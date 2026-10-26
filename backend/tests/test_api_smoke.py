"""Сквозной тест основного сценария (Definition of Done из раздела 6 Архитектуры).

Импорт списка → создание выезда → согласие родителя → дашборд «Сводка ответов» →
генерация скачиваемого приказа. Плюс проверки идемпотентности и обработки ошибок.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_meta_declares_mock_data(client: TestClient) -> None:
    m = client.get("/api/v1/meta").json()
    assert m["dataset"]["is_mock"] is True
    assert "PRO.Культура" in m["dataset"]["catalog_source"]


def test_catalog_filters(client: TestClient) -> None:
    all_events = client.get("/api/v1/culture-events").json()
    assert len(all_events) >= 15
    pushkin = client.get("/api/v1/culture-events", params={"pushkin": True}).json()
    assert all(e["pushkin_eligible"] for e in pushkin)
    assert all("source" in e for e in all_events)


def test_import_class_from_csv(client: TestClient) -> None:
    csv_bytes = (
        "ФИО,Дата рождения,Телефон родителя\n"
        "Тестов Тест Тестович,01.09.2010,+79990000001\n"
        ",02.09.2010,+79990000002\n"
        "Иванов Иван Иванович,неверная дата,+79990000003\n"
    ).encode("utf-8")
    r = client.post(
        "/api/v1/classes/import",
        files={"file": ("class.csv", io.BytesIO(csv_bytes), "text/csv")},
        params={"grade": "9", "letter": "В", "school_name": "МБОУ Тест"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["students_created"] == 2  # строка без ФИО пропущена
    assert body["parents_created"] == 2
    assert body["skipped_rows"]


def test_main_scenario_end_to_end(client: TestClient) -> None:
    klass = client.get("/api/v1/classes").json()[0]
    events = client.get("/api/v1/culture-events", params={"pushkin": True}).json()
    event = events[0]

    # UC-2/UC-3: создание выезда
    exc = client.post("/api/v1/excursions", json={
        "class_id": klass["id"],
        "culture_event_id": event["id"],
        "gathering_time": "08:30",
        "return_time": "14:00",
        "deadline": (datetime.now() + timedelta(days=2)).isoformat(),
    }).json()
    assert exc["status"] == "VOTING"
    assert exc["is_pushkin_card"] is True

    student_id = klass["students"][0]["id"]

    # UC-4: согласие родителя
    consent = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={
        "student_id": student_id, "status": "APPROVED",
        "parent_name": "Мама", "parent_phone": "+79001234501",
    }).json()
    assert consent["consent_status"] == "APPROVED"
    assert consent["changed"] is True

    # Идемпотентность: повторное действие не перезаписывает статус
    repeat = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={
        "student_id": student_id, "status": "REJECTED",
    }).json()
    assert repeat["changed"] is False
    assert repeat["consent_status"] == "APPROVED"

    # UC-5: билет
    ticket = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={
        "student_id": student_id, "ticket_number": "KZ-0001",
    }).json()
    assert ticket["ticket_status"] == "PAID"

    # UC-6: дашборд «Сводка ответов»
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert dash["summary"]["GREEN"] >= 1
    assert 0 <= dash["progress_percent"] <= 100
    lights = {p["traffic_light"] for p in dash["participants"]}
    assert lights <= {"GREEN", "YELLOW", "GREY", "RED"}

    # UC-7: приказ DOCX и PDF
    gen = client.post(f"/api/v1/excursions/{exc['id']}/export-order").json()
    assert gen["version"] >= 1
    docx = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"})
    pdf = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"})
    assert docx.status_code == 200 and len(docx.content) > 5000
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_consent_validation_errors(client: TestClient) -> None:
    klass = client.get("/api/v1/classes").json()[0]
    exc = client.get("/api/v1/excursions").json()[0]
    # несуществующий ученик
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": 999999, "status": "APPROVED"})
    assert r.status_code == 404
    # неверный статус
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": klass["students"][0]["id"], "status": "MAYBE"})
    assert r.status_code == 422
    # несуществующий выезд
    r = client.post("/api/v1/excursions/999999/consent",
                    json={"student_id": klass["students"][0]["id"], "status": "APPROVED"})
    assert r.status_code == 404


def test_ticket_requires_consent(client: TestClient) -> None:
    klass = client.get("/api/v1/classes").json()[0]
    exc = client.post("/api/v1/excursions", json={"class_id": klass["id"], "title": "Тест без согласия"}).json()
    student_id = klass["students"][1]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": student_id}).json()
    assert r["changed"] is False
    assert "согласие" in r["message"].lower()


def test_link_code_deeplink(client: TestClient) -> None:
    klass = client.get("/api/v1/classes").json()[0]
    r = client.post(f"/api/v1/students/{klass['students'][0]['id']}/link-code").json()
    assert r["code"]
    assert r["deep_link"].startswith("https://max.ru/")
    assert "?start=bind_" in r["deep_link"]


def test_webhook_single_and_list(client: TestClient, webhook_on) -> None:
    single = client.post("/webhook/max", headers=webhook_on, json={
        "update_type": "bot_started", "timestamp": 1, "chat_id": 1,
        "user": {"user_id": 42, "name": "Тест"}, "payload": None,
    })
    assert single.status_code == 200 and single.json()["processed"] == 1
    lst = client.post("/webhook/max", headers=webhook_on, json=[
        {"update_type": "bot_started", "timestamp": 2, "chat_id": 1, "user": {"user_id": 42}, "payload": None},
        {"update_type": "message_callback", "timestamp": 3, "callback": {"callback_id": "cb1", "payload": "cmd:trips", "user": {"user_id": 42}}},
    ])
    assert lst.status_code == 200 and lst.json()["processed"] == 2


def test_repeat_scenario_is_stable(client: TestClient) -> None:
    """Повторный прогон основного сценария не должен ломаться (критерий стабильности)."""
    for _ in range(2):
        klass = client.get("/api/v1/classes").json()[0]
        exc = client.post("/api/v1/excursions", json={"class_id": klass["id"], "title": "Повтор"}).json()
        for s in klass["students"][:3]:
            client.post(f"/api/v1/excursions/{exc['id']}/consent",
                        json={"student_id": s["id"], "status": "APPROVED"})
        r = client.get(f"/api/v1/excursions/{exc['id']}/dashboard")
        assert r.status_code == 200
