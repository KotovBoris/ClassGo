"""Личная демо-песочница: каждый пользователь MAX получает свой класс.

Эксперт открывает бота и за минуту проходит обе роли: он классный руководитель
демо-класса 7Б и одновременно родитель одного из учеников. Остальные родители
виртуальные — после запуска выезда они отвечают сами в течение минуты, поэтому
сводка ответов оживает на глазах. Песочницы разных пользователей не пересекаются.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import random
import secrets
from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from . import services, timeutil
from .config import get_settings
from .models import (
    AccessRole,
    ChildJoinRequest,
    ClassAccess,
    ConsentAudit,
    ConsentStatus,
    CultureEvent,
    DemoAnswer,
    DocumentArtifact,
    Excursion,
    ExcursionParticipant,
    ExcursionStatus,
    ParentContact,
    ReminderLog,
    School,
    SchoolClass,
    Student,
    TicketFile,
    TicketStatus,
)

log = logging.getLogger("classgo.demo")

DEMO_SCHOOL = "Школа «ClassGo» (демо-данные)"
DEMO_CITY = "Казань"

# (ребёнок, дата рождения, родитель, роль)
_KIDS: list[tuple[str, str, str, str]] = [
    ("Сафин Тимур Ренатович", "2013-04-12", "", "Родитель"),  # ребёнок самого пользователя
    ("Абдуллина Алия Ильдаровна", "2013-03-12", "Абдуллина Гульнара Рамилевна", "Мама"),
    ("Бикмуллин Марат Ринатович", "2013-01-22", "Бикмуллин Ринат Айратович", "Папа"),
    ("Валеева Дина Артуровна", "2013-07-16", "Валеева Эльвира Маратовна", "Мама"),
    ("Гайнуллин Артём Русланович", "2013-09-09", "Гайнуллина Алсу Фаридовна", "Мама"),
    ("Егорова София Сергеевна", "2013-02-28", "Егоров Сергей Николаевич", "Папа"),
    ("Журавлёва Мария Андреевна", "2013-11-11", "Журавлёва Ольга Викторовна", "Мама"),
    ("Зарипов Ильназ Ленарович", "2013-04-19", "Зарипова Лейсан Рустемовна", "Мама"),
    ("Козлов Матвей Денисович", "2013-12-03", "Козлов Денис Викторович", "Папа"),
    ("Латыпова Карина Булатовна", "2013-01-17", "Латыпова Резеда Ирековна", "Опекун"),
    ("Морозов Даниил Сергеевич", "2013-05-29", "Морозова Татьяна Юрьевна", "Мама"),
    ("Насырова Диляра Рамилевна", "2013-09-11", "Насырова Лилия Фаритовна", "Мама"),
]

# Состояния учеников в примере «идёт сбор ответов» (по индексам _KIDS, кроме 0).
_SAMPLE_PATTERN = {
    1: "PAID", 2: "PAID", 3: "WAIT", 4: "PAID", 5: "REJECT",
    6: "PAID", 7: "WAIT", 8: "PENDING", 9: "PENDING", 10: "PAID", 11: "PENDING",
}

_REJECT_REASONS = ["Личные причины", "Семейные обстоятельства"]


def new_invite_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]


def sandbox_invite_code(user_id: int) -> str:
    """Постоянная ссылка демо-класса пользователя: не меняется после «Начать демо заново».

    Нужна для QR на слайде живого демо — его печатают заранее.
    """
    key = (get_settings().MAX_BOT_TOKEN or "classgo-demo").encode()
    digest = hmac.new(key, f"demo:{user_id}".encode(), hashlib.sha256).digest()
    return "d" + base64.b32encode(digest).decode().lower()[:9]


# Если на защите сканирует больше людей, чем свободных учеников, — добавляем новых.
_EXTRA_KIDS: list[str] = [
    "Ахметова Камила Ришатовна", "Белов Егор Андреевич", "Галиев Тагир Ильдусович",
    "Давыдова Полина Алексеевна", "Исмагилова Амина Рустамовна", "Киселёв Артур Олегович",
    "Мухаметзянов Айдар Раисович", "Никитина Ева Дмитриевна", "Сабирова Аделина Маратовна",
    "Тихонов Лев Максимович", "Фазлыев Карим Азатович", "Хабибуллина Эмилия Ринатовна",
    "Шарипов Роберт Тимурович", "Юсупова Ясмина Ильнуровна",
]
_SURNAMES = ["Зайцев", "Валиев", "Орлов", "Гарипов", "Соколов", "Закиров", "Морозов", "Латыпов", "Павлов", "Нуриев"]
_BOYS = ["Артём", "Марк", "Тимофей", "Даниил", "Рамиль", "Ильдар", "Максим", "Руслан", "Арсений", "Булат"]
_GIRLS = ["Алиса", "Дарья", "Милана", "Лейла", "Варвара", "София", "Алсу", "Ксения", "Диляра", "Ульяна"]


def _spare_names():
    yield from _EXTRA_KIDS
    for i, surname in enumerate(_SURNAMES):
        for j in range(len(_BOYS)):
            yield f"{surname} {_BOYS[(i + j) % len(_BOYS)]}"
            yield f"{surname}а {_GIRLS[(i + j) % len(_GIRLS)]}"


def active_trip(session: Session, klass: SchoolClass) -> Excursion | None:
    """Выезд, на который сейчас отвечают в демо-классе: последний не отменённый и не начавшийся."""
    for exc in session.exec(select(Excursion).where(Excursion.class_id == klass.id, Excursion.cancelled == False)  # noqa: E712
                            .order_by(Excursion.id.desc())).all():
        if not services.trip_started(exc):
            return exc
    return None


def is_sample_trip(session: Session, klass: SchoolClass, trip: Excursion) -> bool:
    """Пример, созданный вместе с демо-классом, — самый первый выезд класса."""
    first = session.exec(select(Excursion).where(Excursion.class_id == klass.id).order_by(Excursion.id)).first()
    return bool(first) and first.id == trip.id


def retire_previous_trips(session: Session, klass: SchoolClass, keep_id: int) -> int:
    """Новый выезд в демо-классе заменяет прежний пример: тот закрывается без рассылки,
    чтобы у гостя из зала было одно приглашение, а не два."""
    retired = 0
    for exc in session.exec(select(Excursion).where(Excursion.class_id == klass.id, Excursion.id != keep_id,
                                                    Excursion.cancelled == False)).all():  # noqa: E712
        if exc.departed_at:
            continue
        exc.cancelled = True
        exc.status = ExcursionStatus.CLOSED
        session.add(exc)
        for answer in session.exec(select(DemoAnswer).where(DemoAnswer.excursion_id == exc.id,
                                                            DemoAnswer.done == False)).all():  # noqa: E712
            answer.done = True
            session.add(answer)
        retired += 1
    session.commit()
    return retired


def sandbox_class(session: Session, user_id: int) -> SchoolClass | None:
    return session.exec(
        select(SchoolClass).where(SchoolClass.is_demo == True, SchoolClass.owner_user_id == user_id)  # noqa: E712
    ).first()


def _school(session: Session) -> School:
    school = session.exec(select(School).where(School.name == DEMO_SCHOOL)).first()
    if school:
        return school
    school = School(name=DEMO_SCHOOL, city=DEMO_CITY, number="")
    session.add(school)
    session.commit()
    session.refresh(school)
    return school


def _pick_event(session: Session) -> CultureEvent | None:
    events = session.exec(select(CultureEvent)).all()
    paid_pushkin = [e for e in events if e.pushkin_eligible and e.price > 0]
    return (paid_pushkin or events or [None])[0]


def _plausible_answer_time(now: datetime) -> datetime:
    """Время «уже пришедшего» ответа: недавно и не ночью по Москве (ответ в 03:46 выглядит фальшиво)."""
    at = now - timedelta(minutes=random.randint(15, 240))
    hour = timeutil.to_local(at, timeutil.DEFAULT_TZ).hour
    if hour < 7 or hour >= 23:
        evening = timeutil.to_local(at, timeutil.DEFAULT_TZ).replace(hour=19, minute=0, second=0, microsecond=0)
        if hour < 7:
            evening -= timedelta(days=1)
        at = timeutil.local_to_utc(evening, timeutil.DEFAULT_TZ) + timedelta(minutes=random.randint(0, 150))
    return at


def create_sandbox(session: Session, user_id: int, user_name: str = "") -> dict:
    """Создаёт демо-класс пользователя (идемпотентно) и пример выезда в процессе сбора."""
    existing = sandbox_class(session, user_id)
    if existing:
        return sandbox_info(session, existing, user_id, created=False)

    school = _school(session)
    teacher = user_name or "Иванова Анна Сергеевна (демо)"
    klass = SchoolClass(
        grade="7", letter="Б", school_id=school.id, school_name=school.name, school_number="",
        teacher_name=teacher, owner_user_id=user_id, teacher_max_id=user_id,
        invite_code=sandbox_invite_code(user_id), is_demo=True,
    )
    session.add(klass)
    session.commit()
    session.refresh(klass)
    session.add(ClassAccess(class_id=klass.id, user_id=user_id, role=AccessRole.OWNER))

    for idx, (child, birth, parent, role) in enumerate(_KIDS):
        student = Student(class_id=klass.id, full_name=child, birth_date=date.fromisoformat(birth))
        session.add(student)
        session.commit()
        session.refresh(student)
        if idx == 0:
            session.add(ParentContact(
                student_id=student.id, full_name=user_name or "Сафина Алина Маратовна (демо)", phone_number="",
                role=role, max_user_id=user_id, confirmed=True,
            ))
        else:
            session.add(ParentContact(
                student_id=student.id, full_name=parent, phone_number=f"+7900000{idx:04d}",
                role=role, is_virtual=True, confirmed=True,
            ))
    session.commit()

    _create_sample_excursion(session, klass)
    return sandbox_info(session, klass, user_id, created=True)


def _create_sample_excursion(session: Session, klass: SchoolClass) -> Excursion | None:
    event = _pick_event(session)
    if not event:
        return None
    now = datetime.utcnow()
    exc = Excursion(
        class_id=klass.id, culture_event_id=event.id, title=event.title,
        location_name=event.venue, address=event.address,
        event_date=date.today() + timedelta(days=9),
        gathering_time=datetime.strptime("09:30", "%H:%M").time(),
        return_time=datetime.strptime("13:30", "%H:%M").time(),
        # 18:00 по Москве (15:00 UTC) через три дня — как поставил бы учитель.
        deadline=datetime.combine(date.today() + timedelta(days=3), datetime.min.time()) + timedelta(hours=15),
        ticket_price=event.price, ticket_sale_url=event.ticket_url,
        is_pushkin_card=event.pushkin_eligible, status=ExcursionStatus.VOTING,
        school_name=klass.school_name, responsible_teacher=klass.teacher_name,
        order_basis="план воспитательной работы на 2026/2027 учебный год",
        created_by_user_id=klass.owner_user_id,
    )
    session.add(exc)
    session.commit()
    session.refresh(exc)

    students = session.exec(select(Student).where(Student.class_id == klass.id).order_by(Student.id)).all()
    for idx, student in enumerate(students):
        kind = _SAMPLE_PATTERN.get(idx, "PENDING")
        part = ExcursionParticipant(
            excursion_id=exc.id, student_id=student.id,
            consent_status=ConsentStatus.PENDING,
            ticket_status=TicketStatus.WAITING_PAYMENT if exc.ticket_price > 0 else TicketStatus.NOT_REQUIRED,
        )
        if kind in ("PAID", "WAIT", "REJECT"):
            parent = session.exec(select(ParentContact).where(ParentContact.student_id == student.id)).first()
            part.signed_by_name = parent.full_name if parent else None
            part.signed_by_phone = parent.phone_number if parent else None
            part.signed_source = "bot"
            part.signed_at = _plausible_answer_time(now)
            if kind == "REJECT":
                part.consent_status = ConsentStatus.REJECTED
                part.rejection_reason = "Семейные обстоятельства"
            else:
                part.consent_status = ConsentStatus.APPROVED
                if exc.ticket_price > 0:
                    part.ticket_status = TicketStatus.PAID if kind == "PAID" else TicketStatus.WAITING_PAYMENT
        session.add(part)
    session.commit()

    # «Билет куплен» в примере — значит, виртуальный родитель прислал файл: иначе учитель
    # видит «прислали 0 из 8», хотя в списке билеты отмечены.
    if exc.ticket_price > 0:
        from . import tickets  # noqa: PLC0415
        for idx, student in enumerate(students):
            if _SAMPLE_PATTERN.get(idx) == "PAID":
                tickets.save_ticket(session, exc, student.id, content=tickets.demo_ticket_image(exc, student),
                                    filename="demo-ticket.jpg", uploaded_by=None, source="demo")
    return exc


def sandbox_info(session: Session, klass: SchoolClass, user_id: int, created: bool) -> dict:
    own_child = session.exec(
        select(ParentContact).where(ParentContact.max_user_id == user_id)
        .join(Student, Student.id == ParentContact.student_id)
        .where(Student.class_id == klass.id)
    ).first()
    child = session.get(Student, own_child.student_id) if own_child else None
    excursions = session.exec(select(Excursion).where(Excursion.class_id == klass.id)).all()
    return {
        "created": created,
        "class_id": klass.id,
        "class_title": klass.title,
        "child_student_id": child.id if child else None,
        "child_name": child.full_name if child else None,
        # Сначала действующие, новые первыми: [0] — выезд, на который сейчас отвечают.
        "excursion_ids": [e.id for e in sorted(excursions, key=lambda e: (e.cancelled, -e.id))],
    }


def delete_sandbox(session: Session, user_id: int) -> bool:
    klass = sandbox_class(session, user_id)
    if not klass:
        return False
    from . import tickets  # noqa: PLC0415

    student_ids = [s.id for s in session.exec(select(Student).where(Student.class_id == klass.id)).all()]
    exc_ids = [e.id for e in session.exec(select(Excursion).where(Excursion.class_id == klass.id)).all()]
    if exc_ids:
        tickets.delete_where(session, TicketFile.excursion_id.in_(exc_ids))  # и файлы с диска
    for model, column, ids in (
        (DemoAnswer, DemoAnswer.excursion_id, exc_ids),
        (ReminderLog, ReminderLog.excursion_id, exc_ids),
        (ConsentAudit, ConsentAudit.excursion_id, exc_ids),
        (DocumentArtifact, DocumentArtifact.excursion_id, exc_ids),
        (ExcursionParticipant, ExcursionParticipant.excursion_id, exc_ids),
        (ParentContact, ParentContact.student_id, student_ids),
        (ChildJoinRequest, ChildJoinRequest.class_id, [klass.id]),
    ):
        if ids:
            for row in session.exec(select(model).where(column.in_(ids))).all():
                session.delete(row)
    session.commit()
    for exc_id in exc_ids:
        row = session.get(Excursion, exc_id)
        if row:
            session.delete(row)
    for sid in student_ids:
        row = session.get(Student, sid)
        if row:
            session.delete(row)
    for access in session.exec(select(ClassAccess).where(ClassAccess.class_id == klass.id)).all():
        session.delete(access)
    session.commit()
    session.delete(klass)
    session.commit()
    return True


def adopt_virtual_child(session: Session, klass: SchoolClass, user_id: int, name: str) -> Student | None:
    """Живое демо: человек открыл ссылку демо-класса и становится родителем свободного ученика.

    Так на защите член жюри сканирует QR со слайда и через минуту отвечает «Да, пойдёт»
    со своего телефона, а у учителя на экране появляется его имя.
    """
    mine = session.exec(
        select(ParentContact).where(ParentContact.max_user_id == user_id)
        .join(Student, Student.id == ParentContact.student_id).where(Student.class_id == klass.id)
    ).first()
    if mine:
        return session.get(Student, mine.student_id)
    students = session.exec(select(Student).where(Student.class_id == klass.id).order_by(Student.full_name)).all()
    trip = active_trip(session, klass)
    scheduled = {a.student_id for a in session.exec(select(DemoAnswer).where(
        DemoAnswer.excursion_id == (trip.id if trip else -1), DemoAnswer.done == False)).all()}  # noqa: E712

    candidates = []
    for st in students:
        parents = services.student_parents(session, st.id)
        if not parents or not all(p.is_virtual for p in parents):
            continue
        if trip:
            part = services.get_participant(session, trip.id, st.id)
            if not part or part.consent_status != ConsentStatus.PENDING:
                continue
        # Сначала «молчунов»: запланированные ответы виртуальных родителей пусть остаются в демо.
        candidates.append((st.id in scheduled, st.full_name, st, parents[0]))
    if not candidates:
        extra = _add_extra_kid(session, klass, {st.full_name for st in students})
        if not extra:
            return None
        candidates.append((False, extra[0].full_name, extra[0], extra[1]))
    candidates.sort(key=lambda c: (c[0], c[1]))
    _, _, student, parent = candidates[0]
    parent.max_user_id = user_id
    parent.is_virtual = False
    parent.full_name = name or "Гость демо"
    parent.role = "Родитель"
    parent.phone_number = ""
    parent.confirmed = True
    session.add(parent)
    for answer in session.exec(select(DemoAnswer).where(DemoAnswer.student_id == student.id, DemoAnswer.done == False)).all():  # noqa: E712
        answer.done = True
        session.add(answer)
    session.commit()
    return student


def schedule_virtual_answers(session: Session, excursion: Excursion, now: datetime | None = None) -> int:
    """После запуска выезда в демо-классе виртуальные родители отвечают в течение ~минуты.

    Большинство соглашается, один отказывается, двое молчат — чтобы было кого
    напомнить. При платном выезде часть согласившихся потом отмечает билет.
    """
    klass = session.get(SchoolClass, excursion.class_id)
    if not klass or not klass.is_demo:
        return 0
    now = now or datetime.utcnow()
    virtual: list[int] = []
    for part in session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all():
        if part.consent_status != ConsentStatus.PENDING:
            continue
        parents = services.student_parents(session, part.student_id)
        if parents and all(p.is_virtual for p in parents):
            virtual.append(part.student_id)
    rng = random.Random(excursion.id)
    rng.shuffle(virtual)
    silent = virtual[:2]
    rejecting = virtual[2:3]
    delay = 1.0
    planned = 0
    for sid in virtual:
        if sid in silent:
            continue
        delay += rng.uniform(1.5, 4.5)
        decision = "REJECTED" if sid in rejecting else "APPROVED"
        session.add(DemoAnswer(
            excursion_id=excursion.id, student_id=sid, decision=decision,
            reason=rng.choice(_REJECT_REASONS) if decision == "REJECTED" else None,
            due_at=now + timedelta(seconds=delay),
        ))
        planned += 1
        if decision == "APPROVED" and excursion.ticket_price > 0 and rng.random() < 0.6:
            session.add(DemoAnswer(
                excursion_id=excursion.id, student_id=sid, decision="TICKET",
                due_at=now + timedelta(seconds=delay + rng.uniform(8, 20)),
            ))
    session.commit()
    return planned


def process_due_answers(session: Session, now: datetime | None = None) -> set[int]:
    """Применяет наступившие ответы виртуальных родителей. Возвращает id затронутых выездов.

    Каждый ответ — отдельно: сбой на одном (ученика удалили, пока ответ ждал) не откатывает
    остальные и не держит очередь — ответ всё равно помечается выполненным.
    """
    now = now or datetime.utcnow()
    touched: set[int] = set()
    due = session.exec(
        select(DemoAnswer.id).where(DemoAnswer.done == False, DemoAnswer.due_at <= now)  # noqa: E712
        .order_by(DemoAnswer.due_at)
    ).all()
    for answer_id in due:
        answer = session.get(DemoAnswer, answer_id)
        if answer is None or answer.done:
            continue
        excursion_id = answer.excursion_id
        try:
            if _apply_answer(session, answer):
                touched.add(excursion_id)
        except ValueError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("Демо-ответ %s не применён", answer_id)
            session.rollback()
        answer = session.get(DemoAnswer, answer_id)
        if answer:
            answer.done = True
            session.add(answer)
            session.commit()
    return touched


def _apply_answer(session: Session, answer: DemoAnswer) -> bool:
    excursion = session.get(Excursion, answer.excursion_id)
    student = session.get(Student, answer.student_id)
    # Учитель мог удалить ученика или выезд, пока ответ ждал своей очереди.
    if not (excursion and student and services.get_participant(session, excursion.id, student.id)):
        return False
    if answer.decision == "TICKET":
        from . import tickets  # noqa: PLC0415
        tickets.save_ticket(session, excursion, student.id, content=tickets.demo_ticket_image(excursion, student),
                            filename="demo-ticket.jpg", uploaded_by=None, source="demo")
    else:
        parent = session.exec(select(ParentContact).where(ParentContact.student_id == student.id)).first()
        services.apply_consent(
            session, excursion, student_id=student.id, status=answer.decision,
            parent_name=parent.full_name if parent else "", parent_phone=parent.phone_number if parent else "",
            reason=answer.reason, source="demo",
        )
    return True


def _add_extra_kid(session: Session, klass: SchoolClass, taken: set[str]) -> tuple[Student, ParentContact] | None:
    name = next((n for n in _spare_names() if n not in taken), None)
    if not name:
        return None
    student = Student(class_id=klass.id, full_name=name, birth_date=date(2013, 6, 1))
    session.add(student)
    session.commit()
    session.refresh(student)
    parent = ParentContact(student_id=student.id, full_name="Родитель (демо)", phone_number="",
                           role="Родитель", is_virtual=True, confirmed=True)
    session.add(parent)
    for exc in session.exec(select(Excursion).where(Excursion.class_id == klass.id,
                                                    Excursion.cancelled == False)).all():  # noqa: E712
        session.add(ExcursionParticipant(
            excursion_id=exc.id, student_id=student.id, consent_status=ConsentStatus.PENDING,
            ticket_status=TicketStatus.WAITING_PAYMENT if exc.ticket_price > 0 else TicketStatus.NOT_REQUIRED,
        ))
    session.commit()
    session.refresh(parent)
    return student, parent
