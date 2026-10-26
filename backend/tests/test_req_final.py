"""Доработки к финалу: демо-песочница, роли, приглашение класса, привязка по телефону, бот."""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import demo
from app.bot import BotService
from app.db import engine
from app.max_validate import verify_phone
from app.models import DemoAnswer, Excursion, ParentContact, SchoolClass, Student

from conftest import make_excursion

USER = 7_700_001


class FakeClient:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.answers: list[dict] = []
        self.uploads: list[str] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": "mid.1"}}}

    async def answer_callback(self, callback_id, **kwargs):
        self.answers.append({"callback_id": callback_id, **kwargs})
        return {"success": True}

    async def upload_file(self, content: bytes, filename: str, upload_type: str = "file"):
        self.uploads.append(filename)
        return f"token-{filename}"

    async def send_document(self, **kwargs):
        self.sent.append({"document": True, **kwargs})
        return {"ok": True}


def test_FIN_1_me_anonymous(client: TestClient) -> None:
    body = client.get("/api/v1/me").json()
    assert body["user_id"] is None and body["auth"] == "anonymous"
    assert body["is_teacher"] is False and body["is_parent"] is False


def test_FIN_2_demo_sandbox_both_roles(client: TestClient) -> None:
    r = client.post("/api/v1/demo/start", params={"user_id": USER})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["created"] is True and info["class_title"] == "7Б" and info["child_student_id"]
    assert info["excursion_ids"], "в песочнице должен быть пример выезда"
    me = client.get("/api/v1/me", params={"user_id": USER}).json()
    assert me["is_teacher"] and me["is_parent"] and me["has_demo"]
    # Повторный вызов не плодит классы
    again = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    assert again["created"] is False and again["class_id"] == info["class_id"]


def test_FIN_3_mine_filters_classes_and_trips(client: TestClient) -> None:
    client.post("/api/v1/demo/start", params={"user_id": USER})
    mine = client.get("/api/v1/classes", params={"user_id": USER, "mine": True}).json()
    assert [c["title"] for c in mine] == ["7Б"] and mine[0]["is_demo"] is True
    assert mine[0]["parents_connected"] == len(mine[0]["students"])
    trips = client.get("/api/v1/excursions", params={"user_id": USER, "mine": True}).json()
    assert trips and all(t["class_id"] == mine[0]["id"] for t in trips)
    assert trips[0]["stats"]["total"] == len(mine[0]["students"])
    # Чужой пользователь демо-класса не видит
    other = client.get("/api/v1/classes", params={"user_id": USER + 1, "mine": True}).json()
    assert all(c["id"] != mine[0]["id"] for c in other)


def test_FIN_4_sandbox_parent_sees_own_child(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": USER}).json()
    child = next(c for c in ctx["children"] if c["student_id"] == info["child_student_id"])
    assert child["is_demo"] is True and child["class_title"] == "7Б"
    assert child["excursions"] and child["excursions"][0]["consent_status"] == "PENDING"


def test_FIN_5_virtual_parents_answer(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    events = client.get("/api/v1/culture-events").json()
    klass = {"id": info["class_id"], "owner_user_id": USER}
    exc = make_excursion(client, klass, events[1]["id"])
    with Session(engine) as s:
        planned = s.exec(select(DemoAnswer).where(DemoAnswer.excursion_id == exc["id"])).all()
        assert planned, "виртуальные родители должны запланировать ответы"
        demo.process_due_answers(s, now=datetime.utcnow() + timedelta(minutes=5))
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard", params={"user_id": USER}).json()
    statuses = [p["consent_status"] for p in dash["participants"]]
    assert statuses.count("APPROVED") >= 6
    assert statuses.count("REJECTED") == 1
    # Ребёнок самого пользователя и двое «молчунов» ждут ответа
    assert statuses.count("PENDING") == 3


def test_FIN_6_class_invite_and_join_by_phone(client: TestClient) -> None:
    owner = 7_700_100
    klass = client.post("/api/v1/classes", json={
        "grade": "6", "letter": "Г", "user_id": owner, "students": [
            {"full_name": "Иванов Иван", "parent_phone": "+7 (912) 345-67-01", "parent_name": "Иванова Анна"},
            {"full_name": "Петрова Мария", "parent_phone": "+79123456702", "parent_name": "Петров Олег"},
        ]}).json()
    inv = client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner}).json()
    assert inv["code"] and f"startapp=join_{inv['code']}" in inv["app_link"]
    assert client.post(f"/api/v1/classes/{klass['id']}/invite", params={"user_id": owner + 1}).status_code == 403
    info = client.get(f"/api/v1/join/{inv['code']}").json()
    assert info["class_title"] == "6Г" and info["students_count"] == 2 and info["phones_listed"] == 2
    empty = client.post("/api/v1/classes", json={"grade": "6", "letter": "Д", "user_id": owner, "students": []}).json()
    empty_inv = client.post(f"/api/v1/classes/{empty['id']}/invite", params={"user_id": owner}).json()
    assert client.get(f"/api/v1/join/{empty_inv['code']}").json()["phones_listed"] == 0

    student = next(s for s in klass["students"] if s["full_name"] == "Петрова Мария")
    phone = student["parents"][0]["phone_number"]
    newbie = 7_700_555
    bad = client.post("/api/v1/parent/join", params={"user_id": newbie},
                      json={"code": inv["code"], "phone": "+7 999 000-00-00"}).json()
    assert bad["status"] == "not_found"
    ok = client.post("/api/v1/parent/join", params={"user_id": newbie},
                     json={"code": inv["code"], "phone": "8" + phone[2:]}).json()
    assert ok["status"] == "linked" and student["full_name"] in ok["children"]
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": newbie}).json()
    assert any(c["student_id"] == student["id"] for c in ctx["children"])


