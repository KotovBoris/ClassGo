"""Требования DOC-*, LNK-*, PUB-* (docs/REQUIREMENTS.md)."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.bot import BotService

from conftest import make_excursion


def _approved_excursion(client: TestClient, klass: dict, event_id: int, n: int = 3) -> dict:
    exc = make_excursion(client, klass, event_id)
    for s in klass["students"][:n]:
        client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": s["id"], "status": "APPROVED"})
    return exc


# --------------------------------------------------------------- DOC
def test_DOC_1_generate(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    body = client.post(f"/api/v1/excursions/{exc['id']}/export-order").json()
    assert body["version"] >= 1 and body["docx_url"] and body["pdf_url"]


def test_DOC_2_docx(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    r = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert r.content[:2] == b"PK"


def test_DOC_3_pdf(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    r = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_DOC_4_only_approved(client: TestClient, first_class, paid_event) -> None:
    exc = make_excursion(client, first_class, paid_event["id"])
    a = first_class["students"][0]
    b = first_class["students"][1]
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": a["id"], "status": "APPROVED"})
    client.post(f"/api/v1/excursions/{exc['id']}/consent", json={"student_id": b["id"], "status": "REJECTED"})
    from app.documents import _collect  # noqa: PLC0415
    from app.db import engine  # noqa: PLC0415
    from app.models import Excursion  # noqa: PLC0415
    from sqlmodel import Session  # noqa: PLC0415

    with Session(engine) as s:
        pack = _collect(s, s.get(Excursion, exc["id"]))
    names = {r.name for r in pack.going}  # в список группы попадают только отпущенные
    assert a["full_name"] in names
    assert b["full_name"] not in names


def test_DOC_5_version_increments(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    v1 = client.post(f"/api/v1/excursions/{exc['id']}/export-order").json()["version"]
    v2 = client.post(f"/api/v1/excursions/{exc['id']}/export-order").json()["version"]
    assert v2 == v1 + 1


def test_DOC_6_bad_fmt_422(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    r = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "rtf"})
    assert r.status_code == 422


def test_DOC_7_unknown_404(client: TestClient) -> None:
    assert client.get("/api/v1/excursions/999999/export-order").status_code == 404


def test_DOC_8_nonempty(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    docx = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "docx"}).content
    pdf = client.get(f"/api/v1/excursions/{exc['id']}/export-order", params={"fmt": "pdf"}).content
    assert len(docx) > 3000 and len(pdf) > 1000


# --------------------------------------------------------------- LNK
def test_LNK_1_link_code(client: TestClient, first_class) -> None:
    sid = first_class["students"][0]["id"]
    body = client.post(f"/api/v1/students/{sid}/link-code").json()
    assert body["code"]
    assert body["deep_link"].startswith("https://max.ru/") and "?start=bind_" in body["deep_link"]


def test_LNK_2_unknown_student_404(client: TestClient) -> None:
    assert client.post("/api/v1/students/999999/link-code").status_code == 404


def test_LNK_3_bot_bind_by_code(client: TestClient, first_class) -> None:
    sid = first_class["students"][0]["id"]
    code = client.post(f"/api/v1/students/{sid}/link-code").json()["code"]
    svc = BotService(client=_FakeClient())

    assert svc._bind_by_code(code, 555001) == sid
    from app.db import engine  # noqa: PLC0415
    from app.models import ParentContact  # noqa: PLC0415
    from sqlmodel import Session, select  # noqa: PLC0415

    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
    assert parent and parent.max_user_id == 555001


def test_LNK_4_code_single_use(client: TestClient, first_class) -> None:
    sid = first_class["students"][1]["id"]
    code = client.post(f"/api/v1/students/{sid}/link-code").json()["code"]
    svc = BotService(client=_FakeClient())
    assert svc._bind_by_code(code, 1) == sid
    assert svc._bind_by_code(code, 2) is None


def test_LNK_5_unknown_code(client: TestClient) -> None:
    svc = BotService(client=_FakeClient())
    assert svc._bind_by_code("nonexistent-code", 3) is None


# --------------------------------------------------------------- PUB
def test_PUB_1_publish_endpoint(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    r = client.post(f"/api/v1/excursions/{exc['id']}/publish", params={"chat_id": 123})
    assert r.status_code == 200 and r.json()["chat_id"] == 123


def test_PUB_2_publish_text_fields(client: TestClient, first_class, paid_event) -> None:
    exc = _approved_excursion(client, first_class, paid_event["id"])
    fake = _FakeClient()
    svc = BotService(client=fake)

    async def run():
        await svc.publish_to_chat(_excursion_obj(exc), 123)

    asyncio.get_event_loop().run_until_complete(run())
    text = fake.sent[-1]["text"]
    assert exc["title"] in text and exc["location_name"] in text


# --------------------------------------------------------------- helpers
class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.answers: list[dict] = []

    @property
    def enabled(self) -> bool:
        return True

    async def get_me(self):
        return {"name": "fake"}

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"ok": True}

    async def answer_callback(self, callback_id, **kwargs):
        self.answers.append({"callback_id": callback_id, **kwargs})
        return {"ok": True}


def _excursion_obj(exc: dict):
    from app.db import engine  # noqa: PLC0415
    from app.models import Excursion  # noqa: PLC0415
    from sqlmodel import Session  # noqa: PLC0415

    with Session(engine) as s:
        return s.get(Excursion, exc["id"])
