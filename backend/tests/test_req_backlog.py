from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import services
from app.bot import BotService
from app.db import engine
from app.models import Excursion, ExcursionParticipant, ParentContact, SchoolClass, Student

from conftest import make_excursion
from test_req_bot import FakeClient, _callback, _message

TEACHER_A = 111001
TEACHER_B = 111002


def _new_class(client: TestClient, user_id: int = TEACHER_A, **extra) -> dict:
    body = {
        "grade": "7",
        "letter": "В",
        "teacher_name": "Иванова А.А.",
        "user_id": user_id,
        "students": [
            {"full_name": "Тестов Тест Тестович", "parent_phone": "+79005550001", "parent_name": "Мама Тестова"},
            {"full_name": "Второв Втор Вторович", "parent_phone": "+79005550002"},
        ],
    }
    body.update(extra)
    r = client.post("/api/v1/classes", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_SCH_1_create_and_search(client: TestClient) -> None:
    r = client.post("/api/v1/schools", json={"name": "МБОУ «Лицей №12»", "city": "Казань",
                                             "number": "12", "user_id": TEACHER_A})
    assert r.status_code == 201
    school = r.json()
    found = client.get("/api/v1/schools", params={"query": "лицей"}).json()
    assert any(s["id"] == school["id"] for s in found)


def test_SCH_2_create_idempotent_by_name(client: TestClient) -> None:
    a = client.post("/api/v1/schools", json={"name": "МБОУ «СОШ №3»", "city": "Казань"}).json()
    b = client.post("/api/v1/schools", json={"name": "МБОУ «СОШ №3»", "city": "Казань"}).json()
    assert a["id"] == b["id"]


def test_SCH_3_share_requires_rights(client: TestClient) -> None:
    school = client.post("/api/v1/schools", json={"name": "МБОУ «СОШ №4»", "user_id": TEACHER_A}).json()
    r = client.post(f"/api/v1/schools/{school['id']}/share",
                    params={"user_id": TEACHER_B}, json={"user_id": TEACHER_B, "role": "EDIT"})
    assert r.status_code == 403
    r = client.post(f"/api/v1/schools/{school['id']}/share",
                    params={"user_id": TEACHER_A}, json={"user_id": TEACHER_B, "role": "EDIT"})
    assert r.status_code == 200


def test_CLS_1_manual_create_with_students(client: TestClient) -> None:
    klass = _new_class(client)
    assert klass["title"] == "7В"
    assert len(klass["students"]) == 2
    assert klass["students"][0]["parents"][0]["confirmed"] is False


def test_CLS_2_patch_chat_and_school(client: TestClient) -> None:
    school = client.post("/api/v1/schools", json={"name": "МБОУ «СОШ №5»", "number": "5"}).json()
    klass = _new_class(client)
    r = client.patch(f"/api/v1/classes/{klass['id']}",
                     json={"chat_id": 777123, "school_id": school["id"], "user_id": TEACHER_A})
    assert r.status_code == 200
    body = r.json()
    assert body["chat_id"] == 777123 and body["school_id"] == school["id"]
    assert body["school_name"] == "МБОУ «СОШ №5»"


def test_CLS_3_edit_forbidden_for_stranger(client: TestClient) -> None:
    klass = _new_class(client)
    r = client.patch(f"/api/v1/classes/{klass['id']}", json={"letter": "Х", "user_id": TEACHER_B})
    assert r.status_code == 403


def test_CLS_4_share_grants_edit(client: TestClient) -> None:
    klass = _new_class(client)
    r = client.post(f"/api/v1/classes/{klass['id']}/share",
                    params={"user_id": TEACHER_A}, json={"user_id": TEACHER_B, "role": "EDIT"})
    assert r.status_code == 200
    r = client.patch(f"/api/v1/classes/{klass['id']}", json={"letter": "Г", "user_id": TEACHER_B})
    assert r.status_code == 200 and r.json()["title"] == "7Г"


def test_CLS_5_list_shared_but_edit_scoped(client: TestClient) -> None:
    # Учительский интерфейс общий: список классов виден всем пользователям,
    # но редактировать чужой класс нельзя (can_edit только у владельца/пошаренных).
    klass = _new_class(client)
    mine = client.get("/api/v1/classes", params={"user_id": TEACHER_A}).json()
    row_mine = next(c for c in mine if c["id"] == klass["id"])
    assert row_mine["can_edit"] is True
    other = client.get("/api/v1/classes", params={"user_id": 999888}).json()
    row_other = next(c for c in other if c["id"] == klass["id"])
    assert row_other["can_edit"] is False


def test_CLS_6_add_student_joins_existing_excursions(client: TestClient) -> None:
    klass = _new_class(client)
    exc = make_excursion(client, klass)
    r = client.post(f"/api/v1/classes/{klass['id']}/students",
                    params={"user_id": TEACHER_A},
                    json={"full_name": "Новиков Новик Новикович", "parent_phone": "+79005550003"})
    assert r.status_code == 201
    sid = r.json()["id"]
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard", params={"user_id": TEACHER_A}).json()
    assert any(p["student_id"] == sid for p in dash["participants"])


def test_CLS_7_remove_student(client: TestClient) -> None:
    klass = _new_class(client)
    sid = klass["students"][0]["id"]
    r = client.delete(f"/api/v1/classes/{klass['id']}/students/{sid}", params={"user_id": TEACHER_A})
    assert r.status_code == 200
    roster = client.get(f"/api/v1/classes/{klass['id']}/roster", params={"user_id": TEACHER_A}).json()
    assert not any(s["id"] == sid for s in roster["students"])


def test_PRNT_1_confirm_link(client: TestClient) -> None:
    klass = _new_class(client)
    sid = klass["students"][0]["id"]
    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777001
        s.add(parent)
        s.commit()
    r = client.post("/api/v1/parent/confirm-link",
                    json={"student_id": sid, "max_user_id": 777001, "accept": True})
    assert r.status_code == 200 and r.json()["confirmed"] is True
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": 777001}).json()
    assert ctx["found"] and ctx["children"][0]["confirmed"] is True


def test_PRNT_2_decline_link_unbinds(client: TestClient) -> None:
    klass = _new_class(client)
    sid = klass["students"][1]["id"]
    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777002
        s.add(parent)
        s.commit()
    r = client.post("/api/v1/parent/confirm-link",
                    json={"student_id": sid, "max_user_id": 777002, "accept": False})
    assert r.status_code == 200 and r.json()["linked"] is False
    ctx = client.get("/api/v1/parent/context", params={"max_user_id": 777002}).json()
    assert not ctx["found"]


def test_PRNT_3_opt_out_excludes_from_reminders(client: TestClient) -> None:
    klass = _new_class(client)
    exc_body = make_excursion(client, klass)
    sid = klass["students"][0]["id"]
    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777003
        parent.confirmed = True
        s.add(parent)
        s.commit()
    r = client.post("/api/v1/parent/notifications", json={"max_user_id": 777003, "enabled": False})
    assert r.status_code == 200 and r.json()["affected"] == 1
    with Session(engine) as s:
        exc = s.get(Excursion, exc_body["id"])
        targets = services.remind_targets(s, exc)
    row = next(t for t in targets if t["student_id"] == sid)
    assert row["max_user_id"] is None


def test_PRNT_4_second_parent_notified(client: TestClient) -> None:
    with Session(engine) as s:
        two_parents = None
        for st in s.exec(select(Student)).all():
            parents = s.exec(select(ParentContact).where(ParentContact.student_id == st.id)).all()
            if len(parents) >= 2:
                two_parents = (st, parents)
                break
        assert two_parents, "в демо-данных нет ученика с двумя родителями"
        student, parents = two_parents
        parents[1].max_user_id = 777004
        parents[1].confirmed = True
        parents[1].notifications_enabled = True
        s.add(parents[1])
        s.commit()
        klass = s.get(SchoolClass, student.class_id)
    exc = make_excursion(client, {"id": klass.id})
    r = client.post(f"/api/v1/excursions/{exc['id']}/consent",
                    json={"student_id": student.id, "status": "APPROVED",
                          "parent_name": "Мама", "parent_phone": "+79001234501"})
    assert r.status_code == 200 and r.json()["changed"] is True


def test_STAT_1_dashboard_has_bot_status(client: TestClient, first_class) -> None:
    exc = make_excursion(client, first_class)
    dash = client.get(f"/api/v1/excursions/{exc['id']}/dashboard").json()
    row = dash["participants"][0]
    assert "bot_activated" in row and "parent_status" in row
    assert row["parent_status"] in ("APPROVED", "REJECTED", "NO_ANSWER", "BOT_INACTIVE")


def test_STAT_2_tag_unactivated_requires_chat(client: TestClient) -> None:
    klass = _new_class(client)
    exc = make_excursion(client, klass)
    r = client.post(f"/api/v1/excursions/{exc['id']}/tag-unactivated", params={"user_id": TEACHER_A})
    assert r.status_code == 400


def test_STAT_3_tag_unactivated_with_chat(client: TestClient) -> None:
    klass = _new_class(client)
    client.patch(f"/api/v1/classes/{klass['id']}", json={"chat_id": 555777, "user_id": TEACHER_A})
    exc = make_excursion(client, klass)
    r = client.post(f"/api/v1/excursions/{exc['id']}/tag-unactivated", params={"user_id": TEACHER_A})
    assert r.status_code == 200
    body = r.json()
    assert body["tagged"] >= 1 and body["names"]


def test_STAT_4_publish_uses_class_chat(client: TestClient) -> None:
    klass = _new_class(client)
    client.patch(f"/api/v1/classes/{klass['id']}", json={"chat_id": 555778, "user_id": TEACHER_A})
    exc = make_excursion(client, klass)
    r = client.post(f"/api/v1/excursions/{exc['id']}/publish", params={"user_id": TEACHER_A})
    assert r.status_code == 200 and r.json()["chat_id"] == 555778


def test_STAT_5_publish_without_chat_400(client: TestClient) -> None:
    klass = _new_class(client)
    exc = make_excursion(client, klass)
    r = client.post(f"/api/v1/excursions/{exc['id']}/publish", params={"user_id": TEACHER_A})
    assert r.status_code == 400


def _daytime_utc() -> datetime:
    """Полдень по Москве сегодня — вне «тихих часов» напоминаний."""
    return datetime.utcnow().replace(hour=9, minute=0, second=0, microsecond=0)


def test_REM_1_auto_reminder_kinds(client: TestClient) -> None:
    klass = _new_class(client)
    now = _daytime_utc()
    exc_body = make_excursion(client, klass, deadline=(now + timedelta(hours=20)).isoformat())
    sid = klass["students"][0]["id"]
    with Session(engine) as s:
        exc = s.get(Excursion, exc_body["id"])
        exc.created_at = now - timedelta(hours=7)
        exc.deadline = now + timedelta(hours=20)
        s.add(exc)
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777010
        parent.confirmed = True
        s.add(parent)
        s.commit()
        due = services.due_auto_reminders(s, now=now)
        mine = [d for d in due if d["excursion"].id == exc_body["id"] and d["student_id"] == sid]
        # Из подходящих ступеней (72 ч и 24 ч) уходит только самая срочная — без пачки сообщений.
        assert {d["kind"] for d in mine} == {"H24"}
        services.mark_reminder_sent(s, exc_body["id"], sid, "H24")
        due2 = services.due_auto_reminders(s, now=now)
        assert not [d for d in due2 if d["excursion"].id == exc_body["id"] and d["student_id"] == sid]
        # Через 8,5 часа (до тихих часов) наступает ступень «12 часов до срока»
        due3 = services.due_auto_reminders(s, now=now + timedelta(hours=8, minutes=30))
        assert {d["kind"] for d in due3 if d["excursion"].id == exc_body["id"] and d["student_id"] == sid} == {"H12"}


def test_REM_3_fresh_invite_and_quiet_hours(client: TestClient) -> None:
    klass = _new_class(client)
    now = _daytime_utc()
    exc_body = make_excursion(client, klass, deadline=(now + timedelta(hours=20)).isoformat())
    sid = klass["students"][0]["id"]
    with Session(engine) as s:
        exc = s.get(Excursion, exc_body["id"])
        exc.created_at = now - timedelta(hours=1)  # приглашение пришло час назад
        exc.deadline = now + timedelta(hours=20)
        s.add(exc)
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777011
        s.add(parent)
        s.commit()
        assert not [d for d in services.due_auto_reminders(s, now=now) if d["excursion"].id == exc_body["id"]]
        night = now.replace(hour=20)  # 23:00 по Москве
        exc.created_at = now - timedelta(days=1)
        s.add(exc)
        s.commit()
        assert services.due_auto_reminders(s, now=night) == []


def test_REM_2_no_reminders_after_deadline(client: TestClient) -> None:
    klass = _new_class(client)
    deadline = datetime.utcnow() - timedelta(hours=1)
    exc_body = make_excursion(client, klass, deadline=deadline.isoformat())
    with Session(engine) as s:
        due = services.due_auto_reminders(s)
    assert not [d for d in due if d["excursion"].id == exc_body["id"]]


@pytest.mark.asyncio
async def test_BOTX_1_mute_command() -> None:
    with Session(engine) as s:
        parent = s.exec(select(ParentContact)).first()
        parent.max_user_id = 777020
        s.add(parent)
        s.commit()
        pid = parent.id
    fake = FakeClient()
    await BotService(client=fake).handle_update(_message("/mute", user_id=777020))
    with Session(engine) as s:
        assert s.get(ParentContact, pid).notifications_enabled is False
    await BotService(client=fake).handle_update(_message("/unmute", user_id=777020))
    with Session(engine) as s:
        assert s.get(ParentContact, pid).notifications_enabled is True


@pytest.mark.asyncio
async def test_BOTX_2_plink_confirm_callback(client: TestClient) -> None:
    klass = _new_class(client)
    sid = klass["students"][0]["id"]
    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        parent.max_user_id = 777021
        s.add(parent)
        s.commit()
    fake = FakeClient()
    await BotService(client=fake).handle_update(_callback(f"plink:{sid}:YES", user_id=777021))
    with Session(engine) as s:
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == sid)).first()
        assert parent.confirmed is True


