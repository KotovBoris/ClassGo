from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlmodel import Session, select

from . import joins, services, tickets, timeutil
from .auth import strict_auth, upsert_profile_from_bot
from .config import get_settings
from .db import engine
from .max_client import (
    MaxClient,
    callback_button,
    inline_keyboard,
    link_button,
    open_app_button,
)
from .models import (
    ChildJoinRequest,
    AccessRole,
    BotLinkCode,
    ClassAccess,
    ConsentStatus,
    Excursion,
    ExcursionParticipant,
    ParentContact,
    SchoolClass,
    Student,
    TicketStatus,
    TrafficLight,
    UserProfile,
)

log = logging.getLogger("classgo.bot")
settings = get_settings()

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
# Причины без медицинских подробностей: сведения о здоровье — особая категория ПДн (152-ФЗ, ст. 10).
REJECT_REASONS = {"personal": "Личные причины", "family": "Семейные обстоятельства", "other": "Другие планы"}


def human_date(value) -> str:
    if not value:
        return "дата уточняется"
    return f"{WEEKDAYS[value.weekday()]}, {value.day} {MONTHS[value.month - 1]}"


def human_deadline(value: datetime | None, tz: str | None = None) -> str:
    """Срок ответа по времени школы."""
    return timeutil.human_deadline(value, tz)


def is_female(full_name: str) -> bool:
    """Пол по отчеству («-овна», «-евна», «-ична», «-кызы»), иначе по фамилии."""
    parts = full_name.split()
    if len(parts) >= 3:
        patronymic = parts[2].lower()
        return patronymic.endswith(("на", "кызы", "гызы"))
    return bool(parts) and parts[0].lower().endswith(("ова", "ева", "ина", "ая", "ына"))


def first_name(full_name: str) -> str:
    """«Сафин Тимур Ренатович» → «Тимур» (ФИО в школьных списках начинается с фамилии)."""
    parts = full_name.split()
    return parts[1] if len(parts) >= 2 else full_name


def quoted(title: str) -> str:
    """Название в кавычках-ёлочках, если их ещё нет: «Научное шоу «Физика»» выглядит неряшливо."""
    return title if "«" in title else f"«{title}»"


def app_button(text: str, payload: str = "") -> dict:
    return open_app_button(text, settings.MAX_BOT_USERNAME, payload)


