from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.models import ParentContact


def test_CLM_1_search_by_student_name(client: TestClient) -> None:
    rows = client.get("/api/v1/parents/search", params={"query": "Валеева"}).json()
    assert rows and any("Валеева" in r["student_name"] or "Валеева" in r["parent_name"] for r in rows)
    assert {"parent_id", "student_id", "class_title", "claimed"} <= set(rows[0])


def test_CLM_2_search_short_query_422(client: TestClient) -> None:
    assert client.get("/api/v1/parents/search", params={"query": "а"}).status_code == 422


def test_CLM_3_claim_binds_and_confirms(client: TestClient) -> None:
    rows = client.get("/api/v1/parents/search", params={"query": "Зарипов"}).json()
    target = next(r for r in rows if not r["claimed"])
    r = client.post("/api/v1/parent/claim",
                    json={"parent_id": target["parent_id"], "max_user_id": 880001})
    assert r.status_code == 200 and r.json()["ok"] is True
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": 880001}).json()
    assert ctx["found"] and ctx["children"][0]["confirmed"] is True
    with Session(engine) as s:
        parent = s.get(ParentContact, target["parent_id"])
        assert parent.max_user_id == 880001 and parent.confirmed is True


def test_CLM_4_claim_unknown_404(client: TestClient) -> None:
    r = client.post("/api/v1/parent/claim", json={"parent_id": 999999, "max_user_id": 880002})
    assert r.status_code == 404
