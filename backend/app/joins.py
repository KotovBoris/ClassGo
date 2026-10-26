"""Родитель сам добавляет ребёнка по ссылке класса, учитель подтверждает.

Так класс собирается без Excel: учитель создаёт класс и отправляет ссылку в чат родителей,
каждый родитель подтверждает номер в MAX и вписывает ребёнка, учитель одним нажатием сверяет.
Если номер родителя уже есть в списке класса, он подключается сразу, без заявки.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlmodel import Session, select

from . import services
from .models import (
    ChildJoinRequest,
    ConsentStatus,
    Excursion,
    ExcursionParticipant,
    ParentContact,
    Student,
    TicketStatus,
)

# Открытых заявок: от одного родителя в классе (дети, близнецы) и всего в классе.
MAX_OPEN_PER_PARENT = 3
MAX_OPEN_PER_CLASS = 60
# Решённые заявки (в них телефон заявителя) храним месяц.
KEEP_DECIDED_DAYS = 30


def norm_name(value: str) -> str:
    return " ".join(value.replace("ё", "е").replace("Ё", "Е").lower().split())


def same_child(a: str, b: str) -> bool:
    """Фамилия и имя совпадают, а отчество совпадает или у одного из двоих не указано."""
    pa, pb = norm_name(a).split(), norm_name(b).split()
    if pa[:2] != pb[:2]:
        return False
    return len(pa) < 3 or len(pb) < 3 or pa[2] == pb[2]


def find_match(session: Session, class_id: int, child_name: str) -> Student | None:
    candidates = [s for s in session.exec(select(Student).where(Student.class_id == class_id)).all()
                  if same_child(s.full_name, child_name)]
    exact = [s for s in candidates if norm_name(s.full_name) == norm_name(child_name)]
    return (exact or candidates or [None])[0]


def clean_name(value: str) -> str:
    """«иванов  пётр» → «Иванов Пётр»: учителю в списке нужен аккуратный вид."""
    return " ".join(part[:1].upper() + part[1:] for part in value.strip().split())


def validate_child_name(value: str) -> str:
    name = clean_name(value)
    parts = name.split()
    if len(parts) < 2 or any(len(p) < 2 for p in parts[:2]):
        raise ValueError("Напишите фамилию и имя ребёнка, например: Иванов Пётр")
    if len(name) > 120 or any(ch.isdigit() for ch in name):
        raise ValueError("Проверьте ФИО ребёнка: только буквы, без цифр")
    return name


def create_request(session: Session, class_id: int, *, max_user_id: int, parent_name: str, parent_role: str,
                   phone: str, child_name: str, birth_date: date | None = None) -> tuple[ChildJoinRequest, bool]:
    """Новая заявка или уже открытая на того же ребёнка (повторное нажатие ничего не дублирует)."""
    name = validate_child_name(child_name)
    mine = session.exec(select(ChildJoinRequest).where(
        ChildJoinRequest.class_id == class_id, ChildJoinRequest.max_user_id == max_user_id,
        ChildJoinRequest.status == "PENDING")).all()
    for existing in mine:
        if norm_name(existing.child_name) == norm_name(name):
            return existing, False
    if len(mine) >= MAX_OPEN_PER_PARENT:
        raise ValueError("Уже есть три заявки без ответа — дождитесь, пока классный руководитель их проверит.")
    if len(pending_for_class(session, class_id)) >= MAX_OPEN_PER_CLASS:
        raise ValueError("Классный руководитель ещё не разобрал заявки. Попробуйте позже или напишите ему.")
    req = ChildJoinRequest(class_id=class_id, max_user_id=max_user_id, parent_name=parent_name.strip()[:120],
                           parent_role=(parent_role or "Родитель").strip()[:40], phone_number=phone,
                           child_name=name, child_birth_date=birth_date)
    session.add(req)
    session.commit()
    session.refresh(req)
    return req, True


def pending_for_class(session: Session, class_id: int) -> list[ChildJoinRequest]:
    return list(session.exec(select(ChildJoinRequest).where(
        ChildJoinRequest.class_id == class_id, ChildJoinRequest.status == "PENDING")
        .order_by(ChildJoinRequest.created_at)).all())


def pending_for_parent(session: Session, max_user_id: int) -> list[ChildJoinRequest]:
    return list(session.exec(select(ChildJoinRequest).where(
        ChildJoinRequest.max_user_id == max_user_id, ChildJoinRequest.status == "PENDING")).all())


def has_parent(session: Session, student: Student) -> bool:
    """У ученика уже есть родитель: подключён в MAX или записан с телефоном в списке класса."""
    return any(p.max_user_id or p.phone_number for p in services.student_parents(session, student.id))


def target_student(session: Session, req: ChildJoinRequest) -> Student | None:
    """К кому привяжется родитель: заявка по ссылке от первого родителя (accept_pair_code) знает
    ученика заранее, обычная — ищем по ФИО в списке класса."""
    if req.student_id is not None:
        return session.get(Student, req.student_id)
    return find_match(session, req.class_id, req.child_name)


def needs_check(session: Session, req: ChildJoinRequest) -> Student | None:
    """Обычная заявка на ученика, у которого уже есть родитель. Так по ссылке класса к чужому
    ребёнку может подключиться посторонний, поэтому учитель подтверждает её отдельной кнопкой
    «Да, это второй родитель». Возвращает этого ученика."""
    if req.status != "PENDING" or req.student_id is not None:
        return None
    match = find_match(session, req.class_id, req.child_name)
    return match if match and has_parent(session, match) else None


def approve(session: Session, req: ChildJoinRequest, child_name: str | None = None, *,
            link_existing: bool = False) -> Student:
    """Ученик есть в списке — подключаем родителя к нему, иначе добавляем ребёнка в список и во все
    открытые выезды. Если у ученика уже есть родитель, нужен явный link_existing («Да, это второй
    родитель»), кроме заявки по ссылке от самого первого родителя.

    child_name — ФИО, исправленное учителем при подтверждении («Иванов Петя» → как в журнале).
    """
    if req.student_id is not None:
        student = session.get(Student, req.student_id)
        if student is None:
            raise ValueError("Этого ученика уже нет в списке класса")
    else:
        if child_name:
            req.child_name = validate_child_name(child_name)
        student = find_match(session, req.class_id, req.child_name)
        if student is not None and not link_existing and has_parent(session, student):
            raise ValueError(f"{student.full_name} уже в списке, и у ребёнка есть родитель. Подключайте "
                             "вторым родителем, только если знаете, что это законный представитель.")
    if student is None:
        student = Student(class_id=req.class_id, full_name=req.child_name, birth_date=req.child_birth_date)
        session.add(student)
        session.commit()
        session.refresh(student)
        for exc in session.exec(select(Excursion).where(Excursion.class_id == req.class_id,
                                                        Excursion.cancelled == False)).all():  # noqa: E712
            if services.trip_started(exc) or services.get_participant(session, exc.id, student.id):
                continue
            session.add(ExcursionParticipant(
                excursion_id=exc.id, student_id=student.id, consent_status=ConsentStatus.PENDING,
                ticket_status=TicketStatus.WAITING_PAYMENT if (exc.ticket_price or 0) > 0 else TicketStatus.NOT_REQUIRED,
            ))
    else:
        # ФИО ученика из заявки не меняем: оно идёт в приказ, его исправляет только учитель.
        if req.child_birth_date and not student.birth_date:
            student.birth_date = req.child_birth_date
        session.add(student)
    contact = next((p for p in services.student_parents(session, student.id) if p.max_user_id == req.max_user_id), None)
    if contact is None:
        contact = ParentContact(student_id=student.id, full_name=req.parent_name, phone_number=req.phone_number,
                                role=req.parent_role, max_user_id=req.max_user_id, confirmed=True)
    else:
        contact.confirmed = True
    session.add(contact)
    req.status = "APPROVED"
    req.student_id = student.id
    req.decided_at = datetime.utcnow()
    session.add(req)
    session.commit()
    session.refresh(student)
    return student


def reject(session: Session, req: ChildJoinRequest) -> None:
    req.status = "REJECTED"
    req.decided_at = datetime.utcnow()
    req.phone_number = ""  # номер чужого человека после отказа не храним
    session.add(req)
    session.commit()


def purge_decided(session: Session, days: int = KEEP_DECIDED_DAYS) -> int:
    """Решённые заявки старше месяца удаляем: родитель уже в списке или получил отказ."""
    edge = datetime.utcnow() - timedelta(days=days)
    rows = session.exec(select(ChildJoinRequest).where(ChildJoinRequest.status != "PENDING",
                                                       ChildJoinRequest.decided_at < edge)).all()
    for row in rows:
        session.delete(row)
    if rows:
        session.commit()
    return len(rows)


def open_trips(session: Session, student: Student) -> list[Excursion]:
    """Выезды класса, на которые ещё можно ответить: по ним новому родителю уходят приглашения."""
    return [e for e in session.exec(select(Excursion).where(Excursion.class_id == student.class_id,
                                                            Excursion.cancelled == False)).all()  # noqa: E712
            if not services.trip_started(e)]
