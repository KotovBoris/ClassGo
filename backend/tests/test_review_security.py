"""Ревью кода и безопасности: билеты, заявки «добавьте ребёнка», демо, бот в группах, скачивание файлов.

F-тесты — сценарии из отчёта ревью (на коде до правок каждый падал), остальные проверяют поведение
после правок: нормализацию файлов, второго родителя, лимиты заявок, очистку данных.
"""
from __future__ import annotations

import io
import itertools
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import demo, joins, services, tickets
from app.bot import BotService
from app.db import engine
from app.main import app
from app.models import (
    ChildJoinRequest,
    ConsentAudit,
    DemoAnswer,
    Excursion,
    ParentContact,
    Student,
    TicketFile,
    TicketStatus,
)

from conftest import make_excursion

_SEQ = itertools.count()


def png_bytes(size=(60, 40), mode="RGB", color="#3366ff") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes(pages: int = 1) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(50, 750, f"Ticket {i + 1}")
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


def _class_with_parent(client, owner, parent_user, phone, second_phone="+79991112233"):
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "5", "letter": "В", "school_name": "Школа № 1", "teacher_name": "Учитель Тест",
        "teacher_phone": "+79990000000",
        "students": [{"full_name": "Петров Илья Олегович", "parent_phone": phone, "parent_name": "Петрова Анна"},
                     {"full_name": "Сидорова Мила Ивановна", "parent_phone": second_phone}],
    }).json()
    invite = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()
    r = client.post("/api/v1/parent/join", params={"user_id": parent_user}, json={"code": invite["code"], "phone": phone})
    assert r.json()["status"] == "linked", r.text
    client.post("/api/v1/me/accept-terms", params={"user_id": parent_user})
    return klass, invite


def _going(client, klass, owner, parent_user, paid_event, prefix="Петров"):
    exc = make_excursion(client, {"id": klass["id"], "owner_user_id": owner}, paid_event["id"])
    sid = next(s["id"] for s in klass["students"] if s["full_name"].startswith(prefix))
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", params={"user_id": parent_user},
                    json={"student_id": sid, "status": "APPROVED", "source": "miniapp"})
    assert r.status_code == 200, r.text
    return exc, sid


def _upload(client, exc_id, sid, user, blob, name="t.bin"):
    return client.post(f"/api/v1/excursions/{exc_id}/tickets", params={"user_id": user},
                       data={"student_id": str(sid)}, files={"file": (name, blob, "application/octet-stream")})


def _pack(client, exc_id, owner):
    link = client.post(f"/api/v1/excursions/{exc_id}/tickets-pdf", params={"user_id": owner}).json()["url"]
    return TestClient(app, raise_server_exceptions=False).get(link.replace("http://testserver", ""))


def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)


# ---------------------------------------------------------------- 1, 9: файлы проверяются при загрузке
@pytest.mark.parametrize("blob", [
    b"\xff\xd8\xff" + b"\x00" * 200,                     # «JPEG» с мусором
    png_bytes(size=(14000, 14000), mode="1", color=0),   # PNG 196 Мпикс, 24 КБ
    png_bytes(size=(7000, 7000), mode="1", color=0),     # 49 Мпикс: Pillow пропустил бы, наш лимит — нет
    b"%PDF-1.7\n" + b"\x00garbage" * 50,                 # «PDF» из мусора
], ids=["fake-jpeg", "pil-bomb", "over-limit", "fake-pdf"])
def test_F1_bad_file_rejected_and_class_pdf_builds(client: TestClient, paid_event, blob) -> None:
    n = next(_SEQ)
    owner, parent = 9_100_001 + n * 10, 9_100_002 + n * 10
    klass, _ = _class_with_parent(client, owner, parent, f"+790011100{n:02d}", f"+790011199{n:02d}")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    r = _upload(client, exc["id"], sid, parent, blob)
    assert r.status_code == 422, r.text
    with Session(engine) as s:
        assert not tickets.tickets_for(s, exc["id"], sid)
        assert services.get_participant(s, exc["id"], sid).ticket_status == TicketStatus.WAITING_PAYMENT
    assert _pack(client, exc["id"], owner).status_code == 200


