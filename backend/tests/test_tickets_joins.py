"""Билеты от родителей (проверка покупки, все билеты класса одним PDF) и заявки «родитель добавил ребёнка»."""
from __future__ import annotations

import io
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import demo, tickets
from app.bot import BotService
from app.db import engine
from app.models import ChildJoinRequest, Excursion, ParentContact, SchoolClass, Student, TicketFile, TicketStatus

from conftest import make_excursion


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "#3366ff").save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes() -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 750, "Ticket")
    c.showPage()
    c.save()
    return buf.getvalue()


class FakeClient:
    enabled = True

    def __init__(self, blob: bytes = b"") -> None:
        self.sent: list[dict] = []
        self.answers: list[dict] = []
        self.blob = blob

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": "mid.1"}}}

    async def answer_callback(self, callback_id, **kwargs):
        self.answers.append({"callback_id": callback_id, **kwargs})
        return {"success": True}

    async def download(self, url: str):
        return self.blob


def _class_with_parent(client: TestClient, owner: int, parent_user: int, phone: str) -> tuple[dict, dict]:
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "5", "letter": "В", "school_name": "Школа № 1", "teacher_name": "Учитель Тест",
        "teacher_phone": "+79990000000",
        "students": [{"full_name": "Петров Илья Олегович", "parent_phone": phone, "parent_name": "Петрова Анна"},
                     {"full_name": "Сидорова Мила Ивановна", "parent_phone": "+79991112233"}],
    }).json()
    invite = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()
    r = client.post("/api/v1/parent/join", params={"user_id": parent_user}, json={"code": invite["code"], "phone": phone})
    assert r.json()["status"] == "linked", r.text
    client.post("/api/v1/me/accept-terms", params={"user_id": parent_user})
    return klass, invite


def _going(client: TestClient, klass: dict, owner: int, parent_user: int, paid_event: dict) -> tuple[dict, int]:
    exc = make_excursion(client, {"id": klass["id"], "owner_user_id": owner}, paid_event["id"])
    sid = next(s["id"] for s in klass["students"] if s["full_name"].startswith("Петров"))
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", params={"user_id": parent_user},
                    json={"student_id": sid, "status": "APPROVED", "source": "miniapp"})
    assert r.status_code == 200, r.text
    return exc, sid


