"""Доводка перед финалом: смена ответа без стирания, живое демо с залом, тексты бота."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import demo, services
from app.bot import BotService, quoted
from app.db import engine
from app.models import ConsentStatus, Excursion, ParentContact, SchoolClass

from conftest import make_excursion
from test_req_final import FakeClient


def _press(bot: BotService, user_id: int, payload: str, n: int):
    return bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": f"cb-pol-{n}", "payload": payload, "user": {"user_id": user_id}},
        "message": {"recipient": {"chat_id": 1}}})


def _status(exc_id: int, student_id: int):
    with Session(engine) as s:
        return services.get_participant(s, exc_id, student_id)


@pytest.mark.asyncio
async def test_POL_1_change_answer_keeps_old_until_new_choice(client: TestClient) -> None:
    owner = 7_800_001
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id, sid = info["excursion_ids"][0], info["child_student_id"]
    client.post("/api/v1/me/accept-terms", params={"user_id": owner})
    fake = FakeClient()
    bot = BotService(client=fake)
    await _press(bot, owner, f"consent:{exc_id}:{sid}:APPROVED", 1)
    assert _status(exc_id, sid).consent_status == ConsentStatus.APPROVED

    # «Изменить ответ» только показывает выбор — согласие остаётся в силе
    await _press(bot, owner, f"change:{exc_id}:{sid}", 2)
    assert "действует прежний" in fake.answers[-1]["text"]
    assert _status(exc_id, sid).consent_status == ConsentStatus.APPROVED

    # «Нет» → выбор причины, ответ всё ещё прежний
    await _press(bot, owner, f"switch:{exc_id}:{sid}:REJECTED", 3)
    assert "Почему" in fake.answers[-1]["text"]
    assert _status(exc_id, sid).consent_status == ConsentStatus.APPROVED

    # Чужой человек не может переключить ответ
    await _press(bot, owner + 99, f"swreason:{exc_id}:{sid}:family", 4)
    assert _status(exc_id, sid).consent_status == ConsentStatus.APPROVED

    await _press(bot, owner, f"swreason:{exc_id}:{sid}:family", 5)
    part = _status(exc_id, sid)
    assert part.consent_status == ConsentStatus.REJECTED
    assert part.rejection_reason == "Семейные обстоятельства"
    assert part.signed_by_max_user_id == owner

    # Тот же ответ ещё раз — ничего не переписываем
    await _press(bot, owner, f"swreason:{exc_id}:{sid}:family", 6)
    assert fake.answers[-1].get("notification") == "Ответ не изменился"
    assert _status(exc_id, sid).signed_at == part.signed_at

    await _press(bot, owner, f"switch:{exc_id}:{sid}:APPROVED", 7)
    assert _status(exc_id, sid).consent_status == ConsentStatus.APPROVED


def test_POL_2_new_demo_trip_replaces_sample(client: TestClient) -> None:
    owner = 7_800_101
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    sample_id = info["excursion_ids"][0]
    events = client.get("/api/v1/culture-events").json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, events[1]["id"])
    with Session(engine) as s:
        assert s.get(Excursion, sample_id).cancelled is True
    again = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    assert again["excursion_ids"][0] == exc["id"]
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": owner}).json()
    assert [t["excursion_id"] for t in ctx["children"][0]["excursions"]] == [exc["id"]]


def test_POL_3_hall_guests_get_unanswered_kids(client: TestClient) -> None:
    owner = 7_800_201
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    events = client.get("/api/v1/culture-events").json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, events[1]["id"])
    with Session(engine) as s:
        demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=5))
        code = s.get(SchoolClass, info["class_id"]).invite_code
    kids = set()
    for guest in range(7_800_210, 7_800_250):  # 40 человек в зале — больше, чем учеников в классе
        r = client.post("/api/v1/parent/join", params={"user_id": guest}, json={"code": code}).json()
        assert r["status"] == "linked", r
        kids.add(r["children"][0])
        with Session(engine) as s:
            p = s.exec(select(ParentContact).where(ParentContact.max_user_id == guest)).first()
            assert _status(exc["id"], p.student_id).consent_status == ConsentStatus.PENDING
    assert len(kids) == 40


def test_POL_4_bot_texts(client: TestClient) -> None:
    owner = 7_800_301
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    bot = BotService(client=FakeClient())
    with Session(engine) as s:
        exc = s.get(Excursion, info["excursion_ids"][0])
        lines = bot._trip_lines(exc)
    assert lines[0] == quoted(exc.title) and lines[1] == f"Где: {exc.location_name}"


def test_POL_5_sample_trip_is_not_offered_to_hall(client: TestClient) -> None:
    owner = 7_800_401
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    events = client.get("/api/v1/culture-events").json()
    with Session(engine) as s:
        klass = s.get(SchoolClass, info["class_id"])
        sample = demo.active_trip(s, klass)
        assert sample and demo.is_sample_trip(s, klass, sample)
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, events[1]["id"])
    with Session(engine) as s:
        klass = s.get(SchoolClass, info["class_id"])
        live = demo.active_trip(s, klass)
        assert live.id == exc["id"] and not demo.is_sample_trip(s, klass, live)


def test_POL_6_sample_trip_has_demo_ticket_files(client: TestClient) -> None:
    """В выезде-примере «билет куплен» подкреплён файлом: учитель видит присланные билеты, а не «0 из N»."""
    owner = 7_800_061
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id = info["excursion_ids"][0]
    with Session(engine) as s:
        exc = s.get(Excursion, exc_id)
        paid = [p for p in services.participants(s, exc_id) if p.ticket_status.value == "PAID"] \
            if hasattr(services, "participants") else None
    data = client.get(f"/api/v1/excursions/{exc_id}/tickets", params={"user_id": owner}).json()
    if exc.ticket_price <= 0:
        assert data["with_ticket"] == 0
        return
    assert data["with_ticket"] >= 4, data
    assert all(item["source"] == "demo" and item["is_image"] for item in data["items"])
    if paid is not None:
        assert data["with_ticket"] == len(paid)