@pytest.mark.asyncio
async def test_BOTX_3_consent_notifies_other_parent(client: TestClient) -> None:
    with Session(engine) as s:
        target = None
        for st in s.exec(select(Student)).all():
            parents = s.exec(select(ParentContact).where(ParentContact.student_id == st.id)).all()
            if len(parents) >= 2:
                target = (st, parents)
                break
        assert target
        student, parents = target
        parents[0].max_user_id = 777030
        parents[1].max_user_id = 777031
        parents[1].confirmed = True
        parents[1].notifications_enabled = True
        s.add(parents[0])
        s.add(parents[1])
        s.commit()
        klass_id = student.class_id
        exc = Excursion(class_id=klass_id, title="Проверка уведомления")
        s.add(exc)
        s.commit()
        s.refresh(exc)
        s.add(ExcursionParticipant(excursion_id=exc.id, student_id=student.id, consent_status="PENDING"))
        s.commit()
        exc_id, student_id = exc.id, student.id
    fake = FakeClient()
    BotService._accept_terms(777030)
    await BotService(client=fake).handle_update(
        _callback(f"consent:{exc_id}:{student_id}:APPROVED", user_id=777030)
    )
    notified = [m for m in fake.sent if m.get("user_id") == 777031]
    assert notified and "подписано согласие" in notified[-1]["text"]
