#!/usr/bin/env bash
# ClassGo — выкладка на сервер одной командой.
#
# Что делает:
#   1. Останавливает все уже запущенные контейнеры на машине (docker stop).
#      Контейнеры не удаляет, volume с базой и сертификатом Caddy не трогает.
#      Процесс BeAdmin на порту 8080 не контейнер, скрипт его не останавливает.
#   2. Клонирует или обновляет ветку main (https://github.com/KotovBoris/kultvyezd).
#   3. Копирует уже готовый ~/.env в каталог проекта. Файл в git не попадает
#      и заново не создаётся. Две публичные ссылки приводятся к https://213.193.198.71.
#   4. Пишет Caddyfile и compose.override.yaml. Caddy слушает 80 и 443 и
#      проксирует на мини-приложение. Порт 8080 остаётся у BeAdmin.
#   5. Собирает и поднимает контейнеры (docker compose up -d --build).
#   6. Ждёт ответ сайта по HTTP и по HTTPS.
#   7. Прогоняет pytest в одноразовом контейнере на временной базе.
#      Рабочий файл classgo.db при этом не меняется.
#   8. Прогоняет HTTP-сценарий по уже поднятому сайту.
#      Этот сценарий вызывает POST /api/v1/admin/reset-demo и возвращает
#      демо-данные к исходному виду.
#   9. Оставляет стек запущенным.
#
# Чего скрипт не делает:
#   - не удаляет volume с базой и сертификатом (нет docker compose down -v);
#   - не печатает и не перезаписывает токен в ~/.env.
#
# Куда класть:
#   В домашнюю директорию, не внутрь репозитория:
#     cp scripts/deploy.sh ~/run.sh && chmod +x ~/run.sh
#   Запуск из ~/classgo делает git reset и может оборвать сам скрипт,
#   если эта копия ещё не в origin/main.
#
# Требования на сервере: docker, docker compose, git, curl.
# Запуск:  ~/run.sh

set -euo pipefail

PUBLIC_ORIGIN="https://213.193.198.71"

running="$(docker ps -q)"
if [[ -n "$running" ]]; then
  # shellcheck disable=SC2086
  docker stop $running
fi

ROOT="${CLASSGO_ROOT:-$HOME/classgo}"
ENV_SRC="${CLASSGO_ENV:-$HOME/.env}"
REPO="https://github.com/KotovBoris/kultvyezd.git"
BRANCH="${CLASSGO_BRANCH:-main}"  # ветку можно выкатить: CLASSGO_BRANCH=final-polish ~/run.sh
HEALTH_HTTP="http://127.0.0.1/healthz"
HEALTH_HTTPS="${PUBLIC_ORIGIN}/healthz"

if [[ ! -f "$ENV_SRC" ]]; then
  echo "Нет $ENV_SRC. Положи туда готовый .env и запусти скрипт снова." >&2
  exit 1
fi

if [[ ! -d "$ROOT/.git" ]]; then
  git clone --branch "$BRANCH" "$REPO" "$ROOT"
fi

cd "$ROOT"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

cp "$ENV_SRC" "$ROOT/.env"
# Токен не трогаем. Публичные адреса должны быть https, иначе MAX не откроет приложение.
for env_file in "$ENV_SRC" "$ROOT/.env"; do
  sed -i 's|^MINIAPP_BASE_URL=.*|MINIAPP_BASE_URL='"$PUBLIC_ORIGIN"'|' "$env_file"
  sed -i 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL='"$PUBLIC_ORIGIN"'|' "$env_file"
done

cat > "$ROOT/Caddyfile" << EOF
{
	email spivakovskiy.ge@phystech.edu
	default_sni 213.193.198.71
	auto_https disable_redirects
}

http:// {
	reverse_proxy miniapp:80
}

https://213.193.198.71 {
	tls {
		issuer acme {
			email spivakovskiy.ge@phystech.edu
			profile shortlived
			disable_tlsalpn_challenge
		}
	}
	reverse_proxy miniapp:80
}
EOF

cat > "$ROOT/compose.override.yaml" << 'EOF'
services:
  miniapp:
    ports: !override []
  # Бэкенд снаружи только через Caddy (HTTPS); прямой порт 8000 — лишь для самого сервера.
  backend:
    ports: !override
      - "127.0.0.1:8000:8000"
  caddy:
    image: caddy:2
    restart: unless-stopped
    depends_on:
      - miniapp
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
volumes:
  caddy-data:
EOF

docker compose up -d --build

healthy=0
for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_HTTP" >/dev/null \
    && curl -fsS --resolve "213.193.198.71:443:127.0.0.1" "$HEALTH_HTTPS" >/dev/null; then
    curl -fsS "$HEALTH_HTTP"
    echo
    healthy=1
    break
  fi
  sleep 2
done
if [[ "$healthy" != "1" ]]; then
  echo "Сайт не ответил на $HEALTH_HTTP или $HEALTH_HTTPS" >&2
  docker compose ps
  docker compose logs backend --tail 60 >&2 || true
  docker compose logs miniapp --tail 20 >&2 || true
  docker compose logs caddy --tail 20 >&2 || true
  exit 1
fi

# Тесты SEC-* считают корнем репозитория parents[2] от backend/tests/.
# Весь каталог монтируется в /src, иначе этот путь оказывается «/».
# В образе нет git — он нужен test_SEC_1 (git ls-files).
docker compose run --rm --no-deps \
  -v "$ROOT:/src" \
  -w /src/backend \
  -e DATABASE_URL=sqlite:////tmp/pytest.db \
  -e MAX_BOT_TOKEN= \
  -e MAX_BOT_MODE=off \
  --entrypoint bash \
  backend -lc 'apt-get update -qq && apt-get install -y -qq git >/dev/null && python -m pytest -q -p no:warnings'

docker run --rm --network host \
  -v "$ROOT:/src" -w /src \
  python:3.12-slim \
  python3 scripts/e2e_docker.py http://127.0.0.1

docker compose ps
curl -fsS --resolve "213.193.198.71:443:127.0.0.1" "$HEALTH_HTTPS"
echo
echo "ClassGo запущен: $PUBLIC_ORIGIN"