def test_F1_saved_broken_file_does_not_break_class_pdf(client: TestClient, paid_event) -> None:
    """Файл, сохранённый до проверки при загрузке (или испорченный на диске), уходит на лист «для учителя»."""
    from pypdf import PdfReader

    owner, parent, parent2 = 9_110_001, 9_110_002, 9_110_003
    klass, invite = _class_with_parent(client, owner, parent, "+79001110101", "+79001110102")
    client.post("/api/v1/parent/join", params={"user_id": parent2}, json={"code": invite["code"], "phone": "+79001110102"})
    client.post("/api/v1/me/accept-terms", params={"user_id": parent2})
    exc, sid = _going(client, klass, owner, parent, paid_event)
    other = next(s["id"] for s in klass["students"] if s["full_name"].startswith("Сидорова"))
    client.post(f"/api/v1/excursions/{exc['id']}/consent", params={"user_id": parent2},
                json={"student_id": other, "status": "APPROVED", "source": "miniapp"})
    assert _upload(client, exc["id"], sid, parent, png_bytes()).status_code == 201
    stored = f"{exc['id']}/{other}_broken.png"
    (tickets.files_dir() / stored).parent.mkdir(parents=True, exist_ok=True)
    (tickets.files_dir() / stored).write_bytes(png_bytes(size=(14000, 14000), mode="1", color=0))
    with Session(engine) as s:
        s.add(TicketFile(excursion_id=exc["id"], student_id=other, content_type="image/png",
                         stored_name=stored, source="bot"))
        s.commit()
    resp = _pack(client, exc["id"], owner)
    assert resp.status_code == 200
    pages = PdfReader(io.BytesIO(resp.content)).pages
    assert len(pages) == 3                                    # обложка, билет Петрова, лист для учителя
    tail = pages[-1].extract_text() or ""
    if tail:                                                  # без шрифта с кириллицей текст не извлечь
        assert "Сидорова" in tail and "не открылся" in tail


def test_9_normalize_exif_transparency_and_size() -> None:
    from PIL import Image

    # Фото «портретом»: пиксели 400×200 и EXIF Orientation=6
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (400, 200), "white").save(buf, format="JPEG", exif=exif.tobytes())
    content, ctype = tickets.normalize(buf.getvalue())
    assert ctype == "image/jpeg"
    with Image.open(io.BytesIO(content)) as img:
        assert img.size == (200, 400) and img.getexif().get(0x0112) is None

    # PNG с прозрачным фоном (QR) — фон белый, а не чёрный
    rgba = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    rgba.paste((0, 0, 0, 255), (10, 10, 90, 40))
    out = io.BytesIO()
    rgba.save(out, format="PNG")
    content, _ = tickets.normalize(out.getvalue())
    with Image.open(io.BytesIO(content)) as img:
        assert min(img.convert("RGB").getpixel((2, 2))) > 240
        assert max(img.convert("RGB").getpixel((50, 25))) < 20

    # Большое фото уменьшается до 2400 px по длинной стороне
    content, _ = tickets.normalize(png_bytes(size=(4000, 3000)))
    with Image.open(io.BytesIO(content)) as img:
        assert max(img.size) == tickets.MAX_SIDE

    with pytest.raises(ValueError, match="Слишком большое"):
        tickets.normalize(png_bytes(size=(14000, 14000), mode="1", color=0))
    with pytest.raises(ValueError, match="PDF"):
        tickets.normalize(b"GIF89a....")


def test_1_pdf_ticket_limits() -> None:
    from pypdf import PdfWriter

    content, ctype = tickets.normalize(pdf_bytes(2))
    assert ctype == "application/pdf" and content.startswith(b"%PDF")
    with pytest.raises(ValueError, match="11 стр"):
        tickets.normalize(pdf_bytes(11))
    locked = io.BytesIO()
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes(1)))
    writer.encrypt(user_password="1234", algorithm="RC4-128")
    writer.write(locked)
    with pytest.raises(ValueError, match="паролем"):
        tickets.normalize(locked.getvalue())
    # Защищён только от правки (пустой пароль) — принимаем и храним расшифрованным
    owner_only = io.BytesIO()
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes(1)))
    writer.encrypt(user_password="", owner_password="owner", algorithm="RC4-128")
    writer.write(owner_only)
    content, _ = tickets.normalize(owner_only.getvalue())
    from pypdf import PdfReader
    assert not PdfReader(io.BytesIO(content)).is_encrypted


