"""Требования CTX-*, DEMO-*, BOT-19 (docs/REQUIREMENTS.md)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.bot import BotService
from app.db import engine
from app.models import Excursion, ExcursionParticipant, ParentContact, SchoolClass, Student

from conftest import make_excursion


class FakeClient:
    enabled = True
    def __init__(self) -> None:
        self.sent: list[dict] = []
    async def send_message(self, **k):
        self.sent.append(k)
        return {"ok": True}
    async def answer_callback(self, *a, **k):
        return {"ok": True}


def _bind(uid: int) -> tuple[int, int]:
    with Session(engine) as s:
        klass = s.exec(select(SchoolClass)).first()
        student = s.exec(select(Student).where(Student.class_id == klass.id)).first()
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == student.id)).first()
        parent.max_user_id = uid
        s.add(parent)
        s.commit()
        return student.id, student.full_name


def test_CTX_1_unknown_parent(client: TestClient) -> None:
    r = client.get("/api/v1/parent/context", params={"max_user_id": 987654321})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False and body["children"] == []


def test_CTX_2_bound_parent_sees_child_and_excursion(client: TestClient, first_class, paid_event) -> None:
    sid, name = _bind(811811)
    exc = make_excursion(client, first_class, paid_event["id"])
    body = client.get("/api/v1/parent/context", params={"max_user_id": 811811}).json()
    assert body["found"] is True
    child = next(c for c in body["children"] if c["student_id"] == sid)
    assert child["student_name"] == name
    ex = next(e for e in child["excursions"] if e["excursion_id"] == exc["id"])
    assert ex["traffic_light"] == "GREY"
    assert ex["consent_status"] == "PENDING"


def test_CTX_3_status_reflects_consent(client: TestClient, first_class, paid_event) -> None:
    sid, _ = _bind(822822)
    exc = make_excursion(client, first_class, paid_event["id"])
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    body = client.get("/api/v1/parent/context", params={"max_user_id": 822822}).json()
    child = next(c for c in body["children"] if c["student_id"] == sid)
    ex = next(e for e in child["excursions"] if e["excursion_id"] == exc["id"])
    assert ex["consent_status"] == "APPROVED"
    assert ex["traffic_light"] in ("YELLOW", "GREEN")


def test_DEMO_1_reset(client: TestClient) -> None:
    r = client.post("/api/v1/admin/reset-demo")
    assert r.status_code == 200
    assert r.json()["reset_participants"] >= 1
    exc_id = r.json()["excursion_id"]
    dash = client.get(f"/api/v1/excursions/{exc_id}/dashboard").json()
    assert all(p["consent_status"] == "PENDING" for p in dash["participants"])


@pytest.mark.asyncio
async def test_BOT_19_trips_shows_statuses(client: TestClient, first_class) -> None:
    sid, name = _bind(833833)
    fake = FakeClient()
    svc = BotService(client=fake)
    msg = {"update_type": "message_created", "timestamp": 1,
           "message": {"sender": {"user_id": 833833}, "recipient": {"chat_id": 1},
                       "body": {"text": "/trips"}, "timestamp": 1}}
    await svc.handle_update(msg)
    assert fake.sent, "бот должен ответить на /trips"
    text = fake.sent[-1]["text"]
    assert name in text
