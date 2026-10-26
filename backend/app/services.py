from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import update
from sqlmodel import Session, select

from . import timeutil

from .models import (
    TicketFile,
    UserProfile,
    ConsentAudit,
    ConsentStatus,
    Excursion,
    ExcursionParticipant,
    ExcursionStatus,
    ParentContact,
    ReminderLog,
    SchoolClass,
    Student,
    TicketStatus,
    TrafficLight,
)

REMINDER_KINDS: dict[str, timedelta] = {
    "H72": timedelta(hours=72),
    "H24": timedelta(hours=24),
    "H12": timedelta(hours=12),
}


def compute_traffic_light(participant: ExcursionParticipant) -> TrafficLight:
    if participant.consent_status == ConsentStatus.REJECTED:
        return TrafficLight.RED
    if participant.consent_status == ConsentStatus.PENDING:
        return TrafficLight.GREY
    if participant.ticket_status in (TicketStatus.PAID, TicketStatus.NOT_REQUIRED):
        return TrafficLight.GREEN
    return TrafficLight.YELLOW


def parent_status(participant: ExcursionParticipant, bot_activated: bool) -> str:
    if participant.consent_status == ConsentStatus.APPROVED:
        return "APPROVED"
    if participant.consent_status == ConsentStatus.REJECTED:
        return "REJECTED"
    return "NO_ANSWER" if bot_activated else "BOT_INACTIVE"


def _ticket_status_for_approve(excursion: Excursion, current: TicketStatus) -> TicketStatus:
    if current == TicketStatus.PAID:
        return TicketStatus.PAID
    if excursion.ticket_price and excursion.ticket_price > 0:
        return TicketStatus.WAITING_PAYMENT
    return TicketStatus.NOT_REQUIRED


def get_participant(session: Session, excursion_id: int, student_id: int) -> ExcursionParticipant | None:
    return session.exec(
        select(ExcursionParticipant).where(
            ExcursionParticipant.excursion_id == excursion_id,
            ExcursionParticipant.student_id == student_id,
        )
    ).first()


def student_parents(session: Session, student_id: int) -> list[ParentContact]:
    return list(session.exec(select(ParentContact).where(ParentContact.student_id == student_id)).all())


def local_stamp(value: datetime | None, tz: str | None) -> str:
    """«24.10 в 18:05» по времени школы."""
    return timeutil.stamp(value, tz)