# ---------------------------------------------------------------- 3, 13: подписанные ссылки
def test_F2_signed_link_survives_delete_and_points_to_other_family(client: TestClient, paid_event) -> None:
    a_owner, a_parent = 9_200_001, 9_200_002
    b_owner, b_parent = 9_200_011, 9_200_012
    ka, _ = _class_with_parent(client, a_owner, a_parent, "+79002220001", "+79002220002")
    kb, _ = _class_with_parent(client, b_owner, b_parent, "+79002220011", "+79002220012")
    exa, sida = _going(client, ka, a_owner, a_parent, paid_event)
    exb, sidb = _going(client, kb, b_owner, b_parent, paid_event)
    mine = _upload(client, exa["id"], sida, a_parent, png_bytes(color="#ff0000")).json()
    url = mine["url"].replace("http://testserver", "")
    assert client.delete(f"/api/v1/tickets/{mine['id']}", params={"user_id": a_parent}).json()["ok"]
    other = _upload(client, exb["id"], sidb, b_parent, png_bytes(color="#00ff00")).json()
    assert other["id"] != mine["id"], "номер удалённого билета выдан заново"
    assert client.get(url).status_code in (403, 404)
    # Подпись привязана к файлу: с тем же номером, но другим файлом она не подходит
    exp = int(url.split("exp=")[1].split("&")[0])
    sig = url.split("sig=")[1]
    assert not tickets.signed_ok("file", mine["id"], exp, sig, salt="другой-файл")


def test_3_pack_link_expires_when_tickets_change(client: TestClient, paid_event) -> None:
    owner, parent = 9_210_001, 9_210_002
    klass, _ = _class_with_parent(client, owner, parent, "+79002230001", "+79002230002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    link = client.post(f"/api/v1/excursions/{exc['id']}/tickets-pdf", params={"user_id": owner}).json()["url"]
    path = link.replace("http://testserver", "")
    first = client.get(path)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-store"
    assert _upload(client, exc["id"], sid, parent, png_bytes()).status_code == 201
    assert client.get(path).status_code == 403


def test_F8_non_ascii_sig_is_not_500(client: TestClient, paid_event) -> None:
    owner = 9_800_001
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "4", "letter": "А", "teacher_name": "Учитель", "students": []}).json()
    exc = make_excursion(client, {"id": klass["id"], "owner_user_id": owner}, paid_event["id"])
    raw = TestClient(app, raise_server_exceptions=False)
    for path in (f"/api/v1/excursions/{exc['id']}/tickets.pdf", f"/api/v1/excursions/{exc['id']}/export-order"):
        r = raw.get(path, params={"exp": 99999999999, "sig": "я"})
        assert r.status_code in (403, 404), (path, r.status_code)


# ---------------------------------------------------------------- 6: удаление файла и оплата
def test_F3_delete_file_keeps_teacher_confirmed_ticket(client: TestClient, paid_event) -> None:
    owner, parent = 9_300_001, 9_300_002
    klass, _ = _class_with_parent(client, owner, parent, "+79003330001", "+79003330002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    r = client.post(f"/api/v1/excursions/{exc['id']}/ticket-confirm", params={"user_id": owner},
                    json={"student_id": sid, "ticket_number": "GRP-77", "source": "teacher"})
    assert r.json()["ticket_status"] == "PAID"
    row = _upload(client, exc["id"], sid, parent, png_bytes()).json()
    client.delete(f"/api/v1/tickets/{row['id']}", params={"user_id": parent})
    with Session(engine) as s:
        p = services.get_participant(s, exc["id"], sid)
        assert p.ticket_status == TicketStatus.PAID, f"оплата учителя (№{p.ticket_number}) потеряна"
        actions = [a.action for a in s.exec(select(ConsentAudit).where(
            ConsentAudit.excursion_id == exc["id"], ConsentAudit.student_id == sid)).all()]
        assert "TICKET_FILE_DELETED" in actions