class BotService:
    def __init__(self, client: MaxClient | None = None) -> None:
        self.client = client or MaxClient()

    # ------------------------------------------------------------------ входящие
    async def handle_update(self, update: dict) -> None:
        utype = update.get("update_type")
        try:
            if utype == "bot_started":
                await self._on_started(update)
            elif utype == "message_created":
                await self._on_message(update)
            elif utype == "message_callback":
                await self._on_callback(update)
        except Exception as exc:  # noqa: BLE001
            log.exception("Ошибка обработки апдейта %s: %s", utype, exc)

    async def _reply(self, chat_id: int | None, user_id: int | None, text: str,
                     attachments: list[dict] | None = None) -> dict | None:
        return await self.client.send_message(chat_id=chat_id, user_id=None if chat_id else user_id,
                                              text=text, attachments=attachments)

    async def _on_started(self, update: dict) -> None:
        user = update.get("user") or {}
        chat_id = update.get("chat_id")
        user_id = user.get("user_id")
        payload = str(update.get("payload") or "")
        with Session(engine) as session:
            upsert_profile_from_bot(session, user)

        if payload.startswith("bind_"):
            student_id = self._bind_by_code(payload[len("bind_"):], user_id)
            if student_id:
                await self._ask_link_confirmation(chat_id, user_id, student_id)
                return
            await self._reply(chat_id, user_id,
                              "Ссылка устарела. Попросите классного руководителя прислать новую.")
            return

        if payload.startswith("pair_"):
            with Session(engine) as session:
                profile_name = " ".join(p for p in (str(user.get("first_name") or ""), str(user.get("last_name") or "")) if p)
                result = services.accept_pair_code(session, payload[len("pair_"):], user_id, profile_name)
                child_name = result[0].full_name if result else ""
            if result:
                if result[1] is None:
                    await self._send_trips(chat_id, user_id)
                    return
                await self._reply(chat_id, user_id,
                                  f"Заявка отправлена: {child_name}. Классный руководитель сверит, что вы законный "
                                  "представитель, — после этого приглашения на выезды будут приходить и вам.")
                await self.notify_join_request(result[1])
                return
            await self._reply(chat_id, user_id, "Ссылка уже использована или устарела. Попросите прислать новую.")
            return

        if payload.startswith("join_"):
            code = payload[len("join_"):]
            with Session(engine) as session:
                klass = session.exec(select(SchoolClass).where(SchoolClass.invite_code == code)).first()
            if klass:
                await self._reply(
                    chat_id, user_id,
                    f"Вас пригласили в класс {klass.title} ({klass.school_name}).\n\n"
                    "Откройте ClassGo, впишите ребёнка и подтвердите номер телефона — "
                    "классный руководитель подтвердит заявку. Если ваш номер уже есть в списке класса, "
                    "ребёнок найдётся сам.",
                    [inline_keyboard([[app_button("Подключиться к классу", f"join_{code}")]])],
                )
                return

        if payload == "demo":
            await self._reply(
                chat_id, user_id,
                "Демо ClassGo: вы учитель демо-класса 7Б и родитель одного ученика.\n"
                "Создайте выезд — приглашение придёт сюда. Остальные родители ответят сами.",
                [inline_keyboard([[app_button("Открыть демо", "demo")]])],
            )
            return

        text = (
            "Здравствуйте! ClassGo помогает собрать класс на выезд в музей или театр.\n\n"
            "Учителю — список «кто едет» и готовый приказ для директора.\n"
            "Родителю — ответ одной кнопкой прямо здесь, в MAX.\n\n"
            "/trips — выезды вашего ребёнка\n"
            "/help — как это работает"
        )
        await self._reply(chat_id, user_id, text, [inline_keyboard([
            [app_button("Открыть ClassGo")],
            [callback_button("Выезды моего ребёнка", "cmd:trips")],
            [app_button("Попробовать демо", "demo")],
        ])])

    async def _ask_link_confirmation(self, chat_id: int | None, user_id: int | None, student_id: int) -> None:
        with Session(engine) as session:
            student = session.get(Student, student_id)
        name = student.full_name if student else f"#{student_id}"
        await self._reply(
            chat_id, user_id,
            f"Классный руководитель указал вас родителем: {name}.\n"
            "Это ваш ребёнок? Если да, приглашения на выезды будут приходить сюда.",
            [inline_keyboard([
                [callback_button("Да, это мой ребёнок", f"plink:{student_id}:YES")],
                [callback_button("Нет, это ошибка", f"plink:{student_id}:NO")],
            ])],
        )

    async def _on_message(self, update: dict) -> None:
        message = update.get("message") or {}
        body = message.get("body") or {}
        text = (body.get("text") or "").strip().lower()
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        if recipient.get("chat_type") not in (None, "dialog"):
            # Общий чат класса (бот там админ): фото оттуда — не билеты, а ответ на /trips выдал бы
            # в группу данные ребёнка. Из групп бот ничего не принимает, только сам публикует выезды.
            return
        chat_id = recipient.get("chat_id")
        user_id = sender.get("user_id")
        files = [a for a in (body.get("attachments") or []) if a.get("type") in ("image", "file")]
        if files and user_id:
            await self._on_ticket_upload(chat_id, user_id, files[0])
            return
        if text.startswith("/start"):
            await self._on_started({**update, "chat_id": chat_id, "user": sender, "payload": None})
            return
        if text.startswith("/trips"):
            await self._send_trips(chat_id, user_id)
            return
        if text.startswith("/mute"):
            await self._set_mute(chat_id, user_id, enabled=False)
            return
        if text.startswith("/unmute"):
            await self._set_mute(chat_id, user_id, enabled=True)
            return
        if text.startswith("/help"):
            await self._reply(
                chat_id, user_id,
                "Как это работает:\n"
                "1. Классный руководитель зовёт класс на выезд.\n"
                "2. Вы отвечаете кнопкой «Да» или «Нет» прямо в этом чате.\n"
                "3. Учитель видит, кто едет, и получает готовые документы.\n\n"
                "/trips — выезды вашего ребёнка\n"
                "/mute — выключить напоминания\n"
                "/unmute — включить напоминания",
                [inline_keyboard([[app_button("Открыть ClassGo")]])],
            )
            return

    async def _set_mute(self, chat_id: int | None, user_id: int | None, *, enabled: bool) -> None:
        if not user_id:
            return
        with Session(engine) as session:
            affected = services.set_notifications(session, user_id, enabled)
        if not affected:
            text = "Вы пока не подключены к классу — напоминаний не будет."
        elif enabled:
            text = "Напоминания снова включены."
        else:
            text = "Напоминания выключены. Включить снова: /unmute"
        await self._reply(chat_id, user_id, text)

    async def _send_trips(self, chat_id: int | None, user_id: int | None) -> None:
        with Session(engine) as session:
            children = services.parent_context(session, user_id) if user_id else []
        if not children:
            await self._reply(
                chat_id, user_id,
                "Вы пока не подключены к классу. Откройте ссылку от классного руководителя "
                "или попробуйте демо.",
                [inline_keyboard([[app_button("Открыть ClassGo")], [app_button("Попробовать демо", "demo")]])],
            )
            return
        for child in children:
            if not child["confirmed"]:
                await self._ask_link_confirmation(chat_id, user_id, child["student_id"])
                continue
            upcoming = [e for e in child["excursions"] if not e["cancelled"] and not e["started"]]
            if not upcoming:
                await self._reply(chat_id, user_id, f"{child['student_name']}: новых выездов нет.")
                continue
            for item in upcoming:
                with Session(engine) as session:
                    excursion = session.get(Excursion, item["excursion_id"])
                    participant = services.get_participant(session, item["excursion_id"], child["student_id"])
                    if not (excursion and participant):
                        continue
                    text, keyboard = self._parent_card(excursion, child["student_name"], participant)
                await self._reply(chat_id, user_id, text, keyboard)

    # ------------------------------------------------------------------ карточки
    def _trip_lines(self, excursion: Excursion, student: Student | None = None) -> list[str]:
        """Что, когда, деньги — коротко и словами, без канцелярита."""
        lines = [quoted(excursion.title)]
        if excursion.location_name:
            lines.append(f"Где: {excursion.location_name}")
        when = human_date(excursion.event_date)
        if excursion.gathering_time:
            when += f", сбор в {excursion.gathering_time:%H:%M} {excursion.meeting_point}"
        if excursion.return_time:
            when += f", вернёмся к {excursion.return_time:%H:%M}"
        lines.append(f"Когда: {when}")
        if excursion.ticket_price:
            price = f"Билет: {excursion.ticket_price:.0f} ₽ — покупаете сами, на сайте или в кассе."
            pushkin = services.pushkin_for(student, excursion)
            if pushkin is True:
                price += " Можно «Пушкинской картой» ребёнка."
            elif pushkin is None:
                price += " Если ребёнку уже 14, можно «Пушкинской картой»."
            lines.append(price + " Школа деньги не собирает.")
        else:
            lines.append("Вход бесплатный.")
        return lines

    def _parent_card(self, excursion: Excursion, student_name: str, participant) -> tuple[str, list[dict]]:
        """Текст и кнопки карточки выезда для родителя — по текущему статусу ребёнка.

        Требования из тестов с родителями 60+: в первой строке — чей ребёнок и класс, дальше —
        кто пишет (учитель, школа), кнопки называют ребёнка, явно сказано, что платить в чате
        ничего не нужно, и есть контакт учителя.
        """
        with Session(engine) as session:
            student = session.get(Student, participant.student_id)
            klass = session.get(SchoolClass, excursion.class_id)
        name = first_name(student_name)
        class_title = klass.title if klass else ""
        teacher = excursion.responsible_teacher or (klass.teacher_name if klass else "") or "классный руководитель"
        contact = f"Вопросы — {teacher}" + (f", {klass.teacher_phone}" if klass and klass.teacher_phone else "") + "."
        lines = self._trip_lines(excursion, student)
        open_btn = [app_button("Подробнее", f"trip_{excursion.id}")]
        head = f"{student_name}{f' ({class_title})' if class_title else ''}"

        if participant.consent_status == ConsentStatus.PENDING:
            deadline = human_deadline(excursion.deadline, excursion.timezone)
            school = f", {klass.school_name}," if klass and klass.school_name else ""
            keyboard = inline_keyboard([
                [callback_button(f"✅ Да, {name} пойдёт", f"consent:{excursion.id}:{participant.student_id}:APPROVED")],
                [callback_button(f"Нет, {name} не пойдёт", f"consent:{excursion.id}:{participant.student_id}:REJECTED")],
                open_btn,
            ])
            text = "\n".join([
                f"{head} — приглашение на выезд",
                "",
                f"Здравствуйте! Классный руководитель {teacher}{school} зовёт класс:",
                "",
                *lines,
                "",
                (f"Ответьте до {deadline}. " if deadline else "")
                + "Ответ кнопкой — ваша подпись под согласием. Платить в чате ничего не нужно.",
                contact,
            ])
            return text, [keyboard]

        when = services.local_stamp(participant.signed_at, excursion.timezone)
        can_change = not services.trip_started(excursion)
        change_btn = [callback_button("Изменить ответ", f"change:{excursion.id}:{participant.student_id}")]
        if participant.consent_status == ConsentStatus.REJECTED:
            text = "\n".join([
                f"Готово: вы ответили, что {name} не пойдёт ({(participant.rejection_reason or 'без причины').lower()}).",
                f"{head}. Ответ записан{' ' + when if when else ''}. Учитель уже видит его.",
                "", *lines[:2], contact,  # без строки про билет — ребёнок не идёт
            ])
            return text, [inline_keyboard([open_btn] + ([change_btn] if can_change else []))]

        rows: list[list[dict]] = []
        status = f"Готово: {name} идёт на выезд — {human_date(excursion.event_date)}."
        extra: list[str] = [f"{head}. Подпись записана{' ' + when if when else ''}. Учитель уже видит ответ."]
        tail: list[str] = []
        if excursion.ticket_price:
            # О покупке не напоминаем: семья решает сама (ВК-2227/08). Билет присылают по желанию,
            # чтобы учитель видел покупку и на входе показал билеты всего класса.
            with Session(engine) as session:
                ticket = next(iter(tickets.tickets_for(session, excursion.id, participant.student_id)), None)
            if ticket:
                got = services.local_stamp(ticket.created_at, excursion.timezone)
                tail.append(f"Билет получен{' ' + got if got else ''} — учитель покажет его на входе.")
                upload_label = "Отправить другой файл"
            else:
                tail.append("Купили билет? Пришлите его фото или PDF — учитель увидит покупку "
                            "и покажет билеты класса на входе.")
                tail.append("Если трудно оплатить билет — скажите классному руководителю.")
                upload_label = "📎 Отправить фото билета"
            if excursion.ticket_sale_url and not ticket:
                rows.append([link_button("Купить билет на сайте", excursion.ticket_sale_url)])
            if not excursion.returned_at:
                rows.append([callback_button(upload_label, f"tup:{excursion.id}:{participant.student_id}")])
        else:
            extra.append("Больше ничего делать не нужно.")
        rows.append(open_btn)
        if can_change:
            rows.append(change_btn)
        return "\n".join([status, *extra, "", *lines, *tail, contact]), [inline_keyboard(rows)]

    # ------------------------------------------------------------------ кнопки
    async def _on_callback(self, update: dict) -> None:
        callback = update.get("callback") or {}
        callback_id = callback.get("callback_id")
        payload = str(callback.get("payload") or "")
        user = callback.get("user") or {}
        user_id = user.get("user_id")
        message = update.get("message") or {}
        chat_id = (message.get("recipient") or {}).get("chat_id")

        if payload == "cmd:trips":
            await self.client.answer_callback(callback_id, notification="Открываю ваши выезды")
            await self._send_trips(chat_id, user_id)
            return

        if payload.startswith("plink:"):
            _, student_id_s, answer = payload.split(":", 2)
            with Session(engine) as session:
                parent = services.confirm_parent_link(session, int(student_id_s), user_id, answer == "YES")
            if not parent:
                await self.client.answer_callback(callback_id, notification="Запись не найдена.")
            elif answer == "YES":
                await self.client.answer_callback(callback_id, text="Готово: вы подключены к классу.",
                                                  attachments=[])
                await self._send_trips(chat_id, user_id)
            else:
                await self.client.answer_callback(
                    callback_id, text="Хорошо, приглашения по этому ученику не придут. Спасибо, что сообщили.",
                    attachments=[])
            return

        if payload.startswith("docs:"):
            try:
                exc_id = int(payload.split(":", 1)[1])
            except ValueError:
                await self.client.answer_callback(callback_id, notification="Кнопка не сработала. Попробуйте ещё раз.")
                return
            with Session(engine) as session:
                excursion = session.get(Excursion, exc_id)
                if not (excursion and self._is_class_teacher(session, excursion.class_id, user_id)):
                    await self.client.answer_callback(callback_id, notification="Документы получает только учитель класса.")
                    return
                await self.client.answer_callback(callback_id, notification="Готовлю документы…")
                await self.send_documents(session, excursion, user_id)
            return

        # Кнопки по конкретному ребёнку нажимает только подтверждённый родитель этого ребёнка.
        if payload.startswith(("ticket:", "reason:", "change:", "back:", "paper:", "consent:", "terms:",
                               "switch:", "swreason:", "tup:", "tsv:")):
            try:
                parts = payload.split(":")
                student_scope = int(parts[3] if payload.startswith("terms:") else parts[2])
            except (ValueError, IndexError):
                await self.client.answer_callback(callback_id, notification="Кнопка не сработала. Попробуйте ещё раз.")
                return
            if not self._is_linked_parent(user_id, student_scope):
                await self.client.answer_callback(callback_id, notification="Эта кнопка — для родителя ученика.")
                return

        if payload.startswith("tup:"):
            _, exc_id_s, student_id_s = payload.split(":", 2)
            with Session(engine) as session:
                student = session.get(Student, int(student_id_s))
                excursion = session.get(Excursion, int(exc_id_s))
                child = first_name(student.full_name) if student else "—"
                trip = (f"{quoted(excursion.title)}, {human_date(excursion.event_date)}" if excursion else "")
                profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
                if profile:
                    profile.pending_ticket_excursion_id = int(exc_id_s)
                    profile.pending_ticket_student_id = int(student_id_s)
                    profile.pending_ticket_at = datetime.utcnow()
                    session.add(profile)
                    session.commit()
            await self.client.answer_callback(
                callback_id,
                text="\n".join([
                    "Пришлите билет одним сообщением — фото или PDF, где виден QR-код или штрихкод.",
                    f"Ребёнок: {child}. Выезд: {trip}.",
                    "",
                    "Как: нажмите 📎 внизу чата → «Фото» или «Файл».",
                    "Билета ещё нет? Подойдёт скриншот чека — закройте номер карты, баланс и другие покупки.",
                ]),
                attachments=[inline_keyboard([[callback_button("← Вернуться к приглашению",
                                                               f"back:{exc_id_s}:{student_id_s}")]])],
            )
            return

        if payload.startswith(("tsv:", "tsx:")):
            # Файл пришёл без кнопки: родитель выбрал, к какому выезду он относится, или отказался.
            parts = payload.split(":")
            with Session(engine) as session:
                profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
                url = profile.pending_ticket_url if profile else None
                name = profile.pending_ticket_name if profile else None
                if profile:
                    profile.pending_ticket_url = None
                    profile.pending_ticket_name = None
                    session.add(profile)
                    session.commit()
            if payload.startswith("tsx:") or not url:
                await self.client.answer_callback(callback_id, attachments=[],
                                                  text="Хорошо, файл не сохранили." if url or payload.startswith("tsx:")
                                                  else "Файл уже не найден — пришлите его ещё раз.")
                return
            await self.client.answer_callback(callback_id, attachments=[], text="Сохраняю билет…")
            await self._store_ticket(chat_id, user_id, int(parts[1]), int(parts[2]), url, name or "")
            return

        if payload.startswith("jr:"):
            try:
                _, req_id_s, verdict = payload.split(":", 2)
                req_id = int(req_id_s)
            except ValueError:
                await self.client.answer_callback(callback_id, notification="Кнопка не сработала. Попробуйте ещё раз.")
                return
            with Session(engine) as session:
                req = session.get(ChildJoinRequest, req_id)
                if not (req and self._is_class_teacher(session, req.class_id, user_id)):
                    await self.client.answer_callback(callback_id, notification="Заявки подтверждает учитель класса.")
                    return
                if req.status != "PENDING":
                    done = "подтверждена" if req.status == "APPROVED" else "отклонена"
                    await self.client.answer_callback(callback_id, notification=f"Заявка уже {done}.")
                    return
                child, approve, link = req.child_name, verdict in ("A", "L"), verdict == "L"
                second = link or req.student_id is not None  # «второй родитель» или ссылка от первого
            from .main import _decide  # noqa: PLC0415 — общий код с мини-приложением
            with Session(engine) as session:
                req = session.get(ChildJoinRequest, req_id)
                try:
                    student = await _decide(session, req, approve, link_existing=link)
                except ValueError:
                    # «Подтвердить» из старого сообщения, а у ученика уже есть родитель: нужен явный ответ.
                    text, keyboard = self._join_request_card(session, req)
                    await self.client.answer_callback(callback_id, text=text, attachments=keyboard)
                    return
                child = student.full_name if student else child
            if not approve:
                text = f"Заявка на «{child}» отклонена. Родитель получил сообщение."
            elif second:
                text = f"Готово: второй родитель подключён — {child}. Ему ушли приглашения на открытые выезды."
            else:
                text = f"Готово: {child} в списке класса. Родителю ушли приглашения на открытые выезды."
            await self.client.answer_callback(callback_id, attachments=[], text=text)
            return

        if payload.startswith("ticket:"):
            _, exc_id_s, student_id_s = payload.split(":", 2)
            with Session(engine) as session:
                excursion = session.get(Excursion, int(exc_id_s))
                if not excursion:
                    await self.client.answer_callback(callback_id, notification="Выезд не найден.")
                    return
                participant, _, msg = services.confirm_ticket(
                    session, excursion, student_id=int(student_id_s), source="bot"
                )
                student = session.get(Student, participant.student_id)
                text, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
            await self.client.answer_callback(callback_id, text=text, attachments=keyboard, notification=msg)
            await self.notify_teacher_if_complete(int(exc_id_s))
            return

        if payload.startswith("reason:"):
            _, exc_id_s, student_id_s, code = payload.split(":", 3)
            await self._apply_bot_consent(callback_id, user_id, int(exc_id_s), int(student_id_s),
                                          "REJECTED", REJECT_REASONS.get(code, "Другая причина"))
            return

        if payload.startswith("change:"):
            _, exc_id_s, student_id_s = payload.split(":", 2)
            exc_id_i, student_id_i = int(exc_id_s), int(student_id_s)
            with Session(engine) as session:
                excursion = session.get(Excursion, exc_id_i)
                participant = services.get_participant(session, exc_id_i, student_id_i)
                student = session.get(Student, student_id_i)
                if not (excursion and participant):
                    await self.client.answer_callback(callback_id, notification="Выезд не найден.")
                    return
                if not services.can_change_answer(session, participant, excursion, user_id):
                    await self.client.answer_callback(
                        callback_id, notification="Ответ уже нельзя изменить — позвоните классному руководителю.")
                    return
                name = first_name(student.full_name) if student else "ребёнок"
                going = participant.consent_status == ConsentStatus.APPROVED
            now = f"Сейчас: {name} идёт на выезд." if going else f"Сейчас: {name} не пойдёт."
            rows = [] if going else [[callback_button(f"✅ Да, {name} пойдёт",
                                                      f"switch:{exc_id_i}:{student_id_i}:APPROVED")]]
            rows += [
                [callback_button(f"Нет, {name} не пойдёт" if going else "Указать другую причину",
                                 f"switch:{exc_id_i}:{student_id_i}:REJECTED")],
                [callback_button("← Оставить как есть", f"back:{exc_id_i}:{student_id_i}")],
            ]
            await self.client.answer_callback(
                callback_id, text=f"{now} Пока вы не выберете новый ответ, действует прежний.",
                attachments=[inline_keyboard(rows)])
            return

        if payload.startswith(("switch:", "swreason:")):
            kind, exc_id_s, student_id_s, value = payload.split(":", 3)
            exc_id_i, student_id_i = int(exc_id_s), int(student_id_s)
            if kind == "switch" and value == "REJECTED":
                with Session(engine) as session:
                    student = session.get(Student, student_id_i)
                child = first_name(student.full_name) if student else "ребёнок"
                await self.client.answer_callback(
                    callback_id,
                    text=f"Почему {child} не пойдёт?\nУчитель увидит только выбранный вариант. Подробности не нужны.",
                    attachments=[inline_keyboard([
                        [callback_button(label, f"swreason:{exc_id_i}:{student_id_i}:{code}")]
                        for code, label in REJECT_REASONS.items()
                    ] + [[callback_button("← Оставить как есть", f"back:{exc_id_i}:{student_id_i}")]])],
                )
                return
            decision = "APPROVED" if kind == "switch" else "REJECTED"
            reason = None if kind == "switch" else REJECT_REASONS.get(value, "Другая причина")
            await self._switch_answer(callback_id, user_id, exc_id_i, student_id_i, decision, reason)
            return

        if payload.startswith("back:"):
            _, exc_id_s, student_id_s = payload.split(":", 2)
            with Session(engine) as session:
                excursion = session.get(Excursion, int(exc_id_s))
                participant = services.get_participant(session, int(exc_id_s), int(student_id_s))
                student = session.get(Student, int(student_id_s))
                if not (excursion and participant):
                    await self.client.answer_callback(callback_id, notification="Выезд не найден.")
                    return
                text, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
            await self.client.answer_callback(callback_id, text=text, attachments=keyboard)
            return

        if payload.startswith("paper:"):
            _, exc_id_s, student_id_s = payload.split(":", 2)
            with Session(engine) as session:
                excursion = session.get(Excursion, int(exc_id_s))
                klass = session.get(SchoolClass, excursion.class_id) if excursion else None
                # Имя читаем до commit в set_notifications: после закрытия сессии объект уже недоступен.
                teacher = (klass.teacher_name if klass else "") or "классного руководителя"
                if user_id:
                    services.set_notifications(session, user_id, False)  # напоминания в MAX больше не шлём
            await self.client.answer_callback(
                callback_id,
                text=f"Хорошо, ответите на бумаге. Бланк — у классного руководителя ({teacher}).\n"
                     "Напоминаний в MAX больше не будет. Передумаете — нажмите «Назад».",
                attachments=[inline_keyboard([[callback_button("← Назад", f"back:{exc_id_s}:{student_id_s}")]])],
            )
            return

        if not payload.startswith(("consent:", "terms:")):
            return
        try:
            if payload.startswith("terms:"):
                _, step_s, exc_id_s, student_id_s, decision = payload.split(":", 4)
                step = int(step_s)
            else:
                _, exc_id_s, student_id_s, decision = payload.split(":", 3)
                step = 0
            exc_id_i, student_id_i = int(exc_id_s), int(student_id_s)
        except ValueError:
            await self.client.answer_callback(callback_id, notification="Кнопка не сработала. Попробуйте ещё раз.")
            return
        if step == 2 and user_id:
            self._accept_terms(user_id)
        if step == 1 or (user_id and not self._terms_accepted(user_id)):
            # Один раз перед первым ответом: соглашение о ПЭП и отдельное согласие на ПДн.
            await self._ask_terms(callback_id, 2 if step == 1 else 1, exc_id_i, student_id_i, decision)
            return
        if decision == "REJECTED":
            # Сначала уточняем причину — общими словами, без сведений о здоровье (152-ФЗ, ст. 10).
            with Session(engine) as session:
                participant = services.get_participant(session, exc_id_i, student_id_i)
                excursion = session.get(Excursion, exc_id_i)
                student = session.get(Student, student_id_i)
                if participant and excursion and participant.consent_status != ConsentStatus.PENDING:
                    text, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
                    await self.client.answer_callback(callback_id, text=text, attachments=keyboard,
                                                      notification="Ответ уже записан")
                    return
            child = first_name(student.full_name) if student else "ребёнок"
            await self.client.answer_callback(
                callback_id,
                text=f"Почему {child} не пойдёт?\n"
                     "Учитель увидит только выбранный вариант. Подробности не нужны.",
                attachments=[inline_keyboard([
                    [callback_button(label, f"reason:{exc_id_i}:{student_id_i}:{code}")]
                    for code, label in REJECT_REASONS.items()
                ] + [[callback_button("← Назад", f"back:{exc_id_i}:{student_id_i}")]])],
            )
            return
        await self._apply_bot_consent(callback_id, user_id, exc_id_i, student_id_i, decision, None)

    async def _switch_answer(self, callback_id: str, user_id: int | None, exc_id: int, student_id: int,
                             decision: str, reason: str | None) -> None:
        """Новый ответ вместо прежнего: прежний действует, пока новый не записан."""
        with Session(engine) as session:
            excursion = session.get(Excursion, exc_id)
            participant = services.get_participant(session, exc_id, student_id)
            student = session.get(Student, student_id)
            if not (excursion and participant):
                await self.client.answer_callback(callback_id, notification="Выезд не найден.")
                return
            same = participant.consent_status.value == decision and (
                decision == "APPROVED" or participant.rejection_reason == reason)
            if not same:
                participant, changed, msg = services.reset_consent(
                    session, excursion, student_id=student_id, user_id=user_id, source="bot")
            if same or not changed:
                text, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
                await self.client.answer_callback(callback_id, text=text, attachments=keyboard,
                                                  notification="Ответ не изменился" if same else msg)
                return
        await self._apply_bot_consent(callback_id, user_id, exc_id, student_id, decision, reason)

    async def _on_ticket_upload(self, chat_id: int | None, user_id: int, attachment: dict) -> None:
        """Родитель прислал фото или файл. После кнопки «Отправить фото билета» сохраняем сразу,
        иначе спрашиваем, к какому выезду он относится: случайное фото не станет «билетом»."""
        payload = attachment.get("payload") or {}
        url = payload.get("url")
        filename = str(attachment.get("filename") or payload.get("filename") or "")
        if not url:
            await self._reply(chat_id, user_id, "Не получилось открыть файл. Пришлите его ещё раз.")
            return
        with Session(engine) as session:
            profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
            fresh = (profile and profile.pending_ticket_excursion_id and profile.pending_ticket_at
                     and (datetime.utcnow() - profile.pending_ticket_at).total_seconds() < 3600)
            target = (profile.pending_ticket_excursion_id, profile.pending_ticket_student_id) if fresh else None
            options = []
            if not target:
                for child in services.parent_context(session, user_id):
                    for item in child["excursions"]:
                        if (item["consent_status"] == "APPROVED" and item["ticket_price"] and not item["cancelled"]
                                and not item.get("returned")):
                            options.append((item["excursion_id"], child["student_id"],
                                            f"{first_name(child['student_name'])} · {item['title'][:28]}"))
                if options and profile:
                    profile.pending_ticket_url = url
                    profile.pending_ticket_name = filename
                    session.add(profile)
                    session.commit()
        if target:
            await self._store_ticket(chat_id, user_id, target[0], target[1], url, filename)
            return
        if not options:
            await self._reply(chat_id, user_id, "Сейчас билет ни к одному выезду не нужен. "
                                                "Если это ошибка — откройте приглашение и нажмите «Отправить фото билета».")
            return
        await self._reply(chat_id, user_id, "Это билет? Выберите, к какому выезду его сохранить:", [inline_keyboard(
            [[callback_button(label, f"tsv:{exc_id}:{sid}")] for exc_id, sid, label in options[:6]]
            + [[callback_button("Нет, это не билет", "tsx:0:0")]]
        )])

    async def _store_ticket(self, chat_id: int | None, user_id: int, exc_id: int, student_id: int,
                            url: str, filename: str) -> None:
        if not self._is_linked_parent(user_id, student_id):
            await self._reply(chat_id, user_id, "Прислать билет может родитель ученика.")
            return
        content = await self.client.download(url)
        if not content:
            await self._reply(chat_id, user_id, "Не получилось открыть файл. Пришлите его ещё раз.")
            return
        try:
            # Проверка и сжатие фото — в отдельном потоке, чтобы не стоял опрос бота.
            await asyncio.to_thread(_save_ticket, exc_id, student_id, content, filename, user_id)
        except ValueError as err:
            await self._reply(chat_id, user_id, str(err))
            return
        with Session(engine) as session:
            excursion = session.get(Excursion, exc_id)
            student = session.get(Student, student_id)
            profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
            if profile:
                profile.pending_ticket_excursion_id = None
                profile.pending_ticket_student_id = None
                profile.pending_ticket_at = None
                session.add(profile)
                session.commit()
            participant = services.get_participant(session, exc_id, student_id)
            child = first_name(student.full_name) if student else "—"
            trip = quoted(excursion.title)
            when = human_date(excursion.event_date)
            # Одно сообщение: подтверждение и кнопки карточки. Полную карточку выезда второй раз
            # не шлём — она уже выше в чате, а повтор выглядит как новое приглашение.
            _, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
        await self._reply(chat_id, user_id, f"✅ Билет получен: {child}, {trip}, {when}.\n"
                                            "Учитель видит его и покажет на входе вместе с билетами класса.", keyboard)

    async def send_tickets(self, session: Session, excursion: Excursion, user_id: int | None) -> bool:
        """Все билеты класса одним PDF — файлом в чат учителю."""
        if not user_id or not self.client.enabled:
            return False
        content = await asyncio.to_thread(_build_pack, excursion.id)  # сборка не держит event loop
        filename = tickets.pack_filename(session, excursion)
        token = await self.client.upload_file(content, filename)
        if not token:
            return False
        rows = tickets.tickets_for(session, excursion.id)
        caption = (f"Билеты класса — {quoted(excursion.title)}: {len(rows)} шт. "
                   "Кто без билета — на последней странице, её на входе не показывайте. "
                   "Файл откроется и без интернета.")
        return await self.client.send_document(filename=filename, token=token, caption=caption,
                                               user_id=user_id) is not None

    async def notify_join_request(self, request_id: int) -> None:
        """Сообщение учителю о заявке. Если заявки идут потоком, пишем одно, а не на каждую —
        кроме заявок на ученика, у которого уже есть родитель: о них предупреждаем всегда."""
        with Session(engine) as session:
            req = session.get(ChildJoinRequest, request_id)
            klass = session.get(SchoolClass, req.class_id) if req else None
            if not (req and klass):
                return
            recent = [r for r in joins.pending_for_class(session, req.class_id)
                      if r.id != request_id and (req.created_at - r.created_at).total_seconds() < 1800]
            if recent and not joins.needs_check(session, req):
                return
            text, keyboard = self._join_request_card(session, req)
        teacher_id = klass.teacher_max_id or klass.owner_user_id
        if not teacher_id:
            return
        await self.client.send_message(user_id=teacher_id, text=text, attachments=keyboard)

    @staticmethod
    def _join_request_card(session: Session, req: ChildJoinRequest) -> tuple[str, list[dict]]:
        """Текст и кнопки заявки для учителя. Три случая: новый ребёнок; второй родитель по ссылке
        от первого; заявка на ученика из списка, у которого уже есть родитель, — с предупреждением."""
        klass = session.get(SchoolClass, req.class_id)
        title = klass.title if klass else ""
        born = f", {req.child_birth_date:%d.%m.%Y}" if req.child_birth_date else ""
        phone = f", {req.phone_number}" if req.phone_number else ""
        who = f"{req.parent_name or 'без имени'} ({req.parent_role.lower()}){phone}"
        tail = "Все заявки — в ClassGo на экране класса."
        existing = joins.needs_check(session, req)
        if existing:
            asked = f" (в заявке: {req.child_name})" if req.child_name != existing.full_name else ""
            text = (f"{title}: заявка на ученика, который уже есть в списке.\n"
                    f"Ребёнок: {existing.full_name}{asked}\nЗаявитель: {who}\n\n"
                    f"Внимание: {existing.full_name} уже в списке, у ребёнка есть родитель. Подтверждайте, "
                    "только если знаете, что это законный представитель — второй родитель или опекун. " + tail)
            buttons = [[callback_button("Да, это второй родитель", f"jr:{req.id}:L")],
                       [callback_button("Отклонить", f"jr:{req.id}:R")]]
        elif req.student_id is not None:
            child = session.get(Student, req.student_id)
            text = (f"{title}: второй родитель просит подключиться по ссылке от первого.\n"
                    f"Ребёнок: {child.full_name if child else req.child_name}\nРодитель: {who}\n"
                    "Подтвердите, если знаете, что это законный представитель. " + tail)
            buttons = [[callback_button("✅ Подтвердить", f"jr:{req.id}:A")],
                       [callback_button("Отклонить", f"jr:{req.id}:R")]]
        else:
            text = (f"{title}: родитель просит добавить ребёнка в список класса.\n"
                    f"Ребёнок: {req.child_name}{born}\nРодитель: {who}\n"
                    "Подтвердите, если это ученик вашего класса. " + tail + " Там можно подтвердить разом.")
            buttons = [[callback_button("✅ Подтвердить", f"jr:{req.id}:A")],
                       [callback_button("Это не мой ученик", f"jr:{req.id}:R")]]
        return text, [inline_keyboard(buttons)]

    async def notify_parent_added(self, request_id: int) -> None:
        """Уже подключённым родителям: к ребёнку подключили ещё одного взрослого. Если он им
        незнаком, они сразу скажут учителю."""
        with Session(engine) as session:
            req = session.get(ChildJoinRequest, request_id)
            student = session.get(Student, req.student_id) if req and req.student_id else None
            klass = session.get(SchoolClass, student.class_id) if student else None
            others = services.other_bound_parents(session, student.id, req.max_user_id) if student else []
            if not (student and others):
                return
            teacher = (klass.teacher_name if klass else "") or "классный руководитель"
            call = f"{teacher}, {klass.teacher_phone}" if klass and klass.teacher_phone else teacher
            text = (f"{student.full_name}: классный руководитель подключил ещё одного родителя — "
                    f"{req.parent_name or 'без имени'} ({req.parent_role.lower()}). Теперь приглашения на выезды "
                    f"приходят и ему. Если вы его не знаете, сразу сообщите учителю: {call}.")
            targets = [p.max_user_id for p in others]
        for user_id in targets:
            await self.client.send_message(user_id=user_id, text=text)

    async def notify_join_decision(self, request_id: int) -> None:
        with Session(engine) as session:
            req = session.get(ChildJoinRequest, request_id)
            klass = session.get(SchoolClass, req.class_id) if req else None
        if not (req and klass):
            return
        if req.status == "APPROVED":
            text = (f"Классный руководитель подтвердил: {req.child_name}, {klass.title}. "
                    "Теперь приглашения на выезды класса будут приходить сюда.")
        else:
            text = (f"Классный руководитель не подтвердил заявку на «{req.child_name}» ({klass.title}). "
                    "Если это ошибка, позвоните ему" + (f": {klass.teacher_phone}." if klass.teacher_phone else "."))
        await self.client.send_message(user_id=req.max_user_id, text=text)

    async def notify_child_updated(self, student_id: int, by_user_id: int | None, changes: list[str]) -> None:
        with Session(engine) as session:
            student = session.get(Student, student_id)
            klass = session.get(SchoolClass, student.class_id) if student else None
            parent = next((p for p in services.student_parents(session, student_id) if p.max_user_id == by_user_id), None)
        if not (student and klass):
            return
        teacher_id = klass.teacher_max_id or klass.owner_user_id
        if not teacher_id:
            return
        who = parent.full_name if parent and parent.full_name else "Родитель"
        await self.client.send_message(user_id=teacher_id,
                                       text=f"{klass.title}: {who} исправил данные ученика — " + "; ".join(changes) + ".")

    @staticmethod
    def _is_linked_parent(user_id: int | None, student_id: int) -> bool:
        if not user_id:
            return False
        with Session(engine) as session:
            return any(p.max_user_id == user_id and p.confirmed and not p.is_virtual
                       for p in services.student_parents(session, student_id))

    @staticmethod
    def _is_class_teacher(session: Session, class_id: int, user_id: int | None) -> bool:
        klass = session.get(SchoolClass, class_id)
        if not klass:
            return False
        if klass.owner_user_id is None:
            return not strict_auth()
        if not user_id:
            return False
        if klass.owner_user_id == user_id or klass.teacher_max_id == user_id:
            return True
        access = session.exec(select(ClassAccess).where(
            ClassAccess.class_id == class_id, ClassAccess.user_id == user_id)).first()
        return bool(access and access.role in (AccessRole.OWNER, AccessRole.EDIT))

    @staticmethod
    def _terms_accepted(user_id: int) -> bool:
        with Session(engine) as session:
            profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
            return bool(profile and profile.terms_accepted_at)

    @staticmethod
    def _accept_terms(user_id: int) -> None:
        with Session(engine) as session:
            profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == user_id)).first()
            profile = profile or UserProfile(max_user_id=user_id)
            if not profile.terms_accepted_at:
                profile.terms_accepted_at = datetime.utcnow()
                session.add(profile)
                session.commit()
                services.set_notifications(session, user_id, True)  # если раньше выбирал «на бумаге»

    async def _ask_terms(self, callback_id: str, step: int, exc_id: int, student_id: int, decision: str) -> None:
        """Те же тексты, что в мини-приложении (ParentHome → Terms), коротко для чата."""
        with Session(engine) as session:
            excursion = session.get(Excursion, exc_id)
            klass = session.get(SchoolClass, excursion.class_id) if excursion else None
            student = session.get(Student, student_id)
        school = (klass.school_name if klass else "") or "школа"
        child = first_name(student.full_name) if student else "ребёнок"
        answer = f"Да, {child} пойдёт" if decision == "APPROVED" else f"Нет, {child} не пойдёт"
        if step == 1:
            text = "\n".join([
                f"Ваш ответ «{answer}» ещё не отправлен — осталось 2 нажатия.",
                "Один раз перед первым ответом. Шаг 1 из 2 — соглашение об электронной подписи.",
                "",
                f"{school} и я, законный представитель ученика, договорились:",
                "1. Мой ответ кнопкой в ClassGo — простая электронная подпись (ст. 9 63-ФЗ); документ с ней "
                "равнозначен бумажному с моей подписью.",
                "2. Подписанта определяют по аккаунту MAX и его номеру телефона, совпадающему с номером у школы.",
                "3. Так подписываются только согласия и отказы на участие ребёнка в экскурсиях.",
                "4. Не передаю телефон и аккаунт MAX другим, об утрате сразу сообщаю классному руководителю.",
                "5. Могу отказаться в любой момент и отвечать на бумаге.",
            ])
            accept = callback_button("✅ Принимаю", f"terms:1:{exc_id}:{student_id}:{decision}")
            decline = callback_button("Отвечать на бумаге", f"paper:{exc_id}:{student_id}")
        else:
            text = "\n".join([
                "Шаг 2 из 2 — согласие на обработку персональных данных (отдельный документ, ст. 9 152-ФЗ).",
                "",
                f"Оператор — {school}. Данные: мои ФИО, телефон, ID в MAX, статус (мать, отец, опекун); ФИО, класс и "
                "дата рождения ребёнка (если указана); мои ответы, их время и причина отказа; отметки переклички; "
                "присланные мной файлы билетов (удаляются через 7 дней после выезда).",
                "Цель: участие ребёнка в экскурсиях школы — приглашения, согласия, списки, документы.",
                "Действия: сбор, запись, хранение, уточнение, использование, передача руководителю группы и "
                "администрации школы, удаление; автоматизированно. По поручению школы данные обрабатывает "
                "ClassGo, сообщения идут через MAX, хранение — в России.",
                "Срок: до конца учебного года или до отзыва — в приложении ClassGo или заявлением в школу.",
            ])
            accept = callback_button("✅ Даю согласие на обработку данных", f"terms:2:{exc_id}:{student_id}:{decision}")
            decline = callback_button("Не даю — отвечу на бумаге", f"paper:{exc_id}:{student_id}")
        await self.client.answer_callback(callback_id, text=text, attachments=[inline_keyboard([
            [accept], [decline], [callback_button("← Назад", f"back:{exc_id}:{student_id}")],
        ])])

    async def _apply_bot_consent(self, callback_id: str, user_id: int | None, exc_id: int,
                                 student_id: int, decision: str, reason: str | None) -> None:
        with Session(engine) as session:
            excursion = session.get(Excursion, exc_id)
            if not excursion:
                await self.client.answer_callback(callback_id, notification="Выезд не найден.")
                return
            parent = None
            if user_id:
                parent = session.exec(
                    select(ParentContact).where(
                        ParentContact.max_user_id == user_id, ParentContact.student_id == student_id
                    )
                ).first()
            participant, changed, msg = services.apply_consent(
                session, excursion, student_id=student_id, status=decision,
                parent_name=parent.full_name if parent else "Законный представитель",
                parent_phone=parent.phone_number if parent else "",
                reason=reason, source="bot", max_user_id=user_id,
            )
            student = session.get(Student, student_id)
            text, keyboard = self._parent_card(excursion, student.full_name if student else "", participant)
        await self.client.answer_callback(callback_id, text=text, attachments=keyboard, notification=msg)
        if changed:
            await self.notify_consent(exc_id, student_id, exclude_user_id=user_id)
            await self.notify_teacher_if_complete(exc_id)

    # ------------------------------------------------------------------ исходящие
    async def invite_one(self, excursion_id: int, student_id: int, user_id: int) -> bool:
        """Приглашение одному родителю — тому, кто только что подключился к классу."""
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            participant = services.get_participant(session, excursion_id, student_id)
            student = session.get(Student, student_id)
            if not (excursion and participant and student) or excursion.cancelled:
                return False
            if participant.consent_status != ConsentStatus.PENDING or services.trip_started(excursion):
                return False
            text, keyboard = self._parent_card(excursion, student.full_name, participant)
        return await self.client.send_message(user_id=user_id, text=text, attachments=keyboard) is not None

    async def notify_owner_joined(self, klass: SchoolClass, parent_name: str, student_name: str,
                                  invited: bool = True) -> None:
        teacher_id = klass.teacher_max_id or klass.owner_user_id
        if not teacher_id:
            return
        await self.client.send_message(
            user_id=teacher_id,
            text=f"{klass.title}: подключился родитель — {parent_name} ({student_name}). "
                 + ("Приглашение на выезд уже отправлено." if invited
                    else "Приглашение придёт, когда вы отправите выезд."),
        )

    def _going_parents(self, session: Session, excursion: Excursion) -> list[tuple[Student, ParentContact, object]]:
        result = []
        for part in session.exec(select(ExcursionParticipant).where(
                ExcursionParticipant.excursion_id == excursion.id)).all():
            student = session.get(Student, part.student_id)
            for parent in services.student_parents(session, part.student_id):
                if parent.max_user_id and not parent.is_virtual and student:
                    result.append((student, parent, part))
        return result

    async def notify_milestone(self, excursion_id: int, kind: str) -> int:
        """День выезда: «группа выехала» (кто на месте, кто не пришёл) и «группа вернулась»."""
        messages: list[tuple[int, str]] = []
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            if not excursion:
                return 0
            now = timeutil.now_local(excursion.timezone).strftime("%H:%M")
            klass = session.get(SchoolClass, excursion.class_id)
            teacher = (klass.teacher_name if klass else "") or "классный руководитель"
            call = f"{teacher}, {klass.teacher_phone}" if klass and klass.teacher_phone else teacher
            for student, parent, part in self._going_parents(session, excursion):
                if part.consent_status != ConsentStatus.APPROVED:
                    continue
                name = first_name(student.full_name)
                if kind == "departed":
                    if part.present is False:
                        came = "пришла" if is_female(student.full_name) else "пришёл"
                        text = (f"{name} не {came} на сбор, группа выехала в {now} — {quoted(excursion.title)}.\n"
                                f"Если всё в порядке, просто сообщите учителю: {call}.")
                    elif part.present is True:
                        text = f"{name} с классом: группа выехала в {now} — {quoted(excursion.title)}."
                    else:
                        text = f"Группа выехала в {now} — {quoted(excursion.title)}."
                else:
                    if part.present is False:
                        continue
                    text = f"Группа вернулась в {now} — {quoted(excursion.title)}. {name} с классом, можно встречать."
                messages.append((parent.max_user_id, text))
        sent = 0
        for user_id, text in messages:
            if await self.client.send_message(user_id=user_id, text=text) is not None:
                sent += 1
        return sent

    async def notify_cancelled(self, excursion_id: int) -> int:
        messages: list[tuple[int, str]] = []
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            if not excursion:
                return 0
            for student, parent, part in self._going_parents(session, excursion):
                if part.consent_status == ConsentStatus.REJECTED:
                    continue
                lessons = (f"{first_name(student.full_name)} учится по расписанию. "
                           if excursion.event_date and excursion.event_date.weekday() < 5 else "")
                messages.append((parent.max_user_id,
                                 f"Отменён выезд {quoted(excursion.title)}, {human_date(excursion.event_date)}. "
                                 f"{lessons}Если вы уже купили билет — вернуть его можно там, где покупали."))
        sent = 0
        for user_id, text in messages:
            if await self.client.send_message(user_id=user_id, text=text) is not None:
                sent += 1
        return sent

    async def invite_parents(self, excursion_id: int) -> int:
        """Персональное приглашение каждому подключённому родителю — с кнопками ответа."""
        sent = 0
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            if not excursion or excursion.cancelled:
                return 0
            cards = []
            for student, parent in services.invitation_targets(session, excursion):
                participant = services.get_participant(session, excursion.id, student.id)
                if not participant or participant.consent_status != ConsentStatus.PENDING:
                    continue
                text, keyboard = self._parent_card(excursion, student.full_name, participant)
                cards.append((parent.max_user_id, text, keyboard))
        for user_id, text, keyboard in cards:
            if await self.client.send_message(user_id=user_id, text=text, attachments=keyboard) is not None:
                sent += 1
        return sent

    async def notify_consent(self, excursion_id: int, student_id: int, exclude_user_id: int | None = None) -> None:
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            student = session.get(Student, student_id)
            participant = services.get_participant(session, excursion_id, student_id)
            others = services.other_bound_parents(session, student_id, exclude_user_id)
        if not (excursion and student and participant) or not others:
            return
        if participant.consent_status.value == "APPROVED":
            verdict = "подписано согласие"
        else:
            verdict = "записан отказ"
        by = participant.signed_by_name or "законный представитель"
        when = services.local_stamp(participant.signed_at, excursion.timezone)
        text = f"{student.full_name}, выезд {quoted(excursion.title)}: {verdict} ({by}{', ' + when if when else ''})."
        for parent in others:
            if parent.is_virtual:
                continue
            await self.client.send_message(user_id=parent.max_user_id, text=text)

    async def notify_teacher_if_complete(self, excursion_id: int) -> bool:
        """Один раз сообщает учителю, что ответили все родители, и предлагает документы."""
        with Session(engine) as session:
            excursion = session.get(Excursion, excursion_id)
            if not excursion or excursion.teacher_notified_complete:
                return False
            klass = session.get(SchoolClass, excursion.class_id)
            teacher_id = (klass.teacher_max_id or klass.owner_user_id) if klass else None
            stats = services.excursion_summary(session, excursion)
            if not teacher_id or stats["waiting"] > 0 or stats["total"] == 0:
                return False
            if klass.expected_size and stats["total"] < klass.expected_size:
                return False  # в классе есть дети, чьи семьи ещё не подключились
            excursion.teacher_notified_complete = True
            session.add(excursion)
            session.commit()
            title, class_title = excursion.title, klass.title
        text = (
            f"{class_title}, {quoted(title)}: ответили все родители.\n"
            f"Отпускают: {stats['going']}, не смогут: {stats['not_going']}.\n\n"
            "Документы готовы: приказ, список группы, реестр согласий, ведомость инструктажа."
        )
        await self.client.send_message(user_id=teacher_id, text=text, attachments=[inline_keyboard([
            [callback_button("Получить документы", f"docs:{excursion_id}")],
            [app_button("Открыть выезд", f"trip_{excursion_id}")],
        ])])
        return True

    async def send_documents(self, session: Session, excursion: Excursion, user_id: int | None) -> bool:
        """Отправляет приказ (PDF и DOCX) файлами в личный чат с учителем."""
        from .documents import build_order_docx, build_order_pdf

        if not user_id or not self.client.enabled:
            return False
        klass = session.get(SchoolClass, excursion.class_id)
        stamp = excursion.event_date.strftime("%d.%m") if excursion.event_date else ""
        base = f"Приказ_{klass.title if klass else ''}_{stamp}".strip("_")
        files = [
            (f"{base}.pdf", build_order_pdf(session, excursion)),
            (f"{base}.docx", build_order_docx(session, excursion)),
        ]
        stats = services.excursion_summary(session, excursion)
        delivered = False
        # Сначала загружаем оба файла: пока грузится второй, MAX успевает обработать первый.
        uploaded = [(filename, await self.client.upload_file(content, filename)) for filename, content in files]
        for idx, (filename, token) in enumerate(uploaded):
            if not token:
                continue
            caption = ""
            if idx == 0:
                caption = (
                    f"Документы по выезду {quoted(excursion.title)}: приказ, список группы ({stats['going']} чел.), "
                    "реестр согласий, ведомость инструктажа.\nPDF — для печати, DOCX — для правки."
                )
            result = await self.client.send_document(filename=filename, token=token, caption=caption,
                                                      user_id=user_id)
            delivered = delivered or result is not None
        return delivered

    async def remind(self, excursion: Excursion, session: Session,
                     now: datetime | None = None) -> tuple[int, list[str], dict]:
        """Кнопка учителя «Напомнить»: не ночью по времени родителя и не чаще раза в 12 часов."""
        skipped = {"quiet": 0, "recent": 0}
        if excursion.cancelled:
            return 0, [], skipped
        targets = services.remind_targets(session, excursion)
        delivered: list[str] = []
        now = now or datetime.utcnow()
        for t in targets:
            if not (t.get("max_user_id") and self.client.enabled):
                continue
            participant = services.get_participant(session, excursion.id, t["student_id"])
            if not participant:
                continue
            if services.in_quiet_hours(now, services.user_timezone(session, t["max_user_id"], excursion.timezone)):
                skipped["quiet"] += 1
                continue
            if services.recently_reminded(session, excursion.id, t["student_id"], now):
                skipped["recent"] += 1
                continue
            text, keyboard = self._parent_card(excursion, t["student_name"], participant)
            result = await self.client.send_message(user_id=t["max_user_id"], text="Напоминание\n\n" + text,
                                                    attachments=keyboard)
            if result is not None:
                delivered.append(t["student_name"])
                services.mark_reminder_sent(session, excursion.id, t["student_id"], services.MANUAL_REMINDER)
        return len(targets), delivered, skipped

    async def send_auto_reminder(self, target: dict) -> bool:
        if not self.client.enabled:
            return False
        excursion: Excursion = target["excursion"]
        with Session(engine) as session:
            participant = services.get_participant(session, excursion.id, target["student_id"])
            if not participant:
                return False
            text, keyboard = self._parent_card(excursion, target["student_name"], participant)
        result = await self.client.send_message(user_id=target["max_user_id"], text="Напоминание\n\n" + text,
                                                attachments=keyboard)
        return result is not None

    def _consent_keyboard(self, excursion: Excursion, student_id: int) -> list[dict]:
        return self._consent_keyboard_raw(excursion.id, student_id)

    def _consent_keyboard_raw(self, excursion_id: int, student_id: int) -> list[dict]:
        approve = callback_button("✅ Да, пойдёт", f"consent:{excursion_id}:{student_id}:APPROVED")
        reject = callback_button("Нет, не пойдёт", f"consent:{excursion_id}:{student_id}:REJECTED")
        return [inline_keyboard([[approve], [reject]])]

    async def publish_to_chat(self, excursion: Excursion, chat_id: int) -> dict | None:
        lines = ["Новый выезд класса:", *self._trip_lines(excursion)]
        if excursion.deadline:
            lines.append(f"Ответить до: {human_deadline(excursion.deadline, excursion.timezone)}")
        lines.append("")
        lines.append("Родители, ответьте одной кнопкой в ClassGo.")
        attachments = [inline_keyboard([[app_button("Ответить", f"trip_{excursion.id}")]])]
        return await self.client.send_message(chat_id=chat_id, text="\n".join(lines), attachments=attachments)

    async def tag_unactivated(self, excursion: Excursion, chat_id: int, names: list[str]) -> dict | None:
        # Без имён: в общем чате нельзя называть, чья семья не ответила или выбрала бумагу.
        text = (
            f"Выезд {quoted(excursion.title)}: ждём ответа ещё от {len(names)} "
            f"{'семьи' if len(names) % 10 == 1 and len(names) % 100 != 11 else 'семей'}.\n"
            "Родители, кто ещё не подключился: откройте ClassGo, впишите ребёнка и подтвердите номер телефона. "
            "Бумажный бланк — у классного руководителя."
        )
        with Session(engine) as session:
            klass = session.get(SchoolClass, excursion.class_id)
            code = klass.invite_code if klass else None
        payload = f"join_{code}" if code else ""
        attachments = [inline_keyboard([[app_button("Подключиться", payload)]])]
        return await self.client.send_message(chat_id=chat_id, text=text, attachments=attachments)

    def _bind_by_code(self, code: str, user_id: int | None) -> int | None:
        if not user_id:
            return None
        with Session(engine) as session:
            link = session.exec(select(BotLinkCode).where(BotLinkCode.code == code, BotLinkCode.used == False)).first()  # noqa: E712
            if not link:
                return None
            parent = session.exec(
                select(ParentContact).where(ParentContact.student_id == link.student_id)
            ).first()
            if parent:
                parent.max_user_id = user_id
                session.add(parent)
            link.used = True
            session.add(link)
            session.commit()
            return link.student_id


def _save_ticket(exc_id: int, student_id: int, content: bytes, filename: str, user_id: int) -> None:
    """Для asyncio.to_thread: своя сессия — Session нельзя делить между потоками."""
    with Session(engine) as session:
        excursion = session.get(Excursion, exc_id)
        if excursion is None:
            raise ValueError("Выезд не найден — откройте приглашение ещё раз")
        tickets.save_ticket(session, excursion, student_id, content=content, filename=filename,
                            uploaded_by=user_id, source="bot")


def _build_pack(excursion_id: int) -> bytes:
    """Для asyncio.to_thread: своя сессия — Session нельзя делить между потоками."""
    with Session(engine) as session:
        return tickets.build_tickets_pdf(session, session.get(Excursion, excursion_id))


def class_chat_id(session: Session, excursion: Excursion) -> int | None:
    klass = session.get(SchoolClass, excursion.class_id)
    return klass.chat_id if klass else None


__all__ = ["BotService", "class_chat_id", "TrafficLight"]
