"""Требования VAL-* (docs/REQUIREMENTS.md): серверная валидация initData MAX Bridge.

Алгоритм: https://dev.max.ru/docs/webapps/validation
"""
from __future__ import annotations

import json
import urllib.parse

from fastapi.testclient import TestClient

from app.max_validate import build_signature_for_test, is_fresh, validate_webapp_data

TOKEN = "test-bot-token"


def _init_data(pairs: dict[str, str], token: str = TOKEN, break_hash: bool = False) -> str:
    data = dict(pairs)
    data["hash"] = build_signature_for_test(pairs, token)
    if break_hash:
        data["hash"] = "0" * 64
    return "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in data.items())


def test_VAL_1_valid_signature() -> None:
    user = json.dumps({"id": 42, "first_name": "Иван"}, separators=(",", ":"))
    raw = _init_data({"user": user, "auth_date": "1700000000", "query_id": "abc"})
    valid, fields = validate_webapp_data(raw, TOKEN)
    assert valid is True
    assert fields["user"]["id"] == 42


def test_VAL_2_tampered_user_invalid() -> None:
    good = _init_data({"user": json.dumps({"id": 42}), "auth_date": "1700000000"})
    tampered = good.replace(urllib.parse.quote(json.dumps({"id": 42}), safe=""),
                            urllib.parse.quote(json.dumps({"id": 999}), safe=""))
    valid, _ = validate_webapp_data(tampered, TOKEN)
    assert valid is False


def test_VAL_3_wrong_token_invalid() -> None:
    raw = _init_data({"user": json.dumps({"id": 1}), "auth_date": "1700000000"})
    valid, _ = validate_webapp_data(raw, "other-token")
    assert valid is False


def test_VAL_4_missing_or_duplicate_hash() -> None:
    assert validate_webapp_data("user=%7B%7D", TOKEN)[0] is False           # нет hash
    dup = "user=%7B%7D&hash=aa&hash=bb"
    assert validate_webapp_data(dup, TOKEN)[0] is False                    # hash дважды


def test_VAL_5_empty_input() -> None:
    assert validate_webapp_data("", TOKEN)[0] is False
    assert validate_webapp_data("user=%7B%7D", "")[0] is False


def test_VAL_6_webappdata_url_fragment() -> None:
    user = json.dumps({"id": 7}, separators=(",", ":"))
    inner = _init_data({"user": user, "auth_date": "1700000000"})
    url = f"https://example.com#WebAppData={urllib.parse.quote(inner, safe='')}&WebAppPlatform=web"
    valid, fields = validate_webapp_data(url, TOKEN)
    assert valid is True and fields["user"]["id"] == 7


def test_VAL_7_freshness() -> None:
    import time  # noqa: PLC0415

    assert is_fresh(int(time.time())) is True
    assert is_fresh(int(time.time()) - 7200) is False
    assert is_fresh(None) is False


def test_VAL_8_endpoint_without_token(client: TestClient) -> None:
    # в тестовом окружении MAX_BOT_TOKEN пуст -> reason
    r = client.post("/api/v1/max/validate-init-data", json={"init_data": "user=%7B%7D&hash=x"})
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
