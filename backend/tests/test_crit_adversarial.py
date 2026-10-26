"""Критичные (adversarial) проверки: краевые данные, параллелизм, пустые множества.

Каждый тест сформулирован как «а что если сломается» — ищет реальные дефекты.
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.bot import BotService
from app.db import engine
from app.models import Excursion, ParentContact, SchoolClass, Student, TicketStatus

from conftest import make_excursion


# --- CRIT-1: ученик из ДРУГОГО класса не может участвовать -------------------
def test_CRIT_1_foreign_student_rejected(client: TestClient, first_class) -> None:
    csv = "ФИО,Дата рождения,Телефон родителя\nЧужой Ученик,01.01.2010,+79990009999\n"
    other = client.post("/api/v1/classes/import",
                        files={"file": ("c.csv", io.BytesIO(csv.encode()), "text/csv")}).json()
    foreign_sid = client.get(f"/api/v1/classes/{other['class_id']}/roster").json()["students"][0]["id"]
    exc = make_excursion(client, first_class)
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": foreign_sid, "status": "APPROVED"})
    assert r.status_code == 404, "ученик другого класса не должен приниматься"


# --- CRIT-2: отрицательный/нулевой student_id --------------------------------
@pytest.mark.parametrize("sid", [0, -1, 10**12])
def test_CRIT_2_bad_student_ids(client: TestClient, first_class, sid: int) -> None:
    exc = make_excursion(client, first_class)
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    assert r.status_code == 404


# --- CRIT-3: нецелый id в пути ----------------------------------------------
def test_CRIT_3_non_int_path_id(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/abc/dashboard").status_code == 422


# --- CRIT-4: приказ при НУЛЕ подтверждённых (пустой список) ------------------
def test_CRIT_4_order_with_zero_approved(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)  # никто не подтверждён
    r = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"})
    assert r.status_code == 200 and r.content[:2] == b"PK", "приказ с нулевым списком должен формироваться"
    rp = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"})
    assert rp.status_code == 200 and rp.content[:4] == b"%PDF"


# --- CRIT-5: параллельные согласия не ломают сервис --------------------------
def test_CRIT_5_parallel_consent_no_5xx(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]

    def post(_):
        return client.post(f"/api/v1/excursions/{exc['id']}/consent",
                           json={"student_id": sid, "status": "APPROVED"}).status_code

    with ThreadPoolExecutor(max_workers=6) as ex:
        codes = list(ex.map(post, range(6)))
    assert all(c < 500 for c in codes), f"параллельные согласия дали 5xx: {codes}"
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in dash["participants"] if p["student_id"] == sid)
    assert row["consent_status"] == "APPROVED"


# --- CRIT-6: подстановка HTML/скриптов в поля --------------------------------
def test_CRIT_6_injection_in_title(client: TestClient, first_class) -> None:
    payload = "<script>alert(1)</script> & \"'\u2028\u2029 weird"
    exc = make_excursion(client, first_class, None, title=payload)
    assert exc["title"] == payload  # хранится как есть (JSON-boundary безопасен)
    r = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"})
    assert r.status_code == 200, "генерация документа не должна падать на спецсимволах"
    rp = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"})
    assert rp.status_code == 200


# --- CRIT-7: дедлайн с таймзоной 'Z' принимается -----------------------------
def test_CRIT_7_deadline_z_suffix(client: TestClient, first_class) -> None:
    r = client.post("/api/v1/excursions", json={
        "class_id": first_class["id"], "title": "Дедлайн Z",
        "deadline": "2026-10-01T12:00:00Z",
    })
    assert r.status_code == 201, r.text


# --- CRIT-8: напоминания не врут про «доставлено» ---------------------------
def test_CRIT_8_remind_delivered_truthful(client: TestClient, first_class) -> None:
    """Если родитель не привязан к боту — delivered должен быть 0."""
    exc = make_excursion(client, first_class)  # все GREY, никто не привязан
    body = client.post(f"/api/v1/excursions/{exc['id']}/remind-unconfirmed").json()
    assert body["targeted"] >= 1
    assert body["delivered"] == 0, "без привязки родителя ничего не доставлено"
    assert body["recipients"] == []


# --- CRIT-9: напоминание реально уходит привязанным родителям ---------------
@pytest.mark.asyncio
async def test_CRIT_9_remind_delivers_to_linked() -> None:
    class Fake:
        enabled = True
        def __init__(self): self.sent = []
        async def send_message(self, **k):
            self.sent.append(k); return {"ok": True}
        async def answer_callback(self, *a, **k): return {"ok": True}

    with Session(engine) as s:
        klass = s.exec(select(SchoolClass)).first()
        students = s.exec(select(Student).where(Student.class_id == klass.id)).all()[:2]
        exc = Excursion(class_id=klass.id, title="Remind", ticket_price=500)
        s.add(exc); s.commit(); s.refresh(exc)
        from app.models import ExcursionParticipant  # noqa: PLC0415
        for i, st in enumerate(students):
            s.add(ExcursionParticipant(excursion_id=exc.id, student_id=st.id, consent_status="PENDING"))
            for j, p in enumerate(
                s.exec(select(ParentContact).where(ParentContact.student_id == st.id)).all()
            ):
                p.max_user_id = 700700 if i == 0 and j == 0 else None
                s.add(p)
        s.commit()
        fake = Fake()
        noon = datetime.utcnow().replace(hour=9, minute=0)  # полдень по Москве, не тихие часы
        targeted, delivered, _skipped = await BotService(client=fake).remind(exc, s, now=noon)
    assert targeted == 2 and len(delivered) == 1 and len(fake.sent) == 1


# --- CRIT-10: webhook считает только валидные Update ------------------------
def test_CRIT_10_webhook_counts_valid_only(client: TestClient, webhook_on) -> None:
    body = [
        {"update_type": "bot_started", "timestamp": 1, "chat_id": 1, "user": {"user_id": 1}, "payload": None},
        {"foo": "bar"},                                   # не Update
        {"update_type": ""},                              # пустой тип
    ]
    r = client.post("/webhook/max", json=body, headers=webhook_on)
    assert r.status_code == 200
    assert r.json()["processed"] == 1, "невалидные элементы не должны считаться обработанными"


# --- CRIT-11: пустой список в webhook ----------------------------------------
def test_CRIT_11_webhook_empty_list(client: TestClient, webhook_on) -> None:
    r = client.post("/webhook/max", json=[], headers=webhook_on)
    assert r.status_code == 200 and r.json()["processed"] == 0


# --- CRIT-12: бесплатное событие — билет не требуется, статус зелёный -------
def test_CRIT_12_free_event_green(client: TestClient, first_class, free_event) -> None:
    exc = make_excursion(client, first_class, free_event["id"])
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": sid, "status": "APPROVED"}).json()
    assert r["ticket_status"] == "NOT_REQUIRED"
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in dash["participants"] if p["student_id"] == sid)
    assert row["traffic_light"] == "GREEN"


# --- CRIT-13: отклонение после подтверждения не откатывает статус -----------
def test_CRIT_13_reject_after_approve_kept(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": sid, "status": "REJECTED", "reason": "передумали"}).json()
    assert r["consent_status"] == "APPROVED"
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in dash["participants"] if p["student_id"] == sid)
    assert row["consent_status"] == "APPROVED" and row["traffic_light"] != "RED"


# --- CRIT-14: крупный импорт не тормозит/не падает --------------------------
def test_CRIT_14_large_import(client: TestClient) -> None:
    rows = ["ФИО,Дата рождения,Телефон родителя"]
    rows += [f"Ученик Номер{i},01.01.201{i % 10},+7999{i:07d}" for i in range(1000)]
    import time  # noqa: PLC0415

    t0 = time.time()
    r = client.post("/api/v1/classes/import",
                    files={"file": ("big.csv", io.BytesIO(("\n".join(rows)).encode()), "text/csv")})
    dt = time.time() - t0
    assert r.status_code == 200 and r.json()["students_created"] == 1000
    assert dt < 30, f"импорт 1000 строк слишком долгий: {dt:.1f}с"


# --- CRIT-15: фильтр по несуществующему возрасту — не ошибка -----------------
def test_CRIT_15_bad_age_filter(client: TestClient) -> None:
    r = client.get("/api/v1/culture-events", params={"age": "999+"})
    assert r.status_code == 200 and r.json() == []


# --- CRIT-16: повторная генерация приказа не ломается ------------------------
def test_CRIT_16_repeated_export(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    for _ in range(3):
        assert client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"}).status_code == 200
        assert client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"}).status_code == 200
