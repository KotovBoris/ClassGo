"""Требования CNS-*, TCK-*, RMN-* (docs/REQUIREMENTS.md)."""
from __future__ import annotations

from sqlmodel import Session, select

from fastapi.testclient import TestClient

from app.db import engine
from app.models import ConsentAudit

from conftest import make_excursion


def test_CNS_1_approve(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": sid, "status": "APPROVED", "parent_name": "Мама"}).json()
    assert r["consent_status"] == "APPROVED" and r["changed"] is True
    assert r["signed_at"]


def test_CNS_2_idempotent_approve(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"}).json()
    assert r["changed"] is False and r["consent_status"] == "APPROVED"
    assert "уже подписано" in r["message"]


def test_CNS_3_two_parents_rule(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][1]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "REJECTED"}).json()
    assert r["changed"] is False and r["consent_status"] == "APPROVED"


def test_CNS_4_reject_reason(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][2]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": sid, "status": "REJECTED", "reason": "Болезнь"}).json()
    assert r["consent_status"] == "REJECTED"
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in d["participants"] if p["student_id"] == sid)
    assert row["rejection_reason"] == "Болезнь"


def test_CNS_5_student_not_in_excursion_404(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": 999999, "status": "APPROVED"})
    assert r.status_code == 404


def test_CNS_6_invalid_status_422(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "MAYBE"})
    assert r.status_code == 422


def test_CNS_7_unknown_excursion_404(client: TestClient, first_class) -> None:
    sid = first_class["students"][0]["id"]
    r = client.post("/api/v1/excursions/999999/consent", json={"student_id": sid, "status": "APPROVED"})
    assert r.status_code == 404


def test_CNS_8_free_event_not_required(client: TestClient, first_class, free_event) -> None:
    exc = make_excursion(client, first_class, free_event["id"])
    assert exc["ticket_price"] == 0
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"}).json()
    assert r["ticket_status"] == "NOT_REQUIRED"


def test_CNS_9_paid_event_waiting_payment(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"}).json()
    assert r["ticket_status"] == "WAITING_PAYMENT"


def test_CNS_10_audit_written(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent",
                json={"student_id": sid, "status": "APPROVED", "source": "miniapp"})
    with Session(engine) as s:
        rows = s.exec(select(ConsentAudit).where(ConsentAudit.excursion_id == exc["id"],
                                                 ConsentAudit.student_id == sid)).all()
    assert rows and any(r.action == "APPROVE" for r in rows)


def test_CNS_11_audit_source_saved(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][3]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent",
                json={"student_id": sid, "status": "APPROVED", "source": "bot"})
    with Session(engine) as s:
        row = s.exec(select(ConsentAudit).where(ConsentAudit.excursion_id == exc["id"],
                                                ConsentAudit.student_id == sid)).first()
    assert row and row.source == "bot"


# --------------------------------------------------------------- TCK
def test_TCK_1_confirm(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm",
                    json={"student_id": sid, "ticket_number": "KZ-1"}).json()
    assert r["ticket_status"] == "PAID"


def test_TCK_2_ticket_without_consent(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": sid}).json()
    assert r["changed"] is False and r["ticket_status"] != "PAID"


def test_TCK_3_repeat_confirm(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": sid})
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": sid}).json()
    assert r["changed"] is False


def test_TCK_4_unknown_student_404(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": 999999})
    assert r.status_code == 404


# --------------------------------------------------------------- RMN
def test_RMN_1_remind_endpoint(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    body = client.post(f"/api/v1/excursions/{exc['id']}/remind-unconfirmed").json()
    assert {"targeted", "delivered", "recipients"} <= set(body)


def test_RMN_2_only_grey_yellow(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    gp = first_class["students"][0]["id"]
    rp = first_class["students"][1]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": gp, "status": "APPROVED"})
    client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": gp})  # GREEN
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": rp, "status": "REJECTED"})  # RED
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    green = next(p["full_name"] for p in d["participants"] if p["student_id"] == gp)
    red = next(p["full_name"] for p in d["participants"] if p["student_id"] == rp)
    body = client.post(f"/api/v1/excursions/{exc['id']}/remind-unconfirmed").json()
    assert green not in body["recipients"]
    assert red not in body["recipients"]


def test_RMN_3_no_token_no_crash(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    assert client.post(f"/api/v1/excursions/{exc['id']}/remind-unconfirmed").status_code == 200
