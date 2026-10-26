"""Проверка адаптера MAX: формирование апдейтов и обработка нажатий кнопок.

Ходит по «фейковому» MAX-клиенту, который записывает исходящие вызовы вместо сети —
это позволяет проверить весь протокол бота без реального токена (offline-режим).
"""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.bot import BotService
from app.db import engine
from app.models import Excursion, ParentContact, SchoolClass, Student
from app.services import compute_traffic_light
from app.models import TrafficLight


class FakeMaxClient:
    """Заглушка MAX Bot API: фиксируем вызовы, ничего не отправляем наружу."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.answers: list[dict] = []

    @property
    def enabled(self) -> bool:
        return True

    async def get_me(self) -> dict:
        return {"name": "fake"}

    async def get_updates(self, **kwargs) -> dict:  # pragma: no cover
        return {"updates": [], "marker": None}

    async def send_message(self, **kwargs) -> dict:
        self.sent.append(kwargs)
        return {"ok": True}

    async def answer_callback(self, callback_id: str, **kwargs) -> dict:
        self.answers.append({"callback_id": callback_id, **kwargs})
        return {"ok": True}


@pytest.mark.asyncio
async def test_bot_started_sends_greeting() -> None:
    fake = FakeMaxClient()
    svc = BotService(client=fake)
    await svc.handle_update({
        "update_type": "bot_started", "timestamp": 1, "chat_id": 555,
        "user": {"user_id": 42, "name": "Родитель"}, "payload": None,
    })
    assert fake.sent, "бот должен отправить приветствие"
    attachments = fake.sent[-1]["attachments"]
    types = {b["type"] for row in attachments[0]["payload"]["buttons"] for b in row}
    assert "open_app" in types  # нативная кнопка открытия мини-приложения


@pytest.mark.asyncio
async def test_callback_consent_updates_status() -> None:
    with Session(engine) as session:
        klass = session.exec(select(SchoolClass)).first()
        student = session.exec(select(Student).where(Student.class_id == klass.id)).first()
        excursion = session.exec(select(Excursion)).first()
        parent = session.exec(select(ParentContact).where(ParentContact.student_id == student.id)).first()
        parent.max_user_id = 777
        session.add(parent)
        session.commit()
        exc_id, student_id = excursion.id, student.id

    fake = FakeMaxClient()
    svc = BotService(client=fake)
    await svc.handle_update({
        "update_type": "message_callback", "timestamp": 2,
        "callback": {
            "callback_id": "cb-1",
            "payload": f"consent:{exc_id}:{student_id}:APPROVED",
            "user": {"user_id": 777, "name": "Родитель"},
        },
    })
    assert fake.answers and fake.answers[-1]["callback_id"] == "cb-1"

    with Session(engine) as session:
        from app.models import ExcursionParticipant

        p = session.exec(select(ExcursionParticipant).where(
            ExcursionParticipant.excursion_id == exc_id,
            ExcursionParticipant.student_id == student_id,
        )).first()
        assert compute_traffic_light(p) in (TrafficLight.GREEN, TrafficLight.YELLOW)


@pytest.mark.asyncio
async def test_remind_sends_only_to_linked_parents() -> None:
    with Session(engine) as session:
        excursion = session.exec(select(Excursion)).first()
        fake = FakeMaxClient()
        svc = BotService(client=fake)
        targeted, delivered, _skipped = await svc.remind(excursion, session)
        assert targeted >= 0
        # отправляем только тем, у кого есть max_user_id
        for call in fake.sent:
            assert call.get("user_id") is not None