# ---------------------------------------------------------------- 8: групповой чат
@pytest.mark.asyncio
async def test_F4_group_chat_ignored(client: TestClient, paid_event) -> None:
    owner, parent = 9_400_001, 9_400_002
    klass, _ = _class_with_parent(client, owner, parent, "+79004440001", "+79004440002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    fake = FakeClient(blob=png_bytes())
    bot = BotService(client=fake)
    group_chat = -70000001
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": group_chat, "chat_type": "chat"},
        "body": {"text": "фото с прошлой экскурсии", "attachments": [
            {"type": "image", "payload": {"url": "https://i.oneme.ru/x.jpg"}}]}}})
    # /trips в общем чате выдал бы туда карточки ребёнка
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": group_chat, "chat_type": "chat"},
        "body": {"text": "/trips"}}})
    with Session(engine) as s:
        assert not tickets.tickets_for(s, exc["id"], sid)
    assert not fake.sent, [m["text"][:70] for m in fake.sent]
    # В личном чате всё по-прежнему
    await bot.handle_update({"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": 77, "chat_type": "dialog"},
        "body": {"text": "", "attachments": [{"type": "image", "payload": {"url": "https://i.oneme.ru/x.jpg"}}]}}})
    assert "Это билет?" in fake.sent[-1]["text"]


# ---------------------------------------------------------------- 4, 7: демо и удаление ученика
def test_F5_removed_demo_student_does_not_stall_demo(client: TestClient, paid_event) -> None:
    owner = 9_500_001
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, paid_event["id"])
    with Session(engine) as s:
        ticket_answer = s.exec(select(DemoAnswer).where(DemoAnswer.excursion_id == exc["id"],
                                                        DemoAnswer.decision == "TICKET")).first()
        assert ticket_answer, "в демо нет запланированных билетов"
        victim = ticket_answer.student_id
    assert client.delete(f"/api/v1/classes/{info['class_id']}/students/{victim}",
                         params={"user_id": owner}).json()["ok"]
    with Session(engine) as s:
        assert not s.exec(select(DemoAnswer).where(DemoAnswer.student_id == victim)).all()
        demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=10))
        assert not s.exec(select(DemoAnswer).where(DemoAnswer.excursion_id == exc["id"],
                                                   DemoAnswer.done == False)).all()  # noqa: E712
        answered = [p for p in s.get(Excursion, exc["id"]).participants if p.consent_status.value != "PENDING"]
        assert len(answered) >= 5


def test_4_one_failing_demo_answer_does_not_block_others(client: TestClient, paid_event, monkeypatch) -> None:
    owner = 9_510_001
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, paid_event["id"])
    real = services.apply_consent
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("сбой базы")
        return real(*args, **kwargs)

    monkeypatch.setattr(services, "apply_consent", flaky)
    with Session(engine) as s:
        # Ответ по ученику, которого уже нет (удалили между планированием и ответом)
        s.add(DemoAnswer(excursion_id=exc["id"], student_id=987654321, decision="TICKET",
                         due_at=datetime.utcnow() - timedelta(hours=1)))
        s.commit()
        touched = demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=10))
        assert exc["id"] in touched
        assert not s.exec(select(DemoAnswer).where(DemoAnswer.excursion_id == exc["id"],
                                                   DemoAnswer.done == False)).all()  # noqa: E712
        answered = [p for p in s.get(Excursion, exc["id"]).participants if p.consent_status.value != "PENDING"]
        assert len(answered) >= 5


def test_F7_student_removed_with_tickets_and_requests(client: TestClient, paid_event) -> None:
    owner, parent = 9_700_001, 9_700_002
    klass, _ = _class_with_parent(client, owner, parent, "+79007770001", "+79007770002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    row = _upload(client, exc["id"], sid, parent, png_bytes()).json()
    with Session(engine) as s:
        stored = s.get(TicketFile, row["id"]).stored_name
        s.add(ChildJoinRequest(class_id=klass["id"], max_user_id=9_700_009, child_name="Петров Илья Олегович",
                               phone_number="+79007779999", status="APPROVED", student_id=sid))
        s.commit()
    assert client.delete(f"/api/v1/classes/{klass['id']}/students/{sid}", params={"user_id": owner}).json()["ok"]
    with Session(engine) as s:
        assert s.get(TicketFile, row["id"]) is None
        assert not s.exec(select(ChildJoinRequest).where(ChildJoinRequest.student_id == sid)).all()
    assert not (tickets.files_dir() / stored).exists()


def test_7_demo_reset_removes_ticket_files(client: TestClient, paid_event) -> None:
    owner = 9_720_001
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc = make_excursion(client, {"id": info["class_id"], "owner_user_id": owner}, paid_event["id"])
    with Session(engine) as s:
        demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=10))
        stored = [r.stored_name for r in tickets.tickets_for(s, exc["id"])]
    assert stored
    client.post("/api/v1/demo/reset", params={"user_id": owner})
    with Session(engine) as s:
        assert not tickets.tickets_for(s, exc["id"])
    assert not any((tickets.files_dir() / name).exists() for name in stored)


