# Стратегия тестирования «ClassGo»

Тестирование полностью автоматизировано: ручное QA сведено к тому, что принципиально
нельзя воспроизвести вне мессенджера MAX (см. [`qa/manual-qa.md`](../qa/manual-qa.md)).

## Принцип

1. **Сначала требования, потом тесты.** Все ожидания выписаны в
   [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) с ID (`SVC-1`, `CAT-2`, `BOT-7`, `UI-10`, …).
   Каждый тест ссылается на ID требования.
2. **Три уровня.** Модульные/API (pytest), интерфейс и MAX Bridge (vitest), сквозные
   сценарии (эмулятор протокола MAX + реальный стек в Docker).
3. **Adversarial-прогон.** Отдельный набор `test_crit_adversarial.py` целенаправленно ищет
   дефекты: краевые данные, параллелизм, инъекции, пустые множества.

## Запуск

```bash
./scripts/run_all_tests.sh          # всё, включая Docker-стек
./scripts/run_all_tests.sh --fast   # только pytest + vitest + агентный E2E
```

## Покрытие по уровням

| Уровень | Инструмент | Файлы | Что проверяет |
|---|---|---|---|
| Backend API | pytest | `backend/tests/test_req_*.py` | все REST-ручки: позитив, негатив (404/422), краевые |
| Правила выезда | pytest | `test_req_consent_tickets.py`, `test_req_excursions_dashboard.py` | повторный ответ не затирает первый, статусы класса |
| Чат-бот MAX | pytest | `test_req_bot.py`, `test_bot_protocol.py` | все типы Update, callback-ветки, напоминания, привязка |
| Безопасность/конфиг | pytest | `test_req_security_nfr.py` | нет секретов в репо, зависимости зафиксированы, ошибки без стека |
| Критичные случаи | pytest | `test_crit_adversarial.py` | чужой ученик, нулевой id, 1000-строчный импорт, инъекции, параллелизм |
| MAX Bridge | vitest | `miniapp/src/test/max.test.ts` | нативный вызов только ВНУТРИ MAX, fallback вне MAX |
| REST-клиент | vitest | `miniapp/src/test/api.test.ts` | сборка query, POST-тела, обработка ошибок |
| UI и клики | vitest | `miniapp/src/test/components.test.tsx`, `app.test.tsx` | вкладки, каталог, создание выезда, «Сводка ответов», экран родителя, скачивание |
| Сквозной бот | python | `scripts/e2e_agent.py` | эмулятор MAX: приветствие, нажатие кнопки, напоминания, приказ, webhook |
| Сквозной стек | python | `scripts/e2e_docker.py` | `docker compose up` + прохождение сценария по HTTP |
| UI в браузере | Playwright | `ui-e2e/tests/ui.spec.ts` | клики по всем экранам, вьюпорты, скриншоты, адаптив |

## Номера

| Набор | Тестов | Статус |
|---|---|---|
| Backend (pytest) | 189 | ✅ |
| Frontend (vitest) | 83 | ✅ |
| Агентный E2E (эмулятор MAX) | 15 | ✅ |
| Docker-стек по HTTP | 19 | ✅ |
| UI в браузере (Playwright, desktop + mobile) | 9 × 2 = 18 | ✅ |
| **Итого** | **324 проверки** | ✅ |

Плюс нагрузочная проверка записи `scripts/race_check.py` (100 параллельных потоков) и
замеры производительности `ui-e2e/perf/measure.mjs` (бюджеты — [`PERFORMANCE.md`](PERFORMANCE.md)).

CI (GitHub Actions, `.github/workflows/ci.yml`) прогоняет backend, frontend и агентный E2E
на каждый push и pull request — воспроизводимость подтверждается автоматически.

## Просмотр и итерация интерфейса

UI можно смотреть и отлаживать без мессенджера MAX:

```bash
docker compose up -d --build          # поднять стек
cd ui-e2e && npm install               # один раз
npx playwright install chromium        # один раз
BASE_URL=http://localhost:8080 npx playwright codegen   # интерактивно «кликать» и смотреть
npx playwright test --project=desktop  # прогнать + записать скриншоты в ui-e2e/screenshots/
```

Скриншоты ключевых экранов лежат в [`docs/screenshots/`](screenshots/) и используются
в презентации. Внутри мини-приложения (без MAX) работает **режим просмотра**: переключение
на экран любого родителя и сброс демо-данных (кнопка «Сбросить демо-данные»).

## Сквозной сценарий (эмулятор MAX), `scripts/e2e_agent.py`

Поднимается `ThreadingHTTPServer`, повторяющий контракт MAX (`GET /me`, `GET /updates`,
`POST /messages`, `POST /answers`). Настоящий backend работает в режиме `polling` и
обращается к эмулятору — то есть тестируется **реальный код адаптера**, а не заглушка.

Шаги: запуск бота → приветствие с `open_app` → создание выезда → нажатие кнопки
родителем → согласие в БД → идемпотентность → напоминания → приказ DOCX/PDF → webhook.

## Найденные при критичном прогоне дефекты (исправлены)

| Дефект | Как проявлялся | Исправление |
|---|---|---|
| Скачивание приказа вне MAX | `WebApp.downloadFile` существует и в браузере, но молча ничего не делает | вызов нативного метода только при `isInsideMax()`; добавлены прямые ссылки |
| Ложное «доставлено» в напоминаниях | `delivered` считал всех адресатов, даже без привязки/отправки | доставленным считается только реально отправленное сообщение |
| Webhook считал мусор обработанным | `processed` включал элементы без `update_type` | считается только валидный Update |
| **Падение бота при старте** | `BOT_COMMANDS` использовался в lifespan, но не был импортирован → polling не стартовал; pytest не ловил (бот выключен), поймал E2E | добавлен импорт; заведён регресс-тест `BOT-22` на символы lifespan, E2E проверяет `PATCH /me/commands` |
| Эмулятор ломал keep-alive | `PATCH /me/commands` не читал тело → непрочитанные байты рвали long polling | `do_PATCH` читает тело; E2E стал выявлять такие дефекты (режим `E2E_VERBOSE=1`) |
