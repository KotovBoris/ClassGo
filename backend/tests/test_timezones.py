"""Время школы, а не Москвы: срок, начало выезда, тихие часы, документы."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import services, timeutil
from app.bot import human_deadline
from app.db import engine
from app.documents import _collect
from app.models import Excursion

TEACHER = 9_100_001


def _ekb_trip(client: TestClient) -> dict:
    klass = client.post("/api/v1/classes", params={"user_id": TEACHER}, json={
        "grade": "5", "letter": "А", "school_name": "Школа Екатеринбурга", "teacher_name": "Учитель Е. Е.",
        "timezone": "Asia/Yekaterinburg",
        "students": [{"full_name": "Уралов Пётр Ильич", "parent_phone": "+79120000001"}]}).json()
    trip = client.post("/api/v1/excursions", params={"user_id": TEACHER}, json={
        "class_id": klass["id"], "title": "Музей", "event_date": "2026-11-12", "gathering_time": "09:00",
        "deadline": "2026-11-10T18:00:00", "escorts": "Помощник", "notify_parents": False}).json()
    return trip


def test_TZ_1_deadline_entered_in_school_time(client: TestClient) -> None:
    trip = _ekb_trip(client)
    assert trip["timezone"] == "Asia/Yekaterinburg"
    # 18:00 по Екатеринбургу (UTC+5) — это 13:00 UTC
    assert trip["deadline"].startswith("2026-11-10T13:00")
    with Session(engine) as s:
        exc = s.get(Excursion, trip["id"])
        # бот показывает срок по часам школы
        assert human_deadline(exc.deadline, exc.timezone) == "10 ноября, 18:00"


def test_TZ_2_trip_starts_by_school_clock(client: TestClient) -> None:
    trip = _ekb_trip(client)
    with Session(engine) as s:
        exc = s.get(Excursion, trip["id"])
        # Сбор 12.11 в 09:00 по Екатеринбургу = 04:00 UTC
        assert not services.trip_started(exc, now=datetime(2026, 11, 12, 3, 59))
        assert services.trip_started(exc, now=datetime(2026, 11, 12, 4, 0))


def test_TZ_3_quiet_hours_by_parent_clock() -> None:
    evening_utc = datetime(2026, 11, 1, 17, 30)  # 20:30 в Москве, 03:30 во Владивостоке
    assert not services.in_quiet_hours(evening_utc, "Europe/Moscow")
    assert services.in_quiet_hours(evening_utc, "Asia/Vladivostok")
    assert services.in_quiet_hours(datetime(2026, 11, 1, 3, 0), "Europe/Moscow")  # 06:00 в Москве


def test_TZ_4_parent_timezone_from_phone(client: TestClient) -> None:
    uid = 9_100_050
    client.get("/api/v1/me", params={"user_id": uid}, headers={"X-Timezone": "Asia/Vladivostok"})
    with Session(engine) as s:
        assert services.user_timezone(s, uid, "Europe/Moscow") == "Asia/Vladivostok"
        assert services.user_timezone(s, 9_100_051, "Asia/Yekaterinburg") == "Asia/Yekaterinburg"
    # Мусор вместо пояса не сохраняется
    client.get("/api/v1/me", params={"user_id": uid}, headers={"X-Timezone": "Mars/Olympus"})
    with Session(engine) as s:
        assert services.user_timezone(s, uid, "Europe/Moscow") == "Asia/Vladivostok"


def test_TZ_5_documents_say_school_time(client: TestClient) -> None:
    trip = _ekb_trip(client)
    with Session(engine) as s:
        pack = _collect(s, s.get(Excursion, trip["id"]))
    assert pack.tz_label == "Екатеринбург, UTC+5"
    assert pack.deadline == "10.11.2026 18:00"


def test_TZ_6_timeutil_basics() -> None:
    assert timeutil.valid_tz("Asia/Omsk") == "Asia/Omsk"
    assert timeutil.valid_tz("../../etc/passwd") == "Europe/Moscow"
    assert timeutil.starts_at_utc(date(2026, 11, 12), time(9, 0), "Europe/Moscow") == datetime(2026, 11, 12, 6, 0)
    assert timeutil.stamp(datetime(2026, 10, 24, 15, 5), "Europe/Moscow") == "24.10 в 18:05"
    assert timeutil.to_local(datetime(2026, 10, 24, 15, 5), "Asia/Kamchatka") - datetime(2026, 10, 24, 15, 5) \
        == timedelta(hours=12)