def test_7_rejected_request_forgets_phone_and_old_requests_purged(client: TestClient) -> None:
    owner, parent = 9_730_001, 9_730_002
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "9", "letter": "Е", "teacher_name": "Учитель", "students": []}).json()
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "Чужой Ребёнок", "phone": "+79007300000"})
    req = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()[0]
    done = client.post(f"/api/v1/join-requests/{req['id']}/decide", params={"user_id": owner},
                       json={"approve": False}).json()
    assert done["status"] == "REJECTED" and done["phone_number"] == ""
    with Session(engine) as s:
        assert joins.purge_decided(s) == 0                       # свежую не трогаем
        row = s.get(ChildJoinRequest, req["id"])
        row.decided_at = datetime.utcnow() - timedelta(days=31)
        s.add(row)
        s.commit()
        assert joins.purge_decided(s) >= 1
        assert s.get(ChildJoinRequest, req["id"]) is None


# ---------------------------------------------------------------- 2: заявка на ученика, у которого есть родитель
@pytest.mark.asyncio
async def test_F6_join_request_for_existing_child_warns_teacher(client: TestClient) -> None:
    owner, stranger = 9_600_001, 9_600_009
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "7", "letter": "Г", "teacher_name": "Учитель Три", "students": [
            {"full_name": "Орлова Вера Павловна", "parent_phone": "+79006660000"}]}).json()
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    client.post("/api/v1/parent/join-request", params={"user_id": stranger}, json={
        "code": code, "child_name": "Орлова Вера Павловна", "phone": "+79006669999"})
    with Session(engine) as s:
        req = s.exec(select(ChildJoinRequest).where(ChildJoinRequest.max_user_id == stranger)).first()
    fake = FakeClient()
    await BotService(client=fake).notify_join_request(req.id)
    text, buttons = fake.sent[-1]["text"], str(fake.sent[-1]["attachments"])
    assert "уже в списке" in text and "законный представитель" in text
    assert f"jr:{req.id}:L" in buttons and "Да, это второй родитель" in buttons and f"jr:{req.id}:R" in buttons
    assert f"jr:{req.id}:A" not in buttons
    listed = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()[0]
    assert listed["needs_check"] is True and listed["match_name"] == "Орлова Вера Павловна"


@pytest.mark.asyncio
async def test_F6b_stranger_not_linked_without_explicit_check(client: TestClient, paid_event) -> None:
    owner, real, stranger = 9_960_001, 9_960_002, 9_960_666
    klass, invite = _class_with_parent(client, owner, real, "+79009600001", "+79009600002")
    sid = next(s["id"] for s in klass["students"] if s["full_name"].startswith("Петров"))
    exc = make_excursion(client, {"id": klass["id"], "owner_user_id": owner}, paid_event["id"])
    client.post("/api/v1/parent/join-request", params={"user_id": stranger}, json={
        "code": invite["code"], "child_name": "Петров Илья", "phone": "+79009606666", "parent_name": "Иванов Иван"})
    req = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()[0]
    plain = client.post(f"/api/v1/join-requests/{req['id']}/decide", params={"user_id": owner}, json={"approve": True})
    assert plain.status_code == 422 and "уже в списке" in plain.json()["detail"]
    client.post("/api/v1/me/accept-terms", params={"user_id": stranger})
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": stranger, "user_id": stranger}).json()
    assert ctx["children"] == []
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", params={"user_id": stranger},
                    json={"student_id": sid, "status": "REJECTED", "source": "miniapp"})
    assert r.status_code == 403
    # Учитель знает этого человека и явно подключает его вторым родителем
    done = client.post(f"/api/v1/join-requests/{req['id']}/decide", params={"user_id": owner},
                       json={"approve": True, "link_existing": True}).json()
    assert done["status"] == "APPROVED"
    with Session(engine) as s:
        student = s.get(Student, sid)
        assert student.full_name == "Петров Илья Олегович"          # ФИО из заявки не переписывает список
        assert any(p.max_user_id == stranger and p.confirmed for p in services.student_parents(s, sid))
    fake = FakeClient()
    await BotService(client=fake).notify_parent_added(req["id"])
    assert [m["user_id"] for m in fake.sent] == [real]
    assert "ещё одного родителя" in fake.sent[0]["text"] and "Иванов Иван" in fake.sent[0]["text"]


