"""Требования EXC-*, DASH-* (docs/REQUIREMENTS.md)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import make_excursion


def test_EXC_1_create_from_event(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    assert exc["status"] == "VOTING"
    assert exc["is_pushkin_card"] == paid_event["pushkin_eligible"]
    assert exc["ticket_price"] == paid_event["price"]


def test_EXC_2_participants_created(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert len(dash["participants"]) == len(first_class["students"])


def test_EXC_3_create_unknown_class_404(client: TestClient, paid_event) -> None:
    r = client.post("/api/v1/excursions", json={"class_id": 999999, "culture_event_id": paid_event["id"]})
    assert r.status_code == 404


def test_EXC_4_manual_title(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class, None, title="Ручной выезд")
    assert exc["title"] == "Ручной выезд"


def test_EXC_5_list(client: TestClient) -> None:
    r = client.get("/api/v1/excursions")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_EXC_6_get_one(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    got = client.get(f"/api/v1/excursions/{exc['id']}").json()
    assert got["id"] == exc["id"] and got["title"] == exc["title"]


def test_EXC_7_get_unknown_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999").status_code == 404


def test_EXC_8_time_normalization(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class, None, gathering_time="8:05", return_time="14:00")
    assert exc["gathering_time"] == "08:05"
    assert exc["return_time"] == "14:00"


def test_EXC_9_participants_endpoint(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    body = client.get(f"/api/v1/excursions/{exc['id']}/participants").json()
    assert "excursion" in body and "participants" in body


# --------------------------------------------------------------- DASH
def test_DASH_1_structure(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert {"excursion", "summary", "progress_percent", "participants"} <= set(d)
    assert set(d["summary"]) == {"GREEN", "YELLOW", "GREY", "RED"}


def test_DASH_2_summary_matches_participants(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert sum(d["summary"].values()) == len(d["participants"])


def test_DASH_3_progress_range(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert 0 <= d["progress_percent"] <= 100


def test_DASH_4_traffic_values(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert {p["traffic_light"] for p in d["participants"]} <= {"GREEN", "YELLOW", "GREY", "RED"}


def test_DASH_5_unknown_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999/dashboard").status_code == 404


def test_DASH_6_consent_no_ticket_yellow(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in d["participants"] if p["student_id"] == sid)
    assert row["traffic_light"] == "YELLOW"


def test_DASH_7_consent_plus_ticket_green(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "APPROVED"})
    client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", json={"student_id": sid})
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in d["participants"] if p["student_id"] == sid)
    assert row["traffic_light"] == "GREEN"


def test_DASH_8_reject_red(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    sid = first_class["students"][0]["id"]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": sid, "status": "REJECTED"})
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = next(p for p in d["participants"] if p["student_id"] == sid)
    assert row["traffic_light"] == "RED"


def test_DASH_9_pending_grey(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    d = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    assert all(p["traffic_light"] == "GREY" for p in d["participants"])
