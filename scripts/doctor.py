#!/usr/bin/env python3
"""«Доктор» интеграции с MAX: самодиагностика и подсказка по восстановлению.

Проверяет по порядку:
  1. доступность домена MAX;
  2. валидность токена (GET /me);
  3. TLS-доверие (сертификаты Минцифры) — самая частая причина сбоя в контейнере;
  4. при проблеме TLS печатает, что именно сделать.

Запуск:  python3 scripts/doctor.py
Токен берётся из .env (переменная MAX_BOT_TOKEN) или из аргумента.
"""
from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip())
    return env


def main() -> int:
    env = load_env()
    token = sys.argv[1] if len(sys.argv) > 1 else env.get("MAX_BOT_TOKEN", "")
    base = env.get("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")
    ca = env.get("MAX_CA_BUNDLE", "")
    insecure = env.get("MAX_TLS_INSECURE", "0").lower() in ("1", "true", "yes")

    print("── Диагностика интеграции MAX ──")
    print(f"домен API: {base}")
    print(f"токен: {'задан' if token else 'НЕ ЗАДАН'}")
    print(f"CA bundle: {ca or '(системный)'} | insecure: {insecure}")
    if not token:
        print("❌ Нет MAX_BOT_TOKEN. Укажите его в .env (он выдаётся платформой MAX).")
        return 1

    ctx = None
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif ca:
        if not Path(ca).exists():
            print(f"❌ Файл CA bundle не найден: {ca}. Смонтируйте его (./certs:/certs:ro).")
            return 1
        ctx = ssl.create_default_context(cafile=ca)

    req = urllib.request.Request(f"{base}/me", headers={"Authorization": token})
    try:
        opener = urllib.request.urlopen(req, timeout=20, context=ctx) if ctx else urllib.request.urlopen(req, timeout=20)
        import json

        data = json.loads(opener.read())
        print(f"✅ Токен валиден. Бот: «{data.get('name')}» (@{data.get('username')}, id={data.get('user_id')})")
        return 0
    except ssl.SSLCertVerificationError as e:
        print(f"❌ TLS: {e}")
        print("   Это ожидаемо, если корневой сертификат Минцифры не в хранилище контейнера.")
        print("   Решения: 1) положить PEM в ./certs и задать MAX_CA_BUNDLE=/certs/<файл>.pem;")
        print("            2) для локальной демонстрации MAX_TLS_INSECURE=1 (только демо!).")
        return 2
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"❌ Ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