def test_2_approve_all_skips_children_with_parent(client: TestClient) -> None:
    owner, real, stranger, newcomer = 9_970_001, 9_970_002, 9_970_666, 9_970_003
    klass, invite = _class_with_parent(client, owner, real, "+79009700001", "+79009700002")
    for user, child, phone in ((stranger, "Петров Илья Олегович", "+79009706666"),
                               (newcomer, "Новикова Ева Сергеевна", "+79009700003")):
        client.post("/api/v1/parent/join-request", params={"user_id": user}, json={
            "code": invite["code"], "child_name": child, "phone": phone})
    done = client.post(f"/api/v1/classes/{klass['id']}/join-requests/approve-all", params={"user_id": owner}).json()
    status = {r["child_name"]: (r["status"], r["needs_check"]) for r in done}
    assert status == {"Новикова Ева Сергеевна": ("APPROVED", False), "Петров Илья Олегович": ("PENDING", True)}
    left = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()
    assert [r["child_name"] for r in left] == ["Петров Илья Олегович"]


def test_2_existing_child_without_parent_links_and_keeps_name(client: TestClient) -> None:
    owner, parent = 9_980_001, 9_980_002
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "3", "letter": "Б", "teacher_name": "Учитель", "students": [{"full_name": "Козлов Матвей"}]}).json()
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    client.post("/api/v1/parent/join-request", params={"user_id": parent}, json={
        "code": code, "child_name": "Козлов Матвей Денисович", "phone": "+79009800002"})
    req = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()[0]
    assert req["needs_check"] is False and req["match_name"] == "Козлов Матвей"
    assert client.post(f"/api/v1/join-requests/{req['id']}/decide", params={"user_id": owner},
                       json={"approve": True}).json()["status"] == "APPROVED"
    roster = client.get(f"/api/v1/classes/{klass['id']}/roster", params={"user_id": owner}).json()
    assert [s["full_name"] for s in roster["students"]] == ["Козлов Матвей"]


# ---------------------------------------------------------------- 10: только подтверждённый родитель
@pytest.mark.asyncio
async def test_F9_unconfirmed_link_has_no_api_access(client: TestClient, paid_event) -> None:
    owner, parent, stranger = 9_900_001, 9_900_002, 9_900_666
    klass, _ = _class_with_parent(client, owner, parent, "+79009990001", "+79009990002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    row = _upload(client, exc["id"], sid, parent, png_bytes()).json()
    with Session(engine) as s:   # состояние после /start bind_<код> до ответа «Да, это мой ребёнок»
        s.add(ParentContact(student_id=sid, full_name="", phone_number="", max_user_id=stranger, confirmed=False))
        s.commit()
    fake = FakeClient()
    await BotService(client=fake).handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb", "payload": f"tup:{exc['id']}:{sid}", "user": {"user_id": stranger}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "для родителя" in fake.answers[-1]["notification"]
    seen = client.get(f"/api/v1/excursions/{exc['id']}/tickets", params={"user_id": stranger})
    gone = client.delete(f"/api/v1/tickets/{row['id']}", params={"user_id": stranger})
    assert seen.status_code == 403 and gone.status_code == 403
    client.post("/api/v1/me/accept-terms", params={"user_id": stranger})
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent", params={"user_id": stranger},
                    json={"student_id": sid, "status": "REJECTED", "source": "miniapp"})
    assert r.status_code == 403 and "подтвердите" in r.json()["detail"]


