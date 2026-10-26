"""Кто делает запрос.

Внутри MAX мини-приложение передаёт подписанный initData в заголовке
``X-Max-Init-Data``: подпись проверяется токеном бота, и user_id берётся из неё —
подменить его нельзя.

Строгий режим (боевой стенд: включён бот или MAX_VALIDATE_INIT_DATA) — личность
только из свежего подписанного initData; параметр ``?user_id`` и поля тела запроса
игнорируются, без подписи пользователь анонимный. Локально и в тестах (бот выключен)
действует демо-режим: user_id из параметра запроса.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, Query, Request
from sqlmodel import Session, select

from .config import get_settings
from .max_validate import validate_webapp_data
from .timeutil import valid_tz
from .models import UserProfile

INIT_DATA_HEADER = "X-Max-Init-Data"


def strict_auth() -> bool:
    """Боевой режим: принимаем только подписанных пользователей MAX."""
    settings = get_settings()
    return bool(settings.MAX_VALIDATE_INIT_DATA or settings.bot_enabled)


@dataclass
class Caller:
    user_id: int | None
    verified: bool
    first_name: str = ""
    last_name: str = ""
    timezone: str = ""  # пояс телефона из заголовка X-Timezone

    @property
    def auth(self) -> str:
        if self.verified:
            return "max"
        return "demo" if self.user_id else "anonymous"

    @property
    def display_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


def _fresh(auth_date: int | None, max_age: int) -> bool:
    if not auth_date:
        return False
    seconds = auth_date / 1000 if auth_date > 10**11 else auth_date  # MAX может прислать миллисекунды
    return -300 <= time.time() - seconds <= max_age


def caller_from_request(request: Request, user_id: int | None) -> Caller:
    settings = get_settings()
    init_data = request.headers.get(INIT_DATA_HEADER, "")
    if init_data:
        valid, fields = validate_webapp_data(init_data, settings.MAX_BOT_TOKEN)
        user = fields.get("user") or {}
        if valid and user.get("id"):
            if strict_auth() and not _fresh(fields.get("auth_date"), settings.INIT_DATA_MAX_AGE_SECONDS):
                raise HTTPException(status_code=401, detail="Сессия устарела. Закройте и снова откройте ClassGo в MAX.")
            return Caller(
                user_id=int(user["id"]),
                verified=True,
                first_name=str(user.get("first_name") or ""),
                last_name=str(user.get("last_name") or ""),
            )
        if strict_auth():
            raise HTTPException(status_code=401, detail="Не удалось проверить вход. Закройте и снова откройте ClassGo в MAX.")
    if strict_auth():
        return Caller(user_id=None, verified=False)
    return Caller(user_id=user_id, verified=False)


def get_caller(request: Request, user_id: int | None = Query(default=None)) -> Caller:
    """FastAPI-зависимость: проверенный пользователь MAX (или демо-user_id вне строгого режима)."""
    caller = caller_from_request(request, user_id)
    caller.timezone = request.headers.get("X-Timezone", "")[:64]
    return caller


def require_user(caller: Caller) -> int:
    if not caller.user_id:
        raise HTTPException(status_code=401, detail="Откройте ClassGo в MAX")
    return caller.user_id


def remember_profile(session: Session, caller: Caller) -> UserProfile | None:
    if not caller.user_id:
        return None
    profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == caller.user_id)).first()
    if profile is None:
        profile = UserProfile(max_user_id=caller.user_id)
    if caller.first_name:
        profile.first_name = caller.first_name
        profile.last_name = caller.last_name
    if caller.timezone and valid_tz(caller.timezone) == caller.timezone:
        profile.timezone = caller.timezone
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def upsert_profile_from_bot(session: Session, user: dict) -> None:
    """Имя из апдейта бота (bot_started/message) — чтобы обращаться к человеку по имени."""
    uid = user.get("user_id")
    if not uid:
        return
    profile = session.exec(select(UserProfile).where(UserProfile.max_user_id == uid)).first()
    if profile is None:
        profile = UserProfile(max_user_id=uid)
    name = str(user.get("first_name") or user.get("name") or "")
    if name:
        profile.first_name = name
        profile.last_name = str(user.get("last_name") or "")
    session.add(profile)
    session.commit()
