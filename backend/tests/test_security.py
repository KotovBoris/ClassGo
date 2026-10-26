"""Безопасность в боевом (строгом) режиме: личность только из подписанного initData MAX.

Включаем MAX_VALIDATE_INIT_DATA и токен бота для подписи; сам бот остаётся выключенным
(MAX_BOT_MODE=off), чтобы тесты не ходили в сеть.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.bot import BotService
from app.config import get_settings
from app.db import engine
from app.max_validate import build_signature_for_test
from app.models import Excursion, ExcursionParticipant, ParentContact

TOKEN = "security-test-token"
TEACHER, PARENT, STRANGER = 8_800_001, 8_800_002, 8_800_666


def init_data(uid: int, name: str = "Тест", token: str = TOKEN, auth_date: int | None = None) -> str:
    pairs = {"auth_date": str(auth_date or int(time.time())), "query_id": "q1",
             "user": json.dumps({"id": uid, "first_name": name}, ensure_ascii=False)}
    sig = build_signature_for_test(pairs, token)
    return "&".join(f"{k}={urllib.parse.quote(v)}" for k, v in pairs.items()) + f"&hash={sig}"


def as_user(uid: int, **kw) -> dict:
    return {"X-Max-Init-Data": init_data(uid, **kw)}


@pytest.fixture()
def strict(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_VALIDATE_INIT_DATA", True)
    monkeypatch.setattr(settings, "MAX_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "MAX_BOT_MODE", "off")
    yield settings


@pytest.fixture()
def world(client: TestClient, strict) -> dict:
    """Класс учителя (подписанный вход) с двумя учениками; родитель подключён к первому."""
    r = client.post("/api/v1/classes", headers=as_user(TEACHER, name="Учитель"), json={
        "grade": "6", "letter": "В", "school_name": "Школа безопасности", "teacher_name": "Учитель Т. Т.",
        "students": [
            {"full_name": "Первый Ученик Иванович", "parent_phone": "+79007770001", "parent_name": "Мама Первого"},
            {"full_name": "Второй Ученик Петрович", "parent_phone": "+79007770002", "parent_name": "Папа Второго"},
        ]})
    assert r.status_code == 201, r.text
    klass = r.json()
    assert klass["owner_user_id"] == TEACHER
    by_name = {s["full_name"]: s["id"] for s in klass["students"]}
    first, second = by_name["Первый Ученик Иванович"], by_name["Второй Ученик Петрович"]
    with Session(engine) as s:
        contact = s.exec(select(ParentContact).where(ParentContact.student_id == first)).first()
        contact.max_user_id, contact.confirmed = PARENT, True
        s.add(contact)
        s.commit()
    trip = client.post("/api/v1/excursions", headers=as_user(TEACHER), json={
        "class_id": klass["id"], "title": "Музей", "event_date": str(date.today() + timedelta(days=10)),
        "gathering_time": "09:00", "escorts": "Помощник П. П.", "notify_parents": False})
    assert trip.status_code == 201, trip.text
    return {"class": klass, "trip": trip.json(), "first": first, "second": second}


# --------------------------------------------------------------- личность
def test_SEC_1_query_user_id_is_ignored_in_strict_mode(client, world):
    trip_id = world["trip"]["id"]
    # Подставили id учителя в адрес — без подписи это аноним
    assert client.get(f"/api/v1/excursions/{trip_id}/dashboard", params={"user_id": TEACHER}).status_code == 403
    assert client.get("/api/v1/classes", params={"user_id": TEACHER}).json() == []
    assert client.get("/api/v1/me", params={"user_id": TEACHER}).json()["user_id"] is None


def test_SEC_2_bad_or_stale_signature_rejected(client, world):
    trip_id = world["trip"]["id"]
    forged = {"X-Max-Init-Data": init_data(TEACHER, token="другой-токен")}
    assert client.get(f"/api/v1/excursions/{trip_id}/dashboard", headers=forged).status_code == 401
    stale = as_user(TEACHER, auth_date=int(time.time()) - 3 * 86400)
    assert client.get(f"/api/v1/excursions/{trip_id}/dashboard", headers=stale).status_code == 401
    assert client.get(f"/api/v1/excursions/{trip_id}/dashboard", headers=as_user(TEACHER)).status_code == 200


# --------------------------------------------------------------- персональные данные
def test_SEC_3_teacher_data_only_for_teacher(client, world):
    trip_id, class_id = world["trip"]["id"], world["class"]["id"]
    for path in (f"/api/v1/excursions/{trip_id}/dashboard", f"/api/v1/excursions/{trip_id}/participants",
                 f"/api/v1/classes/{class_id}/roster", f"/api/v1/excursions/{trip_id}/export-order?fmt=pdf"):
        assert client.get(path).status_code == 403, path
        assert client.get(path, headers=as_user(STRANGER)).status_code == 403, path
        assert client.get(path, headers=as_user(PARENT)).status_code == 403, path
    assert client.get("/api/v1/classes", headers=as_user(STRANGER)).json() == []
    assert client.get("/api/v1/excursions", headers=as_user(STRANGER)).json() == []
    assert client.get("/api/v1/parents/search", params={"query": "Мама"}).status_code == 403
    assert client.get("/api/v1/parents/search", params={"query": "Мама"},
                      headers=as_user(STRANGER)).status_code == 403


def test_SEC_4_parent_sees_only_own_children(client, world):
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": PARENT}, headers=as_user(PARENT))
    assert ctx.status_code == 200 and ctx.json()["found"] is True
    assert client.get("/api/v1/parent/context", params={"max_user_id": PARENT},
                      headers=as_user(STRANGER)).status_code == 403
    assert client.get("/api/v1/parent/context", params={"max_user_id": PARENT}).status_code == 403
    # Карточку выезда родитель видит, учительский дашборд — нет
    trip_id = world["trip"]["id"]
    assert client.get(f"/api/v1/excursions/{trip_id}", headers=as_user(PARENT)).status_code == 200
    assert client.get(f"/api/v1/excursions/{trip_id}", headers=as_user(STRANGER)).status_code == 403


def test_SEC_5_signed_download_links(client, world):
    trip_id = world["trip"]["id"]
    assert client.post(f"/api/v1/excursions/{trip_id}/export-order", headers=as_user(STRANGER)).status_code == 403
    links = client.post(f"/api/v1/excursions/{trip_id}/export-order", headers=as_user(TEACHER)).json()
    url = links["pdf_url"].replace("http://testserver", "")
    assert client.get(url).status_code == 200  # MAX скачивает файл без заголовков — по подписанной ссылке
    tampered = url.replace("fmt=pdf", "fmt=docx")
    assert client.get(tampered).status_code == 403
    other_trip = url.replace(f"/excursions/{trip_id}/", f"/excursions/{trip_id + 1}/")
    assert client.get(other_trip).status_code in (403, 404)
    expired = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(expired.query))
    q["exp"] = str(int(time.time()) - 10)
    assert client.get(f"{expired.path}?{urllib.parse.urlencode(q)}").status_code == 403


# --------------------------------------------------------------- подписи и действия
def test_SEC_6_consent_cannot_be_forged(client, world):
    trip_id, first = world["trip"]["id"], world["first"]
    body = {"student_id": first, "status": "APPROVED", "max_user_id": PARENT, "parent_name": "Подделка"}
    assert client.post(f"/api/v1/excursions/{trip_id}/consent", json=body).status_code == 401
    assert client.post(f"/api/v1/excursions/{trip_id}/consent", json=body,
                       headers=as_user(STRANGER)).status_code == 403
    # Учитель не может «проголосовать» за родителя кнопкой — только отметить бумажный бланк
    assert client.post(f"/api/v1/excursions/{trip_id}/consent", json={**body, "source": "miniapp"},
                       headers=as_user(TEACHER)).status_code == 403
    client.post("/api/v1/me/accept-terms", headers=as_user(PARENT))
    ok = client.post(f"/api/v1/excursions/{trip_id}/consent", json=body, headers=as_user(PARENT)).json()
    assert ok["changed"] is True
    assert ok["signed_by_name"] == "Мама Первого"  # имя из списка школы, а не из запроса


def test_SEC_7_foreign_class_actions_forbidden(client, world):
    trip_id, class_id = world["trip"]["id"], world["class"]["id"]
    phishing = {"class_id": class_id, "title": "Билеты", "ticket_price": 3000,
                "ticket_sale_url": "https://evil.example", "notify_parents": False}
    assert client.post("/api/v1/excursions", json=phishing, headers=as_user(STRANGER)).status_code == 403
    assert client.post("/api/v1/excursions", json=phishing).status_code == 403
    for path in ("remind-unconfirmed", "invite-parents", "publish", "tag-unactivated", "cancel", "send-documents"):
        assert client.post(f"/api/v1/excursions/{trip_id}/{path}",
                           headers=as_user(STRANGER)).status_code in (401, 403), path
    assert client.post(f"/api/v1/students/{world['first']}/link-code",
                       headers=as_user(STRANGER)).status_code == 403
    assert client.post(f"/api/v1/classes/{class_id}/invite", headers=as_user(STRANGER)).status_code == 403


def test_SEC_8_legacy_and_service_endpoints_closed(client, world):
    assert client.post("/api/v1/parent/claim", json={"parent_id": 1, "max_user_id": STRANGER}).status_code == 410
    assert client.post("/api/v1/parent/notifications", json={"max_user_id": PARENT, "enabled": False},
                       headers=as_user(STRANGER)).status_code == 403
    assert client.post("/api/v1/parent/confirm-link", json={"student_id": world["first"], "max_user_id": PARENT},
                       headers=as_user(STRANGER)).status_code == 403
    assert client.post("/api/v1/admin/reset-demo").status_code == 404
    update = {"update_type": "message_callback", "callback": {
        "callback_id": "x", "payload": f"consent:{world['trip']['id']}:{world['first']}:REJECTED",
        "user": {"user_id": PARENT}}}
    assert client.post("/webhook/max", json=update).status_code == 404  # бот в режиме polling — вебхука нет


def test_SEC_9_seed_classes_without_owner_are_locked(client, strict):
    classes_open = client.get("/api/v1/classes", headers=as_user(STRANGER)).json()
    assert classes_open == []
    with Session(engine) as s:
        seed_trip = s.exec(select(Excursion)).first()
    assert client.get(f"/api/v1/excursions/{seed_trip.id}/dashboard",
                      headers=as_user(STRANGER)).status_code == 403


# --------------------------------------------------------------- бот
class _Fake:
    enabled = True

    def __init__(self):
        self.answers, self.sent = [], []

    async def answer_callback(self, callback_id, text=None, attachments=None, notification=None):
        self.answers.append({"text": text, "notification": notification})
        return {}

    async def send_message(self, **kw):
        self.sent.append(kw)
        return {"ok": True}

    async def upload_file(self, *a, **kw):
        return "tok"

    async def send_document(self, **kw):
        self.sent.append(kw)
        return {"ok": True}


@pytest.mark.asyncio
async def test_SEC_10_bot_buttons_only_for_linked_parent(client, world):
    trip_id, first = world["trip"]["id"], world["first"]
    fake = _Fake()
    bot = BotService(client=fake)

    def press(payload, uid):
        return {"update_type": "message_callback", "callback": {
            "callback_id": "c", "payload": payload, "user": {"user_id": uid}}, "message": {"recipient": {"chat_id": 1}}}

    BotService._accept_terms(STRANGER)
    await bot.handle_update(press(f"consent:{trip_id}:{first}:APPROVED", STRANGER))
    assert "для родителя" in (fake.answers[-1]["notification"] or "")
    with Session(engine) as s:
        p = s.exec(select(ExcursionParticipant).where(ExcursionParticipant.excursion_id == trip_id,
                                                      ExcursionParticipant.student_id == first)).first()
        assert p.consent_status.value == "PENDING"
    await bot.handle_update(press(f"docs:{trip_id}", STRANGER))
    assert "только учитель" in (fake.answers[-1]["notification"] or "") and not fake.sent


def test_SEC_11_change_answer_only_by_signer_and_not_after_start(client, world, strict):
    trip_id, first = world["trip"]["id"], world["first"]
    second_parent = 8_800_003
    with Session(engine) as s:
        s.add(ParentContact(student_id=first, full_name="Папа Первого", phone_number="+79007770009",
                            max_user_id=second_parent, confirmed=True))
        s.commit()
    for uid in (PARENT, second_parent):
        client.post("/api/v1/me/accept-terms", headers=as_user(uid))
    client.post(f"/api/v1/excursions/{trip_id}/consent", headers=as_user(PARENT),
                json={"student_id": first, "status": "APPROVED"})
    # Второй родитель не может молча стереть ответ первого
    r = client.post(f"/api/v1/excursions/{trip_id}/consent/reset", headers=as_user(second_parent),
                    json={"student_id": first}).json()
    assert r["changed"] is False
    # Учитель не снимает электронную подпись родителя (только свои бумажные отметки)
    r = client.post(f"/api/v1/excursions/{trip_id}/consent/reset", headers=as_user(TEACHER),
                    json={"student_id": first, "as_teacher": True}).json()
    assert r["changed"] is False
    # После начала выезда ответить нельзя
    with Session(engine) as s:
        exc = s.get(Excursion, trip_id)
        exc.event_date = (datetime.utcnow() - timedelta(days=1)).date()
        s.add(exc)
        s.commit()
    r = client.post(f"/api/v1/excursions/{trip_id}/consent", headers=as_user(TEACHER),
                    json={"student_id": world["second"], "status": "APPROVED", "source": "paper",
                          "parent_name": "Бланк"}).json()
    assert r["changed"] is False and "начался" in r["message"]