# ---------------------------------------------------------------- 11: лимит заявок
def test_F12_join_request_flood(client: TestClient, monkeypatch) -> None:
    owner, spammer = 9_920_001, 9_920_666
    klass = client.post("/api/v1/classes", params={"user_id": owner}, json={
        "grade": "8", "letter": "Д", "teacher_name": "Учитель", "students": []}).json()
    code = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()["code"]
    letters = "абвгдежзиклмнопрстуфхцчшщэюя"
    codes = []
    for i in range(40):
        codes.append(client.post("/api/v1/parent/join-request", params={"user_id": spammer}, json={
            "code": code, "child_name": f"Иванов Ив{letters[i % 28]}{letters[i // 28]}н",
            "phone": "+79009200000"}).status_code)
    pending = client.get(f"/api/v1/classes/{klass['id']}/join-requests", params={"user_id": owner}).json()
    assert len(pending) == joins.MAX_OPEN_PER_PARENT and codes.count(422) == 40 - joins.MAX_OPEN_PER_PARENT
    # И на весь класс: открытых заявок не больше MAX_OPEN_PER_CLASS
    monkeypatch.setattr(joins, "MAX_OPEN_PER_CLASS", joins.MAX_OPEN_PER_PARENT + 1)
    ok = client.post("/api/v1/parent/join-request", params={"user_id": spammer + 1}, json={
        "code": code, "child_name": "Петрова Анна", "phone": "+79009200001"})
    full = client.post("/api/v1/parent/join-request", params={"user_id": spammer + 2}, json={
        "code": code, "child_name": "Сидоров Олег", "phone": "+79009200002"})
    assert ok.status_code == 200 and full.status_code == 422


# ---------------------------------------------------------------- 12: вебхук и скачивание файлов
def test_F13_webhook_closed_unless_enabled_with_secret(client: TestClient, paid_event, monkeypatch) -> None:
    from app import max_client
    from app.config import get_settings

    owner, parent = 9_930_001, 9_930_002
    klass, _ = _class_with_parent(client, owner, parent, "+79009300001", "+79009300002")
    exc, sid = _going(client, klass, owner, parent, paid_event)
    fetched: list[str] = []

    async def fake_download(self, url, limit=0):
        fetched.append(url)
        return png_bytes()

    async def no_send(self, **kw):
        return None

    monkeypatch.setattr(max_client.MaxClient, "download", fake_download)
    monkeypatch.setattr(max_client.MaxClient, "send_message", no_send)
    update = {"update_type": "message_created", "message": {
        "sender": {"user_id": parent}, "recipient": {"chat_id": 5},
        "body": {"attachments": [{"type": "file", "payload": {"url": "https://attacker.example/redirect"}}]}}}
    assert client.post("/webhook/max", json=update).status_code == 404          # бот выключен
    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "MAX_BOT_MODE", "polling")
    assert client.post("/webhook/max", json=update).status_code == 404          # бот опрашивает сам
    monkeypatch.setattr(settings, "MAX_BOT_MODE", "webhook")
    assert client.post("/webhook/max", json=update).status_code == 503          # секрет не настроен
    monkeypatch.setattr(settings, "MAX_WEBHOOK_SECRET", "s3cret")
    assert client.post("/webhook/max", json=update).status_code == 401
    assert client.post("/webhook/max", json=update, headers={"X-Max-Bot-Api-Secret": "wrong"}).status_code == 401
    assert not fetched, f"анонимный POST /webhook/max заставил сервер скачать {fetched}"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://93.184.216.34/ticket.jpg", "https://127.0.0.1/x", "https://169.254.169.254/latest/meta-data/",
    "https://10.1.2.3/x", "https://[::1]/x", "https://localhost/x",
])
async def test_12_download_guard_blocks_internal(url) -> None:
    import httpx

    from app.max_client import BlockedUrl, public_https_only

    with pytest.raises(BlockedUrl):
        await public_https_only(httpx.Request("GET", url))


@pytest.mark.asyncio
async def test_12_download_does_not_follow_redirect_inside(monkeypatch) -> None:
    import httpx

    from app import max_client

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data/"})
        if request.url.path == "/http":
            return httpx.Response(302, headers={"Location": "http://93.184.216.34/plain"})
        return httpx.Response(200, content=b"%PDF-ticket")

    original = httpx.AsyncClient

    class Mocked(original):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(max_client.httpx, "AsyncClient", Mocked)
    client = max_client.MaxClient(token="x")
    assert await client.download("https://93.184.216.34/ticket.pdf") == b"%PDF-ticket"
    assert await client.download("https://93.184.216.34/redirect") is None
    assert await client.download("https://93.184.216.34/http") is None
    assert all("169.254" not in u and not u.startswith("http://") for u in seen), seen
    assert await max_client.MaxClient(token="").download("https://93.184.216.34/ticket.pdf") is None
