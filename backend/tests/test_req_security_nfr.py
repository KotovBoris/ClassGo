"""Требования SEC-*, NFR-* (docs/REQUIREMENTS.md).

Важно: эти тесты НЕ содержат фрагментов реального секрета — иначе проверка «секрета нет»
сама бы его занесла в репозиторий. Проверяем свойства: .env не под контролем git и ни в одном
отслеживаемом файле нет непустого значения MAX_BOT_TOKEN.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import make_excursion

REPO = Path(__file__).resolve().parents[2]  # .../classgo


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
    return [f for f in out.stdout.splitlines() if f]


def test_SEC_1_env_not_tracked_and_no_token_values() -> None:
    tracked = _tracked_files()
    assert ".env" not in tracked, ".env не должен быть под контролем git"
    offenders = []
    # Тесты/примеры по определению используют фиктивные токены — их не считаем секретами.
    skip = ("tests/", "test_", ".env.example", "README", "docs/")
    for rel in tracked:
        if Path(rel).name in {".env", ".env.local"}:
            offenders.append(rel)
            continue
        if any(s in rel for s in skip):
            continue
        p = REPO / rel
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        # строки вида MAX_BOT_TOKEN=<непустое> или OTHER_TOKEN=<непустое> в трекнутых файлах
        for line in text.splitlines():
            m = re.match(r"\s*[A-Z0-9_]*TOKEN\s*=\s*(\S+)", line)
            if m and m.group(1).strip():
                offenders.append(f"{rel}: {line.strip()[:40]}")
    assert not offenders, f"секреты в отслеживаемых файлах: {offenders}"


def test_SEC_2_env_ignored() -> None:
    gi = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^\.env$|^\.env\b", gi, re.M), ".env должен быть в .gitignore"


def test_SEC_3_env_example_without_secrets() -> None:
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "MAX_BOT_TOKEN=" in example
    token_line = next(l for l in example.splitlines() if l.startswith("MAX_BOT_TOKEN="))
    assert token_line.strip() == "MAX_BOT_TOKEN=", "в .env.example токена быть не должно"


def test_SEC_4_token_from_env_only() -> None:
    # В исходниках нет длинных литералов-токенов рядом с *TOKEN* — только чтение настроек.
    hexish = re.compile(r"[A-Za-z0-9_\-]{40,}")
    for f in (REPO / "backend" / "app").rglob("*.py"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if "TOKEN" in line and hexish.search(line) and "=" in line:
                # допустимо: пустое/дефолтное значение, os.getenv, Settings-поле
                if any(k in line for k in ("getenv", "Field", "Settings", '""', "': '", "=")):
                    value = line.split("=", 1)[-1].strip()
                    assert not hexish.match(value.strip(" \"'")), f"похоже на литерал токена: {f}:{line.strip()[:50]}"
    cfg = (REPO / "backend" / "app" / "config.py").read_text(encoding="utf-8")
    assert "BaseSettings" in cfg or "getenv" in cfg


def test_SEC_5_mock_data_declared(client: TestClient) -> None:
    meta = client.get("/api/v1/meta").json()
    assert meta["dataset"]["is_mock"] is True
    events = client.get("/api/v1/culture-events").json()
    assert all(e["source"] for e in events)


def test_SEC_6_errors_have_detail_no_traceback(client: TestClient) -> None:
    r = client.get("/api/v1/excursions/999999/dashboard")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
    assert "Traceback" not in r.text


def test_SEC_7_dependencies_pinned() -> None:
    req = (REPO / "backend" / "requirements.txt").read_text(encoding="utf-8")
    pinned = [l for l in req.splitlines() if l.strip() and not l.startswith("#")]
    assert all("==" in l for l in pinned), "все зависимости должны быть с точной версией"
    pkg = (REPO / "miniapp" / "package.json").read_text(encoding="utf-8")
    assert '"react"' in pkg


# --------------------------------------------------------------- NFR
def test_NFR_3_repeat_scenario_stable(client: TestClient, first_class) -> None:
    for _ in range(2):
        exc = make_excursion(client, first_class)
        for s in first_class["students"][:3]:
            client.post(f"/api/v1/excursions/{exc['id']}/consent",
                        json={"student_id": s["id"], "status": "APPROVED"})
        assert client.get(f"/api/v1/excursions/{exc['id']}/dashboard").status_code == 200


def test_NFR_5_openapi_paths_reachable(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    # все GET-пути без параметров должны отвечать не 404/405
    checked = 0
    for path, ops in spec["paths"].items():
        if "{" in path or "get" not in ops:
            continue
        r = client.get(path)
        assert r.status_code not in (404, 405), f"{path} -> {r.status_code}"
        checked += 1
    assert checked >= 5