def test_FIN_7_join_bad_code(client: TestClient) -> None:
    r = client.post("/api/v1/parent/join", params={"user_id": 1}, json={"code": "nope", "phone": "79000000000"})
    assert r.json()["status"] == "bad_code"
    assert client.get("/api/v1/join/nope").status_code == 404


def test_FIN_8_verify_phone_signature() -> None:
    token, phone, uid, auth = "bot-token", "79001234567", 42, "1771409719"
    msg = f"authDate={auth}\nphone={phone}\nuserId={uid}"
    good = hmac.new(token.encode(), msg.encode(), hashlib.sha256).hexdigest()
    assert verify_phone(auth, "+" + phone, uid, good, token)
    assert not verify_phone(auth, phone, uid + 1, good, token)
    assert not verify_phone(auth, phone, uid, "0" * 64, token)


def test_FIN_9_role_saved(client: TestClient) -> None:
    r = client.post("/api/v1/me/role", params={"user_id": USER}, json={"role": "parent"})
    assert r.status_code == 200 and r.json()["role"] == "parent"


@pytest.mark.asyncio
async def test_FIN_10_invite_parents_and_complete_notice(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    fake = FakeClient()
    bot = BotService(client=fake)
    exc_id = info["excursion_ids"][0]
    sent = await bot.invite_parents(exc_id)
    assert sent == 1 and "пойдёт" in str(fake.sent[-1]["attachments"])
    client.post("/api/v1/me/accept-terms", params={"user_id": USER})
    # Пользователь отвечает в боте — карточка заменяется статусом
    await bot.handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "cb-9", "payload": f"consent:{exc_id}:{info['child_student_id']}:APPROVED",
        "user": {"user_id": USER}}, "message": {"recipient": {"chat_id": 1}}})
    assert "идёт на выезд" in fake.answers[-1]["text"]
    # Остальные отвечают — учителю приходит итог с кнопкой документов
    with Session(engine) as s:
        exc = s.get(Excursion, exc_id)
        for part in exc.participants:
            if part.consent_status.value == "PENDING":
                part.consent_status = "APPROVED"
                s.add(part)
        s.commit()
    assert await bot.notify_teacher_if_complete(exc_id) is True
    assert "docs:" in str(fake.sent[-1]["attachments"])
    assert await bot.notify_teacher_if_complete(exc_id) is False  # только один раз


