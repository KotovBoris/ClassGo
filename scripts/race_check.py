#!/usr/bin/env python3
"""Проверка гонок и блокировок записи под нагрузкой (SQLite vs PostgreSQL).

Что делает:
  1. создаёт выезд;
  2. КУЧА параллельных потоков одновременно пишут согласия:
     - A) N параллельных APPROVED одному ученику (конкурентная запись в одну строку);
     - B) смешанные APPROVED/REJECTED одному ученику (гонка «кто последний»);
     - C) параллельные согласия РАЗНЫМ ученикам (массовая параллельная запись);
  3. считает коды ответов и проверяет консистентность (нет 5xx «database is locked»).

Запуск:  python3 scripts/race_check.py [BASE_URL] [N_ПОТОКОВ]
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
TIMEOUT = 60


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, raw.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def parallel(fn, n: int) -> Counter:
    codes: Counter = Counter()
    lock = threading.Lock()

    def worker(i: int):
        code, _ = fn(i)
        with lock:
            codes[code] += 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    dt = time.time() - t0
    print(f"    {n} потоков за {dt:.2f}с → коды: {dict(codes)}")
    return codes


def main() -> int:
    print(f"▶ база под {BASE}, потоков: {N}\n")
    code, health = call("GET", "/healthz")
    if code != 200:
        print(f"!! сервис недоступен: {code} {health}")
        return 1

    # БД, с которой реально работаем
    code, meta = call("GET", "/api/v1/meta")
    print(f"  meta: {json.dumps(meta, ensure_ascii=False)[:120]}...\n")

    classes = call("GET", "/api/v1/classes")[1]
    klass = classes[0]
    students = [s["id"] for s in klass["students"]]
    event = call("GET", "/api/v1/culture-events", )[1][0]

    ok = True

    # --- A) конкурентная запись в ОДНУ строку (все APPROVED) ---
    exc = call("POST", "/api/v1/excursions",
               {"class_id": klass["id"], "culture_event_id": event["id"]})[1]
    eid, sid = exc["id"], students[0]
    print(f"A) {N} параллельных APPROVED одному ученику (student_id={sid})")
    codes = parallel(
        lambda i: call("POST", f"/api/v1/excursions/{eid}/consent",
                       {"student_id": sid, "status": "APPROVED"}), N)
    if any(c == 0 or c >= 500 for c in codes):
        ok = False
        print("    ❌ есть 5xx/ошибки — возможен 'database is locked'")
    d = call("GET", f"/api/v1/excursions/{eid}/dashboard")[1]
    row = next(p for p in d["participants"] if p["student_id"] == sid)
    print(f"    итоговый статус: {row['consent_status']} (ожидаем APPROVED)")
    if row["consent_status"] != "APPROVED":
        ok = False
        print("    ❌ консистентность нарушена")

    # --- B) гонка APPROVED/REJECTED (кто последний) ---
    exc2 = call("POST", "/api/v1/excursions",
                {"class_id": klass["id"], "culture_event_id": event["id"]})[1]
    eid2, sid2 = exc2["id"], students[1]
    print(f"\nB) смешанная гонка APPROVED/REJECTED (student_id={sid2})")
    codes = parallel(
        lambda i: call("POST", f"/api/v1/excursions/{eid2}/consent",
                       {"student_id": sid2,
                        "status": "APPROVED" if i % 2 == 0 else "REJECTED"}), N)
    if any(c == 0 or c >= 500 for c in codes):
        ok = False
        print("    ❌ есть 5xx/ошибки")
    d2 = call("GET", f"/api/v1/excursions/{eid2}/dashboard")[1]
    row2 = next(p for p in d2["participants"] if p["student_id"] == sid2)
    print(f"    итоговый статус: {row2['consent_status']} (какой-то один — это ожидаемо)")
    if row2["consent_status"] not in ("APPROVED", "REJECTED"):
        ok = False
        print("    ❌ статус не определён")

    # --- C) массовая параллельная запись разным ученикам ---
    exc3 = call("POST", "/api/v1/excursions",
                {"class_id": klass["id"], "culture_event_id": event["id"]})[1]
    eid3 = exc3["id"]
    pool = students[: min(N, len(students))]
    print(f"\nC) параллельные согласия {len(pool)} разным ученикам")
    codes = parallel(
        lambda i: call("POST", f"/api/v1/excursions/{eid3}/consent",
                       {"student_id": pool[i % len(pool)], "status": "APPROVED"}), N)
    if any(c == 0 or c >= 500 for c in codes):
        ok = False
        print("    ❌ есть 5xx/ошибки — вероятна блокировка базы")
    d3 = call("GET", f"/api/v1/excursions/{eid3}/dashboard")[1]
    approved = sum(1 for p in d3["participants"] if p["consent_status"] == "APPROVED")
    print(f"    подтверждено в БД: {approved} из {len(pool)}")

    print("\n── Итог: " + ("✅ гонок/блокировок не выявлено" if ok else "❌ есть проблемы") + " ──")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
