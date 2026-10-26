"""Требования CLS-* (docs/REQUIREMENTS.md)."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import Workbook


def _csv(rows: list[str]) -> bytes:
    return ("\n".join(rows) + "\n").encode("utf-8")


def test_CLS_1_demo_class(client: TestClient, first_class: dict) -> None:
    assert first_class["title"] == "8Б"
    assert len(first_class["students"]) >= 5


def test_CLS_2_roster(client: TestClient, first_class: dict) -> None:
    roster = client.get(f"/api/v1/classes/{first_class['id']}/roster").json()
    assert roster["id"] == first_class["id"]
    assert any(s["parent_phones"] for s in roster["students"])


def test_CLS_3_roster_404(client: TestClient) -> None:
    assert client.get("/api/v1/classes/999999/roster").status_code == 404


def test_CLS_4_import_csv(client: TestClient) -> None:
    data = _csv([
        "ФИО,Дата рождения,Телефон родителя",
        "Первый Ученик Тестович,01.09.2010,+79990000001",
        "Второй Ученик Тестович,02.09.2010,+79990000002",
    ])
    r = client.post(
        "/api/v1/classes/import",
        files={"file": ("c.csv", io.BytesIO(data), "text/csv")},
        params={"grade": "9", "letter": "А"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["students_created"] == 2 and body["parents_created"] == 2


def test_CLS_5_import_skips_bad_row(client: TestClient) -> None:
    data = _csv([
        "ФИО,Дата рождения,Телефон родителя",
        "Валидный Ученик,01.09.2010,+79990000001",
        ",02.09.2010,+79990000002",
    ])
    r = client.post("/api/v1/classes/import", files={"file": ("c.csv", io.BytesIO(data), "text/csv")})
    assert r.status_code == 200
    body = r.json()
    assert body["students_created"] == 1 and body["skipped_rows"]


def test_CLS_6_import_date_formats(client: TestClient) -> None:
    data = _csv([
        "ФИО,Дата рождения,Телефон родителя",
        "ДмГ Русский,01.09.2010,+79990000011",
        "ИСО Формат,2010-09-02,+79990000012",
    ])
    r = client.post("/api/v1/classes/import", files={"file": ("c.csv", io.BytesIO(data), "text/csv")})
    assert r.status_code == 200
    cid = r.json()["class_id"]
    roster = client.get(f"/api/v1/classes/{cid}/roster").json()
    dates = {s["full_name"]: s["birth_date"] for s in roster["students"]}
    assert dates["ДмГ Русский"] == "2010-09-01"
    assert dates["ИСО Формат"] == "2010-09-02"


def test_CLS_7_import_xlsx(client: TestClient) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["ФИО", "Дата рождения", "Телефон родителя"])
    ws.append(["Эксель Ученик", "03.09.2010", "+79990000021"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    r = client.post(
        "/api/v1/classes/import",
        files={"file": ("c.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200 and r.json()["students_created"] == 1


def test_CLS_8_import_empty_file(client: TestClient) -> None:
    r = client.post("/api/v1/classes/import", files={"file": ("e.csv", io.BytesIO(b""), "text/csv")})
    assert r.status_code == 400 and "detail" in r.json()


def test_CLS_9_import_header_only(client: TestClient) -> None:
    r = client.post(
        "/api/v1/classes/import",
        files={"file": ("h.csv", io.BytesIO(_csv(["ФИО,Дата рождения,Телефон родителя"])), "text/csv")},
    )
    assert r.status_code == 400


def test_CLS_10_import_bad_date_no_crash(client: TestClient) -> None:
    data = _csv([
        "ФИО,Дата рождения,Телефон родителя",
        "Кривая Дата Ученик,недата,+79990000031",
    ])
    r = client.post("/api/v1/classes/import", files={"file": ("c.csv", io.BytesIO(data), "text/csv")})
    assert r.status_code == 200
    cid = r.json()["class_id"]
    roster = client.get(f"/api/v1/classes/{cid}/roster").json()
    assert roster["students"][0]["birth_date"] is None
