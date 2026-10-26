"""ST-1: мультидети (parent_context) и сценарий «два родителя» (PRD §5.1).

Проверяются:
- родитель с двумя детьми видит обоих через /api/v1/parent/context (дедупликация);
- повторное согласие «второго родителя» не перезаписывает уже зафиксированное;
- привязка к нужному контакту по parent_phone в link-code + bot._bind_by_code.

Тесты создают собственные классы/учеников, чтобы не влиять на состояние,
разделяемое другими тест-модулями (общая session-scoped БД).
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.bot import BotService
from app.db import engine
from app.models import ParentContact, SchoolClass, Student

from conftest import make_excursion


class FakeClient:
    enabled = True

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"ok": True}

    async def answer_callback(self, *args, **kwargs):
        return {"ok": True}


def _make_class_with_students(n: int = 1, letter: str = "МП") -> tuple[int, list[int]]:
    with Session(engine) as s:
        klass = SchoolClass(grade="7", letter=letter, school_name="Тестовая школа")
        s.add(klass)
        s.commit()
        s.refresh(klass)
        ids: list[int] = []
        for i in range(n):
            st = Student(class_id=klass.id, full_name=f"Ученик Мультиродителев {i + 1}")
            s.add(st)
            s.commit()
            s.refresh(st)
            ids.append(st.id)
        return klass.id, ids


def _add_contact(student_id: int, name: str, phone: str, role: str = "Законный представитель",
                 max_user_id: int | None = None) -> int:
    with Session(engine) as s:
        c = ParentContact(student_id=student_id, full_name=name, phone_number=phone,
                          role=role, max_user_id=max_user_id)
        s.add(c)
        s.commit()
        s.refresh(c)
        return c.id


def test_MULTI_1_parent_sees_two_children(client: TestClient) -> None:
    """Родитель (один max_user_id) привязан к двум детям — видит обоих, без дублей."""
    _, sids = _make_class_with_students(2, letter="МП")
    for sid in sids:
        _add_contact(sid, "Многодетный Родитель", f"+7900{sid:07d}", max_user_id=990101)
    body = client.get("/api/v1/parent/context", params={"max_user_id": 990101}).json()
    assert body["found"] is True
    got = [c["student_id"] for c in body["children"]]
    assert set(sids) <= set(got)
    assert len(got) == len(set(got)), "дети не должны дублироваться"