def normalize_phone(raw: str | None) -> str:
    """Телефон к виду 7XXXXXXXXXX: так сверяем номер из MAX со списком класса."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    return digits


def excursion_summary(session: Session, excursion: Excursion) -> dict:
    parts = session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all()
    counts = {"GREEN": 0, "YELLOW": 0, "GREY": 0, "RED": 0}
    for p in parts:
        counts[compute_traffic_light(p).value] += 1
    total = len(parts)
    answered = total - counts["GREY"]
    return {
        "total": total,
        "answered": answered,
        "going": counts["GREEN"] + counts["YELLOW"],
        "not_going": counts["RED"],
        "waiting": counts["GREY"],
        "waiting_ticket": counts["YELLOW"],
        "summary": counts,
    }


def invitation_targets(session: Session, excursion: Excursion) -> list[tuple[Student, ParentContact]]:
    """Живые родители класса с привязанным MAX: им бот шлёт приглашение на выезд."""
    targets: list[tuple[Student, ParentContact]] = []
    students = session.exec(select(Student).where(Student.class_id == excursion.class_id)).all()
    for student in students:
        for parent in student_parents(session, student.id):
            if parent.max_user_id and parent.confirmed and not parent.is_virtual:
                targets.append((student, parent))
    return targets


def apply_consent(
    session: Session,
    excursion: Excursion,
    *,
    student_id: int,
    status: str,
    parent_phone: str = "",
    parent_name: str = "",
    reason: str | None = None,
    source: str = "api",
    max_user_id: int | None = None,
) -> tuple[ExcursionParticipant, bool, str]:
    participant = get_participant(session, excursion.id, student_id)
    if participant is None:
        raise ValueError("Ученик не найден в этом выезде")

    if excursion.cancelled:
        return participant, False, "Выезд отменён — отвечать не нужно."

    def already() -> tuple[ExcursionParticipant, bool, str]:
        existing_by = participant.signed_by_name or "законный представитель"
        when = local_stamp(participant.signed_at, excursion.timezone) or "ранее"
        if participant.consent_status == ConsentStatus.APPROVED:
            return participant, False, f"Согласие уже подписано ({existing_by}, {when})."
        return participant, False, f"Отказ уже записан ({existing_by}, {when})."

    if participant.consent_status != ConsentStatus.PENDING:
        return already()

    if trip_started(excursion):
        return participant, False, "Выезд уже начался — ответ не принимается. Позвоните классному руководителю."

    approved = status == "APPROVED"
    values = {
        "consent_status": ConsentStatus.APPROVED if approved else ConsentStatus.REJECTED,
        "ticket_status": _ticket_status_for_approve(excursion, participant.ticket_status) if approved
        else participant.ticket_status,
        "rejection_reason": None if approved else (reason or "Без указания причины"),
        "signed_by_phone": parent_phone or None,
        "signed_by_name": parent_name or None,
        "signed_by_max_user_id": max_user_id,
        "signed_source": source,
        "signed_at": datetime.utcnow(),
    }
    # Условная запись: если второй родитель успел ответить раньше, этот ответ не перезапишет его.
    result = session.execute(
        update(ExcursionParticipant)
        .where(ExcursionParticipant.id == participant.id,
               ExcursionParticipant.consent_status == ConsentStatus.PENDING)
        .values(**values)
    )
    if result.rowcount == 0:
        session.rollback()
        session.refresh(participant)
        return already()
    msg = "Согласие подписано." if approved else "Отказ записан."

    session.add(
        ConsentAudit(
            excursion_id=excursion.id,
            student_id=student_id,
            parent_phone=parent_phone,
            parent_name=parent_name,
            action="APPROVE" if status == "APPROVED" else "REJECT",
            reason=reason,
            source=source,
        )
    )
    session.commit()
    session.expire(participant)
    session.refresh(participant)
    return participant, True, msg


def trip_started(excursion: Excursion, now: datetime | None = None) -> bool:
    """Выезд начался: наступило время сбора (по Москве). До этого ответ ещё можно поменять —
    например, если ребёнок заболел утром."""
    start = timeutil.starts_at_utc(excursion.event_date, excursion.gathering_time, excursion.timezone)
    return start is not None and (now or datetime.utcnow()) >= start


def can_change_answer(session: Session, participant: ExcursionParticipant, excursion: Excursion,
                      user_id: int | None, *, as_teacher: bool = False, now: datetime | None = None) -> bool:
    """Изменить ответ может только тот, кто его дал, и только до начала выезда.

    Учитель снимает лишь свои бумажные отметки; электронную подпись родителя он не отменяет.
    Второй родитель чужой ответ не отменяет — ему приходит сообщение, кто и как ответил.
    """
    if participant.consent_status == ConsentStatus.PENDING or excursion.cancelled:
        return False
    if trip_started(excursion, now):
        return False
    if as_teacher:
        return participant.signed_source == "paper"
    return bool(user_id) and participant.signed_by_max_user_id == user_id


def pushkin_for(student: Student | None, excursion: Excursion) -> bool | None:
    """Можно ли этому ребёнку платить «Пушкинской картой» (14–22 года на дату выезда).

    None — дата рождения неизвестна, тогда пишем условно «если ребёнку 14+».
    """
    if not excursion.is_pushkin_card:
        return False
    if not student or not student.birth_date:
        return None
    on = excursion.event_date or datetime.utcnow().date()
    b = student.birth_date
    age = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
    return 14 <= age <= 22


def reset_consent(
    session: Session, excursion: Excursion, *, student_id: int, user_id: int | None,
    as_teacher: bool = False, source: str = "api",
) -> tuple[ExcursionParticipant, bool, str]:
    participant = get_participant(session, excursion.id, student_id)
    if participant is None:
        raise ValueError("Ученик не найден в этом выезде")
    if not can_change_answer(session, participant, excursion, user_id, as_teacher=as_teacher):
        return participant, False, "Ответ уже нельзя изменить — позвоните классному руководителю."
    reset_by = "классный руководитель (бумажный бланк)" if as_teacher else (participant.signed_by_name or "")
    participant.consent_status = ConsentStatus.PENDING
    if participant.ticket_status != TicketStatus.PAID:
        participant.ticket_status = (
            TicketStatus.WAITING_PAYMENT if (excursion.ticket_price or 0) > 0 else TicketStatus.NOT_REQUIRED
        )
    participant.rejection_reason = None
    participant.signed_at = None
    participant.signed_by_name = None
    participant.signed_by_phone = None
    participant.signed_by_max_user_id = None
    participant.signed_source = None
    session.add(participant)
    session.add(ConsentAudit(excursion_id=excursion.id, student_id=student_id, action="RESET", source=source,
                             parent_name=reset_by))
    excursion.teacher_notified_complete = False
    session.add(excursion)
    session.commit()
    session.refresh(participant)
    return participant, True, "Выберите ответ заново."


def confirm_ticket(
    session: Session, excursion: Excursion, *, student_id: int, ticket_number: str | None = None, source: str = "api"
) -> tuple[ExcursionParticipant, bool, str]:
    participant = get_participant(session, excursion.id, student_id)
    if participant is None:
        raise ValueError("Ученик не найден в этом выезде")
    if participant.consent_status != ConsentStatus.APPROVED:
        return participant, False, "Сначала нужно подписать согласие."
    if participant.ticket_status == TicketStatus.PAID:
        return participant, False, "Билет уже отмечен как купленный."
    participant.ticket_status = TicketStatus.PAID
    participant.ticket_number = ticket_number or participant.ticket_number
    session.add(participant)
    session.add(
        ConsentAudit(
            excursion_id=excursion.id,
            student_id=student_id,
            action="TICKET_CONFIRM",
            source=source,
        )
    )
    session.commit()
    session.refresh(participant)
    return participant, True, "Билет отмечен как купленный."


def dashboard(session: Session, excursion: Excursion) -> dict:
    parts = session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all()
    counts = {"GREEN": 0, "YELLOW": 0, "GREY": 0, "RED": 0}
    rows = []
    # Учеников, родителей и билеты — тремя запросами на весь класс, а не по три на ученика:
    # сводку учитель держит открытой, и она перечитывается каждые несколько секунд.
    ids = [p.student_id for p in parts]
    students = {s.id: s for s in session.exec(select(Student).where(Student.id.in_(ids))).all()} if ids else {}
    parents_of: dict[int, list[ParentContact]] = {}
    if ids:
        for pc in session.exec(select(ParentContact).where(ParentContact.student_id.in_(ids))
                               .order_by(ParentContact.id)).all():
            parents_of.setdefault(pc.student_id, []).append(pc)
    ticket_of: dict[int, TicketFile] = {}
    for t in session.exec(select(TicketFile).where(TicketFile.excursion_id == excursion.id)
                          .order_by(TicketFile.id)).all():
        ticket_of.setdefault(t.student_id, t)
    for p in parts:
        student = students.get(p.student_id)
        parents = parents_of.get(p.student_id, [])
        # Виртуальные родители демо-класса считаются «подключёнными»: они отвечают сами.
        activated = any(pc.max_user_id or pc.is_virtual for pc in parents)
        main_parent = next((pc for pc in parents if pc.max_user_id), parents[0] if parents else None)
        tl = compute_traffic_light(p)
        counts[tl.value] += 1
        ticket = ticket_of.get(p.student_id)
        rows.append(
            {
                "student_id": p.student_id,
                "full_name": student.full_name if student else f"#{p.student_id}",
                "traffic_light": tl,
                "consent_status": p.consent_status,
                "ticket_status": p.ticket_status,
                "bot_activated": activated,
                "parent_status": parent_status(p, activated),
                "parent_name": main_parent.full_name if main_parent else None,
                "parent_role": main_parent.role if main_parent else None,
                "parent_phone": main_parent.phone_number if main_parent else None,
                "signed_by_name": p.signed_by_name,
                "signed_by_phone": p.signed_by_phone,
                "signed_by_max_user_id": p.signed_by_max_user_id,
                "signed_source": p.signed_source,
                "signed_at": p.signed_at,
                "present": p.present,
                "rejection_reason": p.rejection_reason,
                "ticket_number": p.ticket_number,
                "ticket_file_id": ticket.id if ticket else None,
                "ticket_uploaded_at": ticket.created_at if ticket else None,
            }
        )
    rows.sort(key=lambda r: r["full_name"])
    total = len(parts) or 1
    ready = counts["GREEN"] + counts["RED"]
    return {
        "summary": counts,
        "progress_percent": round(100 * ready / total),
        "participants": rows,
    }


def remind_targets(session: Session, excursion: Excursion) -> list[dict]:
    parts = session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all()
    targets = []
    for p in parts:
        tl = compute_traffic_light(p)
        # Напоминаем только тем, кто не ответил. Об оплате билета не напоминаем:
        # это читалось бы как понуждение семьи к расходам (письмо Минобрнауки ВК-2227/08).
        if tl != TrafficLight.GREY:
            continue
        student = session.get(Student, p.student_id)
        parent = session.exec(
            select(ParentContact).where(
                ParentContact.student_id == p.student_id,
                ParentContact.max_user_id != None,  # noqa: E711
                ParentContact.notifications_enabled == True,  # noqa: E712
            )
        ).first()
        fallback = session.exec(
            select(ParentContact).where(ParentContact.student_id == p.student_id)
        ).first()
        targets.append(
            {
                "student_id": p.student_id,
                "student_name": student.full_name if student else "",
                "max_user_id": parent.max_user_id if parent else None,
                "phone": (parent or fallback).phone_number if (parent or fallback) else "",
                "traffic_light": tl,
            }
        )
    return targets


def unactivated_children(session: Session, excursion: Excursion) -> list[str]:
    names: list[str] = []
    parts = session.exec(
        select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == excursion.id)
    ).all()
    for p in parts:
        if p.consent_status != ConsentStatus.PENDING:
            continue
        parents = student_parents(session, p.student_id)
        if any(pc.max_user_id for pc in parents):
            continue
        student = session.get(Student, p.student_id)
        if student:
            names.append(student.full_name)
    return names


FRESH_INVITE = timedelta(hours=6)
QUIET_HOURS = (21, 8)  # с 21:00 до 08:00 по местному времени родителей не беспокоим


def in_quiet_hours(now: datetime, tz: str | None = None) -> bool:
    hour = timeutil.now_local(tz, now).hour
    start, end = QUIET_HOURS
    return hour >= start or hour < end


def user_timezone(session: Session, max_user_id: int | None, fallback: str | None) -> str:
    """Пояс телефона родителя (если открывал мини-приложение), иначе пояс школы."""
    if max_user_id:
        profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == max_user_id)).first()
        if profile and profile.timezone:
            return profile.timezone
    return fallback or timeutil.DEFAULT_TZ


def due_auto_reminders(session: Session, now: datetime | None = None) -> list[dict]:
    """Кому пора напомнить: не чаще одного раза на ступень (72/24/12 ч до срока).

    Правила, чтобы не превращать бота в спам:
    — первые 6 часов после приглашения не напоминаем (оно только что пришло);
    — из подходящих ступеней шлём только самую срочную, без пачки сообщений;
    — с 21:00 до 08:00 по местному времени родителя не напоминаем вовсе.
    """
    now = now or datetime.utcnow()
    due: list[dict] = []
    excursions = session.exec(
        select(Excursion).where(Excursion.status == ExcursionStatus.VOTING, Excursion.deadline != None)  # noqa: E711
    ).all()
    for exc in excursions:
        if exc.deadline <= now or (exc.created_at and now - exc.created_at < FRESH_INVITE):
            continue
        applicable = [k for k, off in sorted(REMINDER_KINDS.items(), key=lambda kv: kv[1]) if now >= exc.deadline - off]
        if not applicable:
            continue
        kind = applicable[0]
        for target in remind_targets(session, exc):
            if not target["max_user_id"]:
                continue
            if in_quiet_hours(now, user_timezone(session, target["max_user_id"], exc.timezone)):
                continue
            already = session.exec(
                select(ReminderLog).where(
                    ReminderLog.excursion_id == exc.id,
                    ReminderLog.student_id == target["student_id"],
                    ReminderLog.kind == kind,
                )
            ).first()
            if already:
                continue
            due.append({"excursion": exc, "kind": kind, **target})
    return due


MANUAL_REMINDER = "MANUAL"
MANUAL_REMINDER_GAP = timedelta(hours=12)


def recently_reminded(session: Session, excursion_id: int, student_id: int, now: datetime) -> bool:
    """Любое напоминание этому родителю за последние 12 часов — повторно не шлём."""
    return session.exec(select(ReminderLog).where(
        ReminderLog.excursion_id == excursion_id, ReminderLog.student_id == student_id,
        ReminderLog.sent_at >= now - MANUAL_REMINDER_GAP)).first() is not None


def mark_reminder_sent(session: Session, excursion_id: int, student_id: int, kind: str) -> None:
    session.add(ReminderLog(excursion_id=excursion_id, student_id=student_id, kind=kind))
    session.commit()


def other_bound_parents(session: Session, student_id: int, exclude_user_id: int | None) -> list[ParentContact]:
    parents = session.exec(
        select(ParentContact).where(
            ParentContact.student_id == student_id,
            ParentContact.max_user_id != None,  # noqa: E711
        )
    ).all()
    return [p for p in parents if p.max_user_id != exclude_user_id and p.confirmed and not p.is_virtual]


def set_notifications(session: Session, max_user_id: int, enabled: bool) -> int:
    parents = session.exec(
        select(ParentContact).where(ParentContact.max_user_id == max_user_id)
    ).all()
    for p in parents:
        p.notifications_enabled = enabled
        session.add(p)
    session.commit()
    return len(parents)


def confirm_parent_link(session: Session, student_id: int, max_user_id: int, accept: bool) -> ParentContact | None:
    parent = session.exec(
        select(ParentContact).where(
            ParentContact.student_id == student_id, ParentContact.max_user_id == max_user_id
        )
    ).first()
    if not parent:
        return None
    if accept:
        parent.confirmed = True
    else:
        parent.max_user_id = None
        parent.confirmed = False
    session.add(parent)
    session.commit()
    session.refresh(parent)
    return parent


PAIR_LINK_TTL = timedelta(hours=24)


def pair_link_expired(link, now: datetime | None = None) -> bool:
    """Ссылка для второго родителя живёт сутки: пересланная позже — уже не сработает."""
    return (now or datetime.utcnow()) - link.created_at > PAIR_LINK_TTL


def accept_pair_code(session: Session, code: str, user_id: int, name: str = "",
                     phone: str = "") -> tuple[Student, int | None] | None:
    """Второй родитель открыл ссылку. Подписантом он становится только после подтверждения
    классным руководителем: по ссылке пришёл не обязательно законный представитель (ст. 64 СК).

    Возвращает ученика и номер заявки учителю (None — этот MAX уже подключён к ребёнку).
    """
    from .models import BotLinkCode, ChildJoinRequest  # локальный импорт: модели нужны только здесь

    link = session.exec(select(BotLinkCode).where(BotLinkCode.code == code, BotLinkCode.new_parent == True)).first()  # noqa: E712
    if not link or link.used or pair_link_expired(link):
        return None
    student = session.get(Student, link.student_id)
    if not student:
        return None
    link.used = True
    session.add(link)
    existing = session.exec(select(ParentContact).where(
        ParentContact.student_id == student.id, ParentContact.max_user_id == user_id)).first()
    if existing:
        session.commit()
        return student, None
    # student_id сразу: заявка по ссылке от подключённого родителя относится ровно к этому ребёнку.
    req = ChildJoinRequest(class_id=student.class_id, max_user_id=user_id, parent_name=name or "",
                           parent_role="Второй родитель", phone_number=phone, child_name=student.full_name,
                           child_birth_date=student.birth_date, student_id=student.id)
    session.add(req)
    session.commit()
    session.refresh(req)
    return student, req.id


def parent_context(session: Session, max_user_id: int) -> list[dict]:
    parents = session.exec(select(ParentContact).where(ParentContact.max_user_id == max_user_id)).all()
    result: list[dict] = []
    for parent in parents:
        student = session.get(Student, parent.student_id)
        if not student:
            continue
        excursions = session.exec(
            select(Excursion).where(Excursion.class_id == student.class_id)
        ).all()
        klass = session.get(SchoolClass, student.class_id)
        items = []
        newest = max((e.id for e in excursions), default=0)
        for exc in excursions:
            p = get_participant(session, exc.id, student.id)
            # В демо новый выезд закрывает прежний пример без рассылки — его родителю не показываем.
            if not p or (exc.cancelled and klass and klass.is_demo and exc.id != newest):
                continue
            items.append(
                {
                    "excursion_id": exc.id,
                    "title": exc.title,
                    "location_name": exc.location_name,
                    "address": exc.address,
                    "meeting_point": exc.meeting_point,
                    "responsible_teacher": exc.responsible_teacher,
                    "event_date": exc.event_date,
                    "gathering_time": exc.gathering_time.strftime("%H:%M") if exc.gathering_time else None,
                    "return_time": exc.return_time.strftime("%H:%M") if exc.return_time else None,
                    "deadline": exc.deadline,
                    "ticket_price": exc.ticket_price,
                    "ticket_sale_url": exc.ticket_sale_url,
                    "is_pushkin_card": exc.is_pushkin_card,
                    # True / False / None (дата рождения неизвестна) — карта только для 14–22 лет
                    "pushkin_ok": pushkin_for(student, exc),
                    "can_change": can_change_answer(session, p, exc, max_user_id),
                    "ticket_file_id": ticket.id if (ticket := session.exec(select(TicketFile).where(
                        TicketFile.excursion_id == exc.id, TicketFile.student_id == student.id)).first()) else None,
                    "ticket_uploaded_at": ticket.created_at if ticket else None,
                    "started": trip_started(exc),
                    "timezone": exc.timezone or timeutil.DEFAULT_TZ,
                    "cancelled": exc.cancelled,
                    "returned": exc.returned_at is not None,
                    "status": exc.status,
                    "traffic_light": compute_traffic_light(p).value,
                    "consent_status": p.consent_status.value,
                    "ticket_status": p.ticket_status.value,
                    "rejection_reason": p.rejection_reason,
                    "signed_by_name": p.signed_by_name,
                    "signed_at": p.signed_at,
                }
            )
        items.sort(key=lambda i: (i["cancelled"], i["consent_status"] != "PENDING", str(i["event_date"] or "")))
        result.append(
            {
                "student_id": student.id,
                "student_name": student.full_name,
                "birth_date": student.birth_date,
                "class_title": klass.title if klass else "",
                "school_name": klass.school_name if klass else "",
                "teacher_name": klass.teacher_name if klass else "",
                "teacher_phone": klass.teacher_phone if klass else "",
                "is_demo": bool(klass and klass.is_demo),
                "parent_name": parent.full_name,
                "parent_role": parent.role,
                "confirmed": parent.confirmed,
                "notifications_enabled": parent.notifications_enabled,
                "excursions": items,
            }
        )
    return result