@pytest.mark.asyncio
async def test_FIN_11_documents_sent_as_files(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    fake = FakeClient()
    with Session(engine) as s:
        exc = s.get(Excursion, info["excursion_ids"][0])
        ok = await BotService(client=fake).send_documents(s, exc, USER)
    assert ok and any(f.endswith(".pdf") for f in fake.uploads) and any(f.endswith(".docx") for f in fake.uploads)


def test_FIN_12_demo_reset_recreates(client: TestClient) -> None:
    first = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    reset = client.post("/api/v1/demo/reset", params={"user_id": USER}).json()
    assert reset["created"] is True and first["created"] is False
    with Session(engine) as s:
        classes = s.exec(select(SchoolClass).where(SchoolClass.owner_user_id == USER,
                                                   SchoolClass.is_demo == True)).all()  # noqa: E712
        assert len(classes) == 1
        assert len(s.exec(select(Student).where(Student.class_id == classes[0].id)).all()) == 12
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": USER}).json()
    assert ctx["children"][0]["excursions"][0]["consent_status"] == "PENDING"


def test_FIN_13_change_answer_rules(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    exc_id, sid = info["excursion_ids"][0], info["child_student_id"]
    client.post("/api/v1/me/accept-terms", params={"user_id": USER})
    client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": USER},
                json={"student_id": sid, "status": "APPROVED", "max_user_id": USER})
    # Другой человек чужой ответ сбросить не может
    other = client.post(f"/api/v1/excursions/{exc_id}/consent/reset", params={"user_id": USER + 5},
                        json={"student_id": sid}).json()
    assert other["changed"] is False
    mine = client.post(f"/api/v1/excursions/{exc_id}/consent/reset", params={"user_id": USER},
                       json={"student_id": sid}).json()
    assert mine["changed"] is True and mine["consent_status"] == "PENDING"


def test_FIN_14_teacher_paper_consent(client: TestClient) -> None:
    info = client.post("/api/v1/demo/start", params={"user_id": USER}).json()
    exc_id = info["excursion_ids"][0]
    dash = client.get(f"/api/v1/excursions/{exc_id}/dashboard", params={"user_id": USER}).json()
    pending = next(p for p in dash["participants"] if p["consent_status"] == "PENDING"
                   and p["student_id"] != info["child_student_id"])
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": USER},
                    json={"student_id": pending["student_id"], "status": "APPROVED", "source": "paper",
                          "parent_name": "Бумажное согласие"}).json()
    assert r["changed"] is True
    # Учитель может снять свою отметку, посторонний — нет
    assert client.post(f"/api/v1/excursions/{exc_id}/consent/reset", params={"user_id": USER + 9},
                       json={"student_id": pending["student_id"], "as_teacher": True}).status_code == 403
    ok = client.post(f"/api/v1/excursions/{exc_id}/consent/reset", params={"user_id": USER},
                     json={"student_id": pending["student_id"], "as_teacher": True}).json()
    assert ok["changed"] is True


def test_FIN_15_live_demo_join_adopts_virtual_child(client: TestClient) -> None:
    owner = 7_700_300
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    inv = client.post(f"/api/v1/classes/{info['class_id']}/invite", params={"user_id": owner}).json()
    assert client.get(f"/api/v1/join/{inv['code']}").json()["is_demo"] is True
    guest = 7_700_301
    r = client.post("/api/v1/parent/join", params={"user_id": guest}, json={"code": inv["code"]}).json()
    assert r["status"] == "linked" and len(r["children"]) == 1
    # Повторное открытие ссылки не забирает второго ребёнка
    again = client.post("/api/v1/parent/join", params={"user_id": guest}, json={"code": inv["code"]}).json()
    assert again["children"] == r["children"]
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": guest}).json()
    assert ctx["children"][0]["student_name"] == r["children"][0]
    with Session(engine) as s:
        p = s.exec(select(ParentContact).where(ParentContact.max_user_id == guest)).first()
        assert p.is_virtual is False
        assert not s.exec(select(DemoAnswer).where(DemoAnswer.student_id == p.student_id,
                                                   DemoAnswer.done == False)).all()  # noqa: E712