def test_TK_1_parent_uploads_ticket_teacher_sees_it(client: TestClient, paid_event) -> None:
    owner, parent = 8_100_001, 8_100_002
    klass, _ = _class_with_parent(client, owner, parent, "+79001110001")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    r = client.post(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": parent},
                    data={"student_id": str(sid)}, files={"file": ("ticket.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text
    assert r.json()["is_image"] is True
    with Session(engine) as s:
        from app import services
        assert services.get_participant(s, exc["id"], sid).ticket_status == TicketStatus.PAID

    listing = client.get(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": owner}).json()
    assert listing["going"] == 1 and listing["with_ticket"] == 1 and not listing["missing"]
    url = listing["items"][0]["url"].replace("http://testserver", "")
    assert client.get(url).status_code == 200                       # по подписанной ссылке
    plain = url.split("?")[0]
    assert client.get(plain).status_code == 403                     # без подписи и без пользователя — нет
    assert client.get(plain, params={"user_id": owner}).status_code == 200
    # Посторонний не видит билеты класса
    assert client.get(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": 8_100_099}).status_code == 403
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard", params={"user_id": owner}).json()
    row = next(p for p in dash["participants"] if p["student_id"] == sid)
    assert row["ticket_file_id"] and row["ticket_uploaded_at"]


def test_TK_2_ticket_validation_and_access(client: TestClient, paid_event) -> None:
    owner, parent = 8_100_011, 8_100_012
    klass, _ = _class_with_parent(client, owner, parent, "+79001110011")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    bad = client.post(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": parent},
                      data={"student_id": str(sid)}, files={"file": ("t.txt", b"hello", "text/plain")})
    assert bad.status_code == 422 and "PDF" in bad.json()["detail"]
    other = next(s["id"] for s in klass["students"] if s["full_name"].startswith("Сидорова"))
    stranger = client.post(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": parent},
                           data={"student_id": str(other)}, files={"file": ("t.png", png_bytes(), "image/png")})
    assert stranger.status_code == 403
    # Учитель может приложить бумажный билет за семью, но только тому, кто идёт
    pending = client.post(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": owner},
                          data={"student_id": str(other)}, files={"file": ("t.png", png_bytes(), "image/png")})
    assert pending.status_code == 422 and "«Да»" in pending.json()["detail"]


def test_TK_3_replace_delete_and_pack_pdf(client: TestClient, paid_event) -> None:
    from pypdf import PdfReader

    owner, parent = 8_100_021, 8_100_022
    klass, _ = _class_with_parent(client, owner, parent, "+79001110021")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    for blob, name in ((png_bytes(), "a.png"), (pdf_bytes(), "b.pdf")):
        r = client.post(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": parent},
                        data={"student_id": str(sid)}, files={"file": (name, blob, "application/octet-stream")})
        assert r.status_code == 201
    with Session(engine) as s:
        rows = tickets.tickets_for(s, exc["id"], sid)
        assert len(rows) == 1 and rows[0].content_type == "application/pdf"   # новый заменил прежний
    link = client.post(f"/api/v1/excursions/{exc['id']}/tickets-pdf", params={"user_id": owner}).json()["url"]
    assert client.post(f"/api/v1/excursions/{exc['id']}/tickets-pdf", params={"user_id": parent}).status_code == 403
    pdf = client.get(link.replace("http://testserver", ""))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(pdf.content)).pages) >= 3                # обложка + подпись + билет
    file_id = client.get(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": parent}).json()["items"][0]["id"]
    assert client.delete(f"/api/v1/tickets/{file_id}", params={"user_id": 8_100_099}).status_code == 403
    assert client.delete(f"/api/v1/tickets/{file_id}", params={"user_id": parent}).json()["ok"] is True
    with Session(engine) as s:
        from app import services
        assert services.get_participant(s, exc["id"], sid).ticket_status == TicketStatus.WAITING_PAYMENT


@pytest.mark.asyncio
async def test_TK_4_ticket_through_bot_chat(client: TestClient, paid_event) -> None:
    owner, parent = 8_100_031, 8_100_032
    klass, _ = _class_with_parent(client, owner, parent, "+79001110031")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    fake = FakeClient(blob=png_bytes())
    bot = BotService(client=fake)
    # Чужой не может нажать «Прислать билет» за родителя
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-x", "payload": f"tup:{exc['id']}:{sid}", "user": {"user_id": parent + 50}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "для родителя" in fake.answers[-1]["notification"]
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-1", "payload": f"tup:{exc['id']}:{sid}", "user": {"user_id": parent}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "Пришлите билет" in fake.answers[-1]["text"]
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": 1},
        "body": {"text": "", "attachments": [{"type": "image", "payload": {"url": "https://fu.example/img.jpg"}}]}}})
    assert any("получен" in m.get("text", "") for m in fake.sent)
    with Session(engine) as s:
        rows = tickets.tickets_for(s, exc["id"], sid)
        assert len(rows) == 1 and rows[0].source == "bot"
    # Одно сообщение: «Билет получен» с кнопкой заменить файл, полная карточка выезда не повторяется
    received = [m for m in fake.sent if "получен" in m.get("text", "")]
    card = fake.sent[-1]
    assert len(received) == 1 and card is received[0]
    assert "Билет получен" in card["text"] and "Отправить другой файл" in str(card["attachments"])
    assert "Где:" not in card["text"]

    # Фото без кнопки: бот не сохраняет молча, а спрашивает, к какому выезду оно относится
    fake.sent.clear()
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": 1},
        "body": {"text": "", "attachments": [{"type": "image", "payload": {"url": "https://fu.example/2.jpg"}}]}}})
    assert "Это билет?" in fake.sent[-1]["text"] and f"tsv:{exc['id']}:{sid}" in str(fake.sent[-1]["attachments"])
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-2", "payload": "tsx:0:0", "user": {"user_id": parent}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "не сохранили" in fake.answers[-1]["text"]
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": 1},
        "body": {"text": "", "attachments": [{"type": "file", "filename": "b.png",
                                              "payload": {"url": "https://fu.example/3.png"}}]}}})
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-3", "payload": f"tsv:{exc['id']}:{sid}", "user": {"user_id": parent}},
        "message": {"recipient": {"chat_id": 1}}})
    assert any("✅ Билет получен" in m.get("text", "") for m in fake.sent)


def test_TK_5_demo_virtual_parents_send_tickets(client: TestClient, paid_event) -> None:
    owner = 8_100_041
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, paid_event["id"])
    with Session(engine) as s:
        demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=10))
        rows = tickets.tickets_for(s, exc["id"])
        assert rows and all(r.source == "demo" for r in rows)
        assert tickets.read_ticket(rows[0]).startswith(b"\xff\xd8")   # картинки хранятся в JPEG


