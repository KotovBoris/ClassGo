#!/usr/bin/env bash
# Единый прогон ВСЕХ тестов «ClassGo».
#
#   ./scripts/run_all_tests.sh          # всё
#   ./scripts/run_all_tests.sh --fast   # без docker-стека (pytest + vitest + agent e2e)
#
# Требуется: Python 3.13 (backend/.venv313), Node 20 (miniapp/node_modules).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

fail=0
run() {
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "▶ $1"
  echo "════════════════════════════════════════════════════════════"
  shift
  "$@" || fail=1
}

# 1. Backend: pytest (требования + adversarial). Запуск из backend/ — там pytest.ini.
run "Backend tests (pytest: требования REQUIREMENTS.md + adversarial)" \
  bash -c "cd '$ROOT/backend' && ./.venv313/bin/python -m pytest -q -p no:warnings"

# 2. Frontend: vitest (MAX Bridge, api, компоненты и клики)
run "Frontend tests (vitest: MAX Bridge, api, UI-клики)" \
  bash -lc 'source "$HOME/.nvm/nvm.sh" 2>/dev/null; nvm use 20 >/dev/null 2>&1; cd miniapp && npm test'

# 3. Агентный E2E: эмулятор протокола MAX + реальный polling
run "Agent E2E (эмулятор MAX: бот, callbacks, документы)" \
  ./backend/.venv313/bin/python scripts/e2e_agent.py

# 4. Docker-стек по HTTP + нагрузка на запись + UI-харнесс (Playwright)
if [[ "$FAST" == "0" ]]; then
  run "Docker stack (compose up + HTTP сценарий)" bash -lc '
    docker compose up -d --build >/dev/null 2>&1
    for i in $(seq 1 40); do
      code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/healthz || true)
      [ "$code" = "200" ] && break; sleep 2
    done
    curl -s -X POST http://localhost:8080/api/v1/admin/reset-demo >/dev/null
    python3 scripts/e2e_docker.py http://localhost:8080'

  run "Нагрузка на запись (гонки/блокировки БД, 100 потоков)" \
    python3 scripts/race_check.py http://localhost:8080 100

  run "UI-харнесс (Playwright: клики + скриншоты)" bash -lc '
    source "$HOME/.nvm/nvm.sh" 2>/dev/null; nvm use 20 >/dev/null 2>&1
    cd ui-e2e && { [ -d node_modules ] || npm install --no-audit --no-fund; }
    npx playwright test'
fi

echo ""
if [[ "$fail" == "0" ]]; then
  echo "✅ ВСЁ ЗЕЛЁНОЕ"
else
  echo "❌ ЕСТЬ ПАДЕНИЯ (см. вывод выше)"
fi
exit "$fail"
