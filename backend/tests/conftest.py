"""Общая обвязка тестов: изолированная БД и клиент приложения.

Переменные окружения выставляются ДО импорта приложения, чтобы engine взял тестовую БД.
Бот MAX принудительно выключен (MAX_BOT_MODE=off) — тесты не ходят во внешнюю сеть.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DIR = Path(tempfile.mkdtemp(prefix="classgo-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DIR / 'test.db'}")
os.environ["MAX_BOT_TOKEN"] = ""
os.environ["MAX_BOT_MODE"] = "off"
os.environ["AUTO_SEED"] = "true"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ["FILES_DIR"] = str(_TMP_DIR / "files")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def session():
    """Сессия БД приложения — для проверок, которые смотрят данные напрямую."""
    from app.db import Session as _Session, engine as _engine

    with _Session(_engine) as s:
        yield s


@pytest.fixture()
def webhook_on(monkeypatch) -> dict:
    """Бот в режиме webhook с секретом; запросы к MAX подменены заглушкой. Возвращает нужные заголовки."""
    from app import max_client
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "MAX_BOT_TOKEN", "test-token")
    monkeypatch.setattr(settings, "MAX_BOT_MODE", "webhook")
    monkeypatch.setattr(settings, "MAX_WEBHOOK_SECRET", "test-secret")

    async def offline(self, *args, **kwargs):
        return None

    monkeypatch.setattr(max_client.MaxClient, "_request", offline)
    monkeypatch.setattr(max_client.MaxClient, "download", offline)
    return {"X-Max-Bot-Api-Secret": "test-secret"}


@pytest.fixture()
def first_class(client: TestClient) -> dict:
    """Демо-класс 8-Б (создаётся сидером при старте)."""
    classes = client.get("/api/v1/classes").json()
    demo = next((c for c in classes if c["title"] == "8Б"), classes[0] if classes else None)
    assert demo, "демо-класс не засеян"
    return demo


@pytest.fixture()
def paid_event(client: TestClient) -> dict:
    events = client.get("/api/v1/culture-events", params={"pushkin": True}).json()
    paid = next((e for e in events if e["price"] > 0), events[0])
    return paid


@pytest.fixture()
def free_event(client: TestClient) -> dict:
    events = client.get("/api/v1/culture-events", params={"free": True}).json()
    assert events, "нет бесплатных событий"
    return events[0]


def make_excursion(client: TestClient, klass: dict, event_id: int | None = None, **extra) -> dict:
    """Хелпер: создать выезд и вернуть его тело."""
    body = {"class_id": klass["id"], "gathering_time": "08:30", "return_time": "14:00"}
    if event_id is not None:
        body["culture_event_id"] = event_id
    else:
        body["title"] = "Тестовый выезд"
    body.update(extra)
    # Выезд создаёт учитель класса (у старых сид-классов владельца нет — тогда без user_id).
    owner = klass.get("owner_user_id")
    r = client.post("/api/v1/excursions", json=body, params={"user_id": owner} if owner else None)
    assert r.status_code == 201, r.text
    return r.json()