def test_FIN_16_roll_call_milestones_and_cancel(client: TestClient) -> None:
    owner = 7_700_400
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id = info["excursion_ids"][0]
    dash = client.get(f"/api/v1/excursions/{exc_id}/dashboard", params={"user_id": owner}).json()
    going = next(p for p in dash["participants"] if p["consent_status"] == "APPROVED")
    assert client.post(f"/api/v1/excursions/{exc_id}/attendance", params={"user_id": owner + 1},
                       json={"student_id": going["student_id"], "present": False}).status_code == 403
    r = client.post(f"/api/v1/excursions/{exc_id}/attendance", params={"user_id": owner},
                    json={"student_id": going["student_id"], "present": False})
    assert r.status_code == 200
    m = client.post(f"/api/v1/excursions/{exc_id}/milestone", params={"user_id": owner},
                    json={"kind": "departed"}).json()
    assert going["full_name"] in m["absent"]
    trip = client.get(f"/api/v1/excursions/{exc_id}", params={"user_id": owner}).json()
    assert trip["departed_at"] and not trip["returned_at"]
    # Повторное «выехали» не рассылает сообщения заново и не сдвигает время
    again = client.post(f"/api/v1/excursions/{exc_id}/milestone", params={"user_id": owner},
                        json={"kind": "departed"}).json()
    assert again["notified"] == 0 and again["at"] == m["at"]
    # Группа уже выехала — отменить выезд нельзя (родителям ушло бы «ребёнок остаётся на уроках»)
    assert client.post(f"/api/v1/excursions/{exc_id}/cancel", params={"user_id": owner}).status_code == 409
    assert client.post(f"/api/v1/excursions/{exc_id}/milestone", params={"user_id": owner},
                       json={"kind": "returned"}).status_code == 200

    # Отмена до выезда: ответить нельзя, «выехали» нельзя, родитель видит отмену
    info = client.post("/api/v1/demo/reset", params={"user_id": owner}).json()
    exc_id = info["excursion_ids"][0]
    dash = client.get(f"/api/v1/excursions/{exc_id}/dashboard", params={"user_id": owner}).json()
    c = client.post(f"/api/v1/excursions/{exc_id}/cancel", params={"user_id": owner}).json()
    assert c["ok"] is True
    assert client.get(f"/api/v1/excursions/{exc_id}", params={"user_id": owner}).json()["cancelled"] is True
    assert client.post(f"/api/v1/excursions/{exc_id}/milestone", params={"user_id": owner},
                       json={"kind": "departed"}).status_code == 409
    waiting = next(p for p in dash["participants"] if p["consent_status"] == "PENDING")
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": owner},
                    json={"student_id": waiting["student_id"], "status": "APPROVED", "source": "paper",
                          "parent_name": "Тест"}).json()
    assert r["changed"] is False and "отменён" in r["message"]
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": owner}).json()
    trip = next(t for t in ctx["children"][0]["excursions"] if t["excursion_id"] == exc_id)
    assert trip["cancelled"] is True and trip["can_change"] is False


def test_FIN_19_gender_from_patronymic() -> None:
    from app.bot import is_female

    assert is_female("Сафина Алина Маратовна")
    assert not is_female("Сафин Тимур Ренатович")
    assert is_female("Иванова Анна")
    assert not is_female("Иванов Иван")


def test_FIN_17_second_parent_by_link(client: TestClient) -> None:
    owner = 7_700_500
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    sid = info["child_student_id"]
    assert client.post("/api/v1/parent/second-invite", params={"user_id": owner + 9},
                       json={"student_id": sid}).status_code == 403
    inv = client.post("/api/v1/parent/second-invite", params={"user_id": owner}, json={"student_id": sid}).json()
    assert "startapp=pair_" in inv["app_link"]
    assert client.get(f"/api/v1/parent/pair/{inv['code']}").json()["student_name"] == inv["student_name"]
    spouse = 7_700_501
    r = client.post("/api/v1/parent/pair", params={"user_id": spouse}, json={"code": inv["code"]}).json()
    # Подписантом второй родитель становится только после подтверждения учителем (ст. 64 СК)
    assert r["status"] == "requested"
    assert client.get("/api/v1/parent/context", params={"max_user_id": spouse}).json()["children"] == []
    reqs = client.get(f"/api/v1/classes/{info['class_id']}/join-requests", params={"user_id": owner}).json()
    assert reqs[0]["parent_role"] == "Второй родитель" and reqs[0]["match_has_parent"] is True
    client.post(f"/api/v1/join-requests/{reqs[0]['id']}/decide", params={"user_id": owner}, json={"approve": True})
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": spouse}).json()
    assert ctx["children"][0]["student_id"] == sid
    # Ссылка одноразовая
    assert client.post("/api/v1/parent/pair", params={"user_id": spouse + 1},
                       json={"code": inv["code"]}).json()["status"] == "bad_code"


def test_FIN_18_pushkin_only_for_14_plus(client: TestClient) -> None:
    from datetime import date

    from app import services as svc
    from app.models import Excursion as Exc, Student as St

    exc = Exc(class_id=1, title="t", is_pushkin_card=True, event_date=date(2026, 11, 1))
    assert svc.pushkin_for(St(class_id=1, full_name="a", birth_date=date(2013, 4, 12)), exc) is False
    assert svc.pushkin_for(St(class_id=1, full_name="b", birth_date=date(2011, 10, 1)), exc) is True
    assert svc.pushkin_for(St(class_id=1, full_name="c"), exc) is None


