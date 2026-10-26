"""Время школы, а не Москвы.

В БД всё хранится в UTC без зоны (как datetime.utcnow()). Людям показываем местное время
школы: выезд проходит там, «сбор в 09:30» — это 09:30 по часам школы. Часовой пояс — у класса
(берётся из телефона учителя при создании класса) и копируется в выезд. Тихие часы
напоминаний считаем по поясу родителя, если он известен (мини-приложение присылает пояс
телефона), иначе по поясу школы.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Europe/Moscow"
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]

_CITY = {
    "Europe/Kaliningrad": "Калининград", "Europe/Moscow": "Москва", "Europe/Simferopol": "Москва",
    "Europe/Kirov": "Москва", "Europe/Volgograd": "Москва", "Europe/Samara": "Самара",
    "Europe/Ulyanovsk": "Ульяновск", "Europe/Saratov": "Саратов", "Europe/Astrakhan": "Астрахань",
    "Asia/Yekaterinburg": "Екатеринбург", "Asia/Omsk": "Омск", "Asia/Novosibirsk": "Новосибирск",
    "Asia/Barnaul": "Барнаул", "Asia/Tomsk": "Томск", "Asia/Novokuznetsk": "Новокузнецк",
    "Asia/Krasnoyarsk": "Красноярск", "Asia/Irkutsk": "Иркутск", "Asia/Chita": "Чита",
    "Asia/Yakutsk": "Якутск", "Asia/Khandyga": "Якутск", "Asia/Vladivostok": "Владивосток",
    "Asia/Ust-Nera": "Владивосток", "Asia/Sakhalin": "Сахалин", "Asia/Magadan": "Магадан",
    "Asia/Srednekolymsk": "Среднеколымск", "Asia/Kamchatka": "Камчатка", "Asia/Anadyr": "Анадырь",
}


def zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def valid_tz(name: str | None) -> str:
    """Имя пояса из браузера, если оно настоящее; иначе Москва."""
    if not name or len(name) > 64:
        return DEFAULT_TZ
    try:
        ZoneInfo(name)
        return name
    except (ZoneInfoNotFoundError, ValueError):
        return DEFAULT_TZ


def to_local(value: datetime, tz: str | None) -> datetime:
    """UTC (без зоны) → местное время школы (без зоны)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone(tz)).replace(tzinfo=None)


def local_to_utc(value: datetime, tz: str | None) -> datetime:
    """Местное время (без зоны) → UTC (без зоны). Время с зоной просто переводится в UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=zone(tz))
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def now_local(tz: str | None, now: datetime | None = None) -> datetime:
    return to_local(now or datetime.utcnow(), tz)


def stamp(value: datetime | None, tz: str | None) -> str:
    """«24.10 в 18:05» по времени школы."""
    if not value:
        return ""
    return to_local(value, tz).strftime("%d.%m в %H:%M")


def human_deadline(value: datetime | None, tz: str | None) -> str:
    """«27 октября, 18:00» по времени школы."""
    if not value:
        return ""
    local = to_local(value, tz)
    return f"{local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def starts_at_utc(event_date: date | None, start: time | None, tz: str | None) -> datetime | None:
    if not event_date:
        return None
    return local_to_utc(datetime.combine(event_date, start or time.max), tz)


def label(tz: str | None) -> str:
    """«Екатеринбург, UTC+5» — подпись к времени в документах."""
    z = zone(tz)
    offset = datetime.now(z).utcoffset()
    hours = int(offset.total_seconds() // 3600) if offset is not None else 3
    city = _CITY.get(str(z.key), str(z.key))
    return f"{city}, UTC{'+' if hours >= 0 else '−'}{abs(hours)}"
