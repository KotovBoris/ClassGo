from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any

DEFAULT_MAX_AGE = 3600


def _extract_web_app_data(url_or_fragment: str) -> str:
    raw = url_or_fragment
    if "#" in raw:
        raw = raw.split("#", 1)[1]
    params = urllib.parse.parse_qs(raw, keep_blank_values=True)
    if "WebAppData" in params:
        return params["WebAppData"][0]
    return url_or_fragment


def validate_webapp_data(app_data: str, bot_token: str) -> tuple[bool, dict[str, Any]]:
    if not app_data or not bot_token:
        return False, {}

    data = _extract_web_app_data(app_data)
    pairs: list[list[str]] = [p.split("=", 1) for p in data.split("&") if "=" in p]

    hashes = [p[1] for p in pairs if p[0] == "hash"]
    if len(hashes) != 1:
        return False, {}
    original_hash = hashes[0]

    decoded = {k: urllib.parse.unquote(v) for k, v in pairs if k != "hash"}

    launch_params = "\n".join(f"{k}={decoded[k]}" for k in sorted(decoded))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()

    valid = hmac.compare_digest(signature, original_hash)

    fields: dict[str, Any] = {}
    if "user" in decoded:
        try:
            fields["user"] = json.loads(decoded["user"])
        except Exception:  # noqa: BLE001
            fields["user"] = None
    if "chat" in decoded:
        try:
            fields["chat"] = json.loads(decoded["chat"])
        except Exception:  # noqa: BLE001
            fields["chat"] = None
    if "auth_date" in decoded:
        try:
            fields["auth_date"] = int(decoded["auth_date"])
        except Exception:  # noqa: BLE001
            fields["auth_date"] = None
    fields["start_param"] = decoded.get("start_param")
    return valid, fields


def verify_phone(auth_date: str | int, phone: str, user_id: int, phone_hash: str, bot_token: str) -> bool:
    """Проверка номера из WebApp.requestContact() (dev.max.ru, «Подключение мини-приложения»).

    hash = HMAC_SHA256(key=токен бота, msg="authDate=…\\nphone=…\\nuserId=…"), номер без «+».
    user_id берётся из уже проверенного initData — так номер нельзя подставить чужой.
    """
    if not (phone_hash and bot_token and phone and user_id):
        return False
    msg = "\n".join([f"authDate={auth_date}", f"phone={str(phone).lstrip('+')}", f"userId={user_id}"])
    calc = hmac.new(bot_token.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calc, str(phone_hash))


def is_fresh(auth_date: int | None, max_age: int = DEFAULT_MAX_AGE) -> bool:
    if not auth_date:
        return False
    return (time.time() - auth_date) <= max_age


def build_signature_for_test(app_data_pairs: dict[str, str], bot_token: str) -> str:
    launch_params = "\n".join(f"{k}={app_data_pairs[k]}" for k in sorted(app_data_pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
