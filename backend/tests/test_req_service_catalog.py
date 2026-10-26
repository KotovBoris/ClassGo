"""Требования SVC-*, CAT-* (docs/REQUIREMENTS.md)."""
from __future__ import annotations

import io
from datetime import date, timedelta

from fastapi.testclient import TestClient

from sqlmodel import select

from app import services
from app.models import Student


def _events(client: TestClient, **params) -> list[dict]:
    r = client.get("/api/v1/culture-events", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _sorted(seq: list, key) -> bool:
    values = [key(x) for x in seq]
    return values == sorted(values)


# --------------------------------------------------------------- SVC
def test_SVC_1_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    for field in ("version", "bot_mode", "bot_enabled", "time"):
        assert field in body


def test_SVC_2_meta(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["dataset"]["is_mock"] is True
    assert "PRO.Культура" in body["dataset"]["catalog_source"]
    assert "roles" in body and "max" in body


def test_SVC_3_openapi(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert {"openapi", "paths", "info"} <= set(spec)
    assert len(spec["paths"]) >= 15


def test_SVC_4_docs(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200


def test_SVC_5_unknown_path_404(client: TestClient) -> None:
    assert client.get("/api/v1/nope").status_code == 404


# --------------------------------------------------------------- CAT
def test_CAT_1_all_events(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events").json()
    assert len(events) >= 15
    for e in events:
        for f in ("id", "title", "venue", "city", "age_rating", "price", "pushkin_eligible", "is_free", "source"):
            assert f in e


def test_CAT_2_pushkin_true(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"pushkin": True}).json()
    assert events and all(e["pushkin_eligible"] for e in events)


def test_CAT_3_pushkin_false(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"pushkin": False}).json()
    assert all(not e["pushkin_eligible"] for e in events)


def test_CAT_4_free_true(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"free": True}).json()
    assert events and all(e["is_free"] for e in events)


def test_CAT_5_city(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"city": "Казань"}).json()
    assert events and all(e["city"] == "Казань" for e in events)


def test_CAT_6_age(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"age": "12+"}).json()
    assert all(e["age_rating"] == "12+" for e in events)


def test_CAT_7_combined_filters(client: TestClient) -> None:
    events = client.get(
        "/api/v1/culture-events", params={"city": "Казань", "pushkin": True, "free": True}
    ).json()
    for e in events:
        assert e["city"] == "Казань" and e["pushkin_eligible"] and e["is_free"]


def test_CAT_8_no_match_empty(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events", params={"city": "НетТакогоГорода"}).json()
    assert events == []


def test_CAT_9_source_present(client: TestClient) -> None:
    events = client.get("/api/v1/culture-events").json()
    assert all(isinstance(e["source"], str) and e["source"] for e in events)


# --------------------------------------------------------- ST-4: сортировка


def test_CAT_21_age_fit_without_class_is_noop(client: TestClient) -> None:
    assert len(_events(client, age_fit=True)) == len(_events(client))


# ------------------------------------------------- unit: логика возраста