@pytest.mark.asyncio
async def test_JR_1_parent_adds_child_teacher_approves(client: TestClient, paid_event) -> None:
    owner, parent = 8_200_001, 8_200_002
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "6", "letter": "А", "school_name": "Школа № 2", "teacher_name": "Учитель Два",
        "teacher_phone": "+79990000001", "students": []}).json()
    exc = make_excursion(client, {"id": klass["id"], "owner_user_id": owner}, paid_event["id"])
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    not_found = client.post("/api/v1/parent/join", params={"user_id": parent},
                            json={"code": code, "phone": "+79005550001"}).json()
    assert not_found["status"] == "not_found"
    bad = client.post("/api/v1/parent/join-request", params={"user_id": parent},
                      json={"code": code, "child_name": "Петя", "phone": "+79005550001"})
    assert bad.status_code == 422
    r = client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "кузнецов  пётр сергеевич", "role": "Папа", "parent_name": "Кузнецов Сергей",
        "phone": "+79005550001", "birth_date": "2013-03-01"}).json()
    assert r["status"] == "requested" and r["children"] == ["Кузнецов Пётр Сергеевич"]
    again = client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "Кузнецов Петр Сергеевич", "phone": "+79005550001"}).json()
    assert again["status"] == "requested"
    reqs = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()
    assert len(reqs) == 1 and reqs[0]["parent_role"] == "Папа"
    assert client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": parent}).status_code == 403
    mine = client.get("/api/v1/parent/join-requests", params={"user_id": parent}).json()
    assert mine and mine[0]["class_title"] == klass["title"]
    assert client.get("/api/v1/classes", params={"user_id": owner, "mine": True}).json()[0]["join_requests"] == 1
    # Решает только учитель класса
    assert client.post(f"/api/v1/join-requests/{reqs[0]['id']}/decide", params={"user_id": parent},
                       json={"approve": True}).status_code == 403
    done = client.post(f"/api/v1/join-requests/{reqs[0]['id']}/decide", params={"user_id": owner},
                       json={"approve": True}).json()
    assert done["status"] == "APPROVED"
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": parent, "user_id": parent}).json()
    child = ctx["children"][0]
    assert child["student_name"] == "Кузнецов Пётр Сергеевич" and child["confirmed"] is True
    assert [e["excursion_id"] for e in child["excursions"]] == [exc["id"]]   # сразу в открытом выезде


@pytest.mark.asyncio
async def test_JR_2_bot_buttons_and_reject(client: TestClient) -> None:
    owner, parent = 8_200_011, 8_200_012
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "7", "letter": "Г", "teacher_name": "Учитель Три", "students": [
            {"full_name": "Орлова Вера Павловна", "parent_phone": "+79007770000"}]}).json()
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "Орлова Вера Павловна", "phone": "+79007771111"})
    with Session(engine) as s:
        req = s.exec(select(ChildJoinRequest).where(ChildJoinRequest.max_user_id == parent)).first()
    fake = FakeClient()
    bot = BotService(client=fake)
    await bot.notify_join_request(req.id)
    # Ученица уже в списке и у неё есть родитель: предупреждение и отдельная кнопка «второй родитель»
    assert "Орлова Вера" in fake.sent[-1]["text"] and "уже в списке" in fake.sent[-1]["text"]
    assert f"jr:{req.id}:L" in str(fake.sent[-1]["attachments"])
    assert f"jr:{req.id}:A" not in str(fake.sent[-1]["attachments"])
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-j1", "payload": f"jr:{req.id}:L", "user": {"user_id": parent}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "учитель класса" in fake.answers[-1]["notification"]
    # Обычное «Подтвердить» (например, из старого сообщения) молча не привязывает
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-j2", "payload": f"jr:{req.id}:A", "user": {"user_id": owner}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "уже в списке" in fake.answers[-1]["text"] and f"jr:{req.id}:L" in str(fake.answers[-1]["attachments"])
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-j3", "payload": f"jr:{req.id}:L", "user": {"user_id": owner}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "второй родитель подключён" in fake.answers[-1]["text"]
    with Session(engine) as s:
        students = s.exec(select(Student).where(Student.class_id == klass["id"])).all()
        assert len(students) == 1                                   # совпало ФИО — второго ученика нет
        contacts = s.exec(select(ParentContact).where(ParentContact.student_id == students[0].id)).all()
        assert any(c.max_user_id == parent and c.confirmed for c in contacts)
    # Повторная заявка на другого ребёнка — учитель отклоняет
    client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "Орлов Иван", "phone": "+79007771111"})
    with Session(engine) as s:
        req2 = s.exec(select(ChildJoinRequest).where(ChildJoinRequest.max_user_id == parent,
                                                     ChildJoinRequest.status == "PENDING")).first()
    r = client.post(f"/api/v1/join-requests/{req2.id}/decide", params={"user_id": owner}, json={"approve": False}).json()
    assert r["status"] == "REJECTED"


def test_JR_3_parent_edits_child(client: TestClient) -> None:
    owner, parent = 8_200_021, 8_200_022
    klass, _ = _class_with_parent(client, owner, parent, "+79001110041")
    sid = next(s["id"] for s in klass["students"] if s["full_name"].startswith("Петров"))
    assert client.patch(f"/api/v1/parent/children/{sid}", params={"user_id": parent + 1},
                        json={"birth_date": "2012-05-05"}).status_code == 403
    r = client.patch(f"/api/v1/parent/children/{sid}", params={"user_id": parent},
                     json={"full_name": "Петров Илья Олегович", "birth_date": "2012-05-05"}).json()
    assert r["changed"] == ["дата рождения: 05.05.2012"]
    bad = client.patch(f"/api/v1/parent/children/{sid}", params={"user_id": parent}, json={"full_name": "И"})
    assert bad.status_code == 422


def test_TK_6_sniff_types() -> None:
    assert tickets.sniff_type(png_bytes()) == "image/png"
    assert tickets.sniff_type(pdf_bytes()) == "application/pdf"
    assert tickets.sniff_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert tickets.sniff_type(b"GIF89a") is None