def test_FIN_20_consent_only_by_parent_or_teacher_paper(client: TestClient) -> None:
    owner = 7_700_700
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id, own_child = info["excursion_ids"][0], info["child_student_id"]
    dash = client.get(f"/api/v1/excursions/{exc_id}/dashboard", params={"user_id": owner}).json()
    other = next(p for p in dash["participants"]
                 if p["consent_status"] == "PENDING" and p["student_id"] != own_child)
    stranger = owner + 77
    # Чужой человек не может ответить за ребёнка
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": stranger},
                    json={"student_id": own_child, "status": "APPROVED", "source": "miniapp"})
    assert r.status_code == 403
    # …и не может отметить бумажный бланк в чужом классе
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": stranger},
                    json={"student_id": other["student_id"], "status": "APPROVED", "source": "paper"})
    assert r.status_code == 403
    # Учитель отмечает бланк: подписью MAX учителя это не становится
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": owner},
                    json={"student_id": other["student_id"], "status": "APPROVED", "source": "paper",
                          "parent_name": "Родитель (бумажный бланк, отметил учитель)"})
    assert r.status_code == 200 and r.json()["changed"] is True
    row = next(p for p in client.get(f"/api/v1/excursions/{exc_id}/dashboard",
                                     params={"user_id": owner}).json()["participants"]
               if p["student_id"] == other["student_id"])
    assert row["signed_source"] == "paper" and row["signed_by_max_user_id"] is None
    # Родитель без принятого соглашения о ПЭП ответить не может, после принятия — может
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": owner},
                    json={"student_id": own_child, "status": "APPROVED", "source": "miniapp"})
    assert r.status_code == 409
    client.post("/api/v1/me/accept-terms", params={"user_id": owner})
    r = client.post(f"/api/v1/excursions/{exc_id}/consent", params={"user_id": owner},
                    json={"student_id": own_child, "status": "APPROVED", "source": "miniapp"})
    assert r.status_code == 200


def test_FIN_21_live_demo_link_stable_and_roomy(client: TestClient) -> None:
    owner = 7_700_800
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    code = client.post(f"/api/v1/classes/{info['class_id']}/invite", params={"user_id": owner}).json()["code"]
    # «Начать демо заново» не меняет ссылку — QR на слайде остаётся рабочим
    info2 = client.post("/api/v1/demo/reset", params={"user_id": owner}).json()
    assert client.post(f"/api/v1/classes/{info2['class_id']}/invite",
                       params={"user_id": owner}).json()["code"] == code
    # Зал больше свободных учеников: каждый, кто отсканировал, становится родителем
    joined = set()
    for i in range(16):
        r = client.post("/api/v1/parent/join", params={"user_id": owner + 100 + i},
                        json={"code": code, "phone": ""}).json()
        assert r["status"] == "linked", r
        joined.add(r["children"][0])
    assert len(joined) == 16
    exc_id = info2["excursion_ids"][0]
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": owner + 115}).json()
    trip = next(t for t in ctx["children"][0]["excursions"] if t["excursion_id"] == exc_id)
    assert trip["consent_status"] == "PENDING"


@pytest.mark.asyncio
async def test_FIN_22_bot_asks_terms_before_first_answer(client: TestClient) -> None:
    owner = 7_700_900
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id, sid = info["excursion_ids"][0], info["child_student_id"]
    fake = FakeClient()
    bot = BotService(client=fake)

    def press(payload: str, cb: str) -> dict:
        return {"update_type": "message_callback", "callback": {
            "callback_id": cb, "payload": payload, "user": {"user_id": owner}},
            "message": {"recipient": {"chat_id": 1}}}

    def status() -> str:
        with Session(engine) as s:
            return next(p for p in s.get(Excursion, exc_id).participants if p.student_id == sid).consent_status.value

    await bot.handle_update(press(f"consent:{exc_id}:{sid}:APPROVED", "a"))
    assert "Шаг 1 из 2" in fake.answers[-1]["text"] and status() == "PENDING"
    await bot.handle_update(press(f"terms:1:{exc_id}:{sid}:APPROVED", "b"))
    assert "Шаг 2 из 2" in fake.answers[-1]["text"] and status() == "PENDING"
    await bot.handle_update(press(f"terms:2:{exc_id}:{sid}:APPROVED", "c"))
    assert status() == "APPROVED" and "идёт на выезд" in fake.answers[-1]["text"]
    assert client.get("/api/v1/me", params={"user_id": owner}).json()["terms_accepted"] is True


@pytest.mark.asyncio
async def test_FIN_23_bot_paper_choice_answers(client: TestClient) -> None:
    owner = 7_701_000
    info = client.post("/api/v1/demo/start", params={"user_id": owner}).json()
    exc_id, sid = info["excursion_ids"][0], info["child_student_id"]
    fake = FakeClient()
    await BotService(client=fake).handle_update({"update_type": "message_callback", "callback": {
        "callback_id": "p", "payload": f"paper:{exc_id}:{sid}", "user": {"user_id": owner}},
        "message": {"recipient": {"chat_id": 1}}})
    assert "на бумаге" in fake.answers[-1]["text"]
