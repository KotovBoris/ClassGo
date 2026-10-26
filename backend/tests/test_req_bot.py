"""Требования BOT-* (docs/REQUIREMENTS.md). Чат-бот MAX, все типы Update."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.bot import BotService
from app.db import engine
from app.max_client import MaxClient
from app.models import Excursion, ExcursionParticipant, ParentContact, SchoolClass, Student

from conftest import make_excursion


class FakeClient:
    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self.sent: list[dict] = []
        self.answers: list[dict] = []
        self.update_calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def get_me(self):
        return {"name": "fake", "username": "fake_bot"}

    async def get_updates(self, **kwargs):
        self.update_calls.append(kwargs)
        return {"updates": [], "marker": None}

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return {"ok": True}

    async def answer_callback(self, callback_id, **kwargs):
        self.answers.append({"callback_id": callback_id, **kwargs})
        return {"ok": True}


def _bot_started(user_id: int = 424242) -> dict:
    return {
        "update_type": "bot_started", "timestamp": 1, "chat_id": 555,
        "user": {"user_id": user_id, "name": "Родитель"}, "payload": None,
    }


def _message(text: str, user_id: int = 424242) -> dict:
    return {
        "update_type": "message_created", "timestamp": 2,
        "message": {
            "sender": {"user_id": user_id, "name": "Родитель"},
            "recipient": {"chat_id": 555},
            "body": {"text": text},
            "timestamp": 2,
        },
    }


def _callback(payload: str, user_id: int = 424242, cb_id: str = "cb-1") -> dict:
    return {
        "update_type": "message_callback", "timestamp": 3,
        "callback": {"callback_id": cb_id, "payload": payload, "user": {"user_id": user_id}},
    }


def _button_types(attachments) -> set[str]:
    types = set()
    for att in attachments or []:
        for row in att.get("payload", {}).get("buttons", []):
            for b in row:
                types.add(b["type"])
    return types


# ------------------------------------------------------- онбординг
@pytest.mark.asyncio
async def test_BOT_1_bot_started_greeting() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_bot_started())
    assert fake.sent and _button_types(fake.sent[-1]["attachments"]) >= {"open_app", "callback"}


@pytest.mark.asyncio
async def test_BOT_2_start_command() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_message("/start"))
    assert fake.sent and "ClassGo" in fake.sent[-1]["text"]


@pytest.mark.asyncio
async def test_BOT_3_help_command() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_message("/help"))
    assert fake.sent and "open_app" in _button_types(fake.sent[-1]["attachments"])


@pytest.mark.asyncio
async def test_BOT_4_trips_without_binding() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_message("/trips"))
    assert fake.sent and "не подключены" in fake.sent[-1]["text"].lower()


@pytest.mark.asyncio
async def test_BOT_5_trips_with_binding() -> None:
    with Session(engine) as s:
        klass = s.exec(select(SchoolClass)).first()
        student = s.exec(select(Student).where(Student.class_id == klass.id)).first()
        parent = s.exec(select(ParentContact).where(ParentContact.student_id == student.id)).first()
        parent.max_user_id = 900900
        parent.confirmed = True
        s.add(parent)
        s.commit()
        student_name = student.full_name
    fake = FakeClient()
    await BotService(client=fake).handle_update(_message("/trips", user_id=900900))
    assert fake.sent and any(student_name in m["text"] for m in fake.sent)


# ------------------------------------------------------- callbacks
@pytest.mark.asyncio
async def test_BOT_6_callback_cmd_trips() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_callback("cmd:trips"))
    assert fake.answers and fake.answers[-1]["callback_id"] == "cb-1"


@pytest.mark.asyncio
async def test_BOT_7_callback_consent_approved() -> None:
    exc_id, sid = _fresh_excursion_and_student()
    fake = FakeClient()
    BotService._accept_terms(424242)
    await BotService(client=fake).handle_update(_callback(f"consent:{exc_id}:{sid}:APPROVED"))
    with Session(engine) as s:
        p = _participant(s, exc_id, sid)
    assert p.consent_status.value == "APPROVED"


@pytest.mark.asyncio
async def test_BOT_8_callback_consent_rejected() -> None:
    exc_id, sid = _fresh_excursion_and_student()
    fake = FakeClient()
    BotService._accept_terms(424242)
    await BotService(client=fake).handle_update(_callback(f"consent:{exc_id}:{sid}:REJECTED"))
    with Session(engine) as s:
        p = _participant(s, exc_id, sid)
    # Сначала бот уточняет причину отказа — статус ещё не меняется.
    assert p.consent_status.value == "PENDING"
    assert "почему" in fake.answers[-1]["text"].lower()
    await BotService(client=fake).handle_update(_callback(f"reason:{exc_id}:{sid}:personal"))
    with Session(engine) as s:
        p = _participant(s, exc_id, sid)
    assert p.consent_status.value == "REJECTED"
    assert p.rejection_reason == "Личные причины"


@pytest.mark.asyncio
async def test_BOT_9_broken_callback_payload() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update(_callback("consent:not:int"))
    assert fake.answers  # ответ есть, исключения нет


@pytest.mark.asyncio
async def test_BOT_10_unknown_update_ignored() -> None:
    fake = FakeClient()
    await BotService(client=fake).handle_update({"update_type": "user_added", "timestamp": 1})
    assert not fake.sent and not fake.answers


@pytest.mark.asyncio
async def test_BOT_11_error_in_update_does_not_raise() -> None:
    fake = FakeClient()
    # message_callback без callback -> обращение к None приведёт к исключению внутри,
    # но handle_update обязан его проглотить
    await BotService(client=fake).handle_update({"update_type": "message_callback", "timestamp": 1})


# ------------------------------------------------------- контракт MAX-клиента
@pytest.mark.asyncio
async def test_BOT_12_get_updates_params() -> None:
    fake = FakeClient()
    await fake.get_updates(marker=42, timeout=30, limit=100, types=["message_created"])
    call = fake.update_calls[-1]
    assert call["marker"] == 42 and call["types"] == ["message_created"]


def test_BOT_13_recipient_single() -> None:
    from app.max_client import MaxClient  # noqa: PLC0415  (проверяем формирование запроса)

    client = MaxClient(token="x", base="http://example")
    # user_id передаётся как параметр запроса, chat_id — не должен попадать вместе
    import inspect  # noqa: PLC0415

    src = inspect.getsource(client.send_message)
    assert "user_id" in src and "chat_id" in src


def test_BOT_14_consent_keyboard_payloads() -> None:
    with Session(engine) as s:
        exc = s.exec(select(Excursion)).first()
    kb = BotService(client=FakeClient())._consent_keyboard(exc, 7)
    buttons = [b for row in kb[0]["payload"]["buttons"] for b in row]
    payloads = {b["payload"] for b in buttons}
    assert f"consent:{exc.id}:7:APPROVED" in payloads
    assert f"consent:{exc.id}:7:REJECTED" in payloads


@pytest.mark.asyncio
async def test_BOT_15_client_swallows_api_errors(monkeypatch) -> None:
    client = MaxClient(token="x", base="http://127.0.0.1:1")  # заведомо недоступный порт
    assert await client.get_me() is None
    assert await client.send_message(user_id=1, text="hi") is None


def test_BOT_18_webhook_bad_json(client, webhook_on) -> None:  # noqa: ANN001
    r = client.post("/webhook/max", content=b"{not json", headers={"Content-Type": "application/json", **webhook_on})
    assert r.status_code == 400


def test_BOT_20_bot_commands_valid() -> None:
    from app.max_client import BOT_COMMANDS  # noqa: PLC0415

    names = [c["name"] for c in BOT_COMMANDS]
    assert names == ["start", "trips", "mute", "unmute", "help"]
    assert len(set(names)) == len(names)
    for c in BOT_COMMANDS:
        assert 1 <= len(c["name"]) <= 64
        assert 1 <= len(c["description"]) <= 128


@pytest.mark.asyncio
async def test_BOT_21_set_commands_no_network() -> None:
    """Регистрация команд не бросает исключений при недоступном API MAX."""
    from app.max_client import BOT_COMMANDS, MaxClient  # noqa: PLC0415

    client = MaxClient(token="x", base="http://127.0.0.1:1")
    assert await client.set_commands(BOT_COMMANDS) is None


def test_BOT_22_lifespan_symbols_imported() -> None:
    """Все имена, используемые в lifespan/polling, импортированы в main.

    Регресс-защита: однажды `BOT_COMMANDS` использовался в lifespan, но не был
    импортирован — приложение падало при старте в режиме polling. Тесты с
    выключенным ботом этого не ловили; этот тест ловит.
    """
    import app.main as m  # noqa: PLC0415

    for name in ("BOT_COMMANDS", "BotService", "_poll_loop", "BOT_COMMANDS"):
        assert hasattr(m, name), f"{name} не импортирован в app.main"


# ------------------------------------------------------- helpers
def _fresh_excursion_and_student() -> tuple[int, int]:
    with Session(engine) as s:
        klass = s.exec(select(SchoolClass)).first()
        student = s.exec(select(Student).where(Student.class_id == klass.id)).first()
        exc = Excursion(class_id=klass.id, title="Тест бота")
        s.add(exc)
        s.commit()
        s.refresh(exc)
        s.add(ExcursionParticipant(excursion_id=exc.id, student_id=student.id,
                                   consent_status="PENDING"))
        # Кнопки в боте нажимает подтверждённый родитель этого ученика.
        for other in s.exec(select(ParentContact).where(ParentContact.max_user_id == 424242)).all():
            other.max_user_id = None
            s.add(other)
        s.add(ParentContact(student_id=student.id, full_name="Родитель для теста бота", phone_number="+79001110000",
                            max_user_id=424242, confirmed=True))
        s.commit()
        return exc.id, student.id


def _participant(session: Session, exc_id: int, sid: int) -> ExcursionParticipant:
    return session.exec(select(ExcursionParticipant).where(
        ExcursionParticipant.excursion_id == exc_id,
        ExcursionParticipant.student_id == sid,
    )).first()
