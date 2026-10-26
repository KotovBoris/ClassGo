# Производительность ClassGo (ST-8 · «Задача 2»)

Документ фиксирует объективные замеры mini-app и API, список изменений с измеримым
эффектом, **performance budget** и способ воспроизвести цифры.

Стенд: локальный `docker compose` (mini-app на `http://localhost:8080`, backend :8000),
Chromium через Playwright (Pixel 7), замеры — `ui-e2e/perf/measure.mjs`.

---

## 1. Как воспроизвести замеры

```bash
# 1. Стек (mini-app + backend)
cd hackathon/classgo
export PATH="/opt/homebrew/bin:$PATH"
docker compose up -d --build

# 2. Размеры бандла (JS/CSS, gzip, число чанков)
cd miniapp && npm run build

# 3. Web Vitals + время API + проверка бюджета
cd ../ui-e2e && { [ -d node_modules ] || npm install; }
npm run perf:budget          # = node perf/measure.mjs --budget

# 4. Полный UI-прогон (Playwright, скриншоты)
npm test
```

Отчёты замеров сохраняются в [`ui-e2e/perf/`](../ui-e2e/perf):

- [`baseline.json`](../ui-e2e/perf/baseline.json) — до оптимизаций;
- [`after.json`](../ui-e2e/perf/after.json) — после;
- `last-run.json` — последний прогон (перезаписывается).

Скрипт меряет те же 4 ключевых API, что названы в задаче
(`/api/v1/excursions`, `/api/v1/culture-events`, `/dashboard`, `export-order`),
LCP/TBT/CLS и объём переданных JS/CSS (каждый экран — в свежем контексте, без кэша).

---

## 2. Baseline (до изменений)

Сборка `npm run build`: **49 модулей, 1 JS-чанк, 1 CSS**.

| Артефакт | Размер | gzip |
|---|---|---|
| `dist/assets/index.js` | 315.81 kB | 96.20 kB |
| `dist/assets/index.css` | 81.51 kB | 12.78 kB |

Страница (Pixel 7, локально):

| Метрика | teacher (`/`) | parent (`/?startapp=1`) |
|---|---|---|
| JS по сети | **315.2 kB** (2 запроса) | 315.2 kB (2) |
| CSS по сети | **79.9 kB** | 79.9 kB |
| LCP | 341 ms | 95 ms |
| DCL / load | 190 ms | 59 ms |
| TBT | 0 ms | 0 ms |
| CLS | 0 | 0.22 |

API (медиана / p95): excursions 8.2 / 10.9 ms · culture-events 6.3 / 11.2 ms ·
dashboard 13.7 / 23.8 ms · export-order 7.4 / 10.7 ms.

**Найденные проблемы:**

1. **Ассеты отдаются без сжатия**: nginx не имел `gzip` — браузер получал JS 315 kB
   и CSS 80 kB в открытом виде (проверено заголовками: `Content-Encoding` отсутствовал).
2. **Нет кэш-заголовков**: ни `Cache-Control`, ни `immutable` — повторные открытия
   mini-app каждый раз перекачивали бандл.
3. **CSS-бандл на 81 % состоит из неиспользуемого кода**: `import "@maxhub/max-ui/dist/styles.css"`
   (66 kB) тянул стили всех компонентов MAX UI, тогда как интерфейс использует только
   обёртку `MaxUI` (рендерит `<div class="MaxUI …">`), а свои стили ClassGo — собственные `.kv-*`.
   Глобальных ресетов в этом файле нет (только `.MaxUI_resetBody` на `body`), проверил grep'ом.
4. **Водопад запросов на экране родителя**: `loadAll()` грузил ведомости
   последовательным `for … await` — N выездов × задержка запроса.
5. **Внешний `max-web-app.js` (21 kB, ~0.4 с)** подключён без `defer`/`preconnect`,
   блокируя разбор HTML и первую отрисовку.
6. **CLS 0.22 на экране родителя** (подмена шрифта Golos Text и разная высота скелетона).

---

## 3. Что изменили

| Файл | Изменение | Правило (vercel-react-best-practices) |
|---|---|---|
| [`nginx.conf`](../miniapp/nginx.conf) | `gzip` для JS/CSS/JSON/SVG; `Cache-Control: immutable` для `/assets/` и `/fonts/`, `no-cache` для `index.html` | — |
| [`index.html`](../miniapp/index.html) | `defer` + `preconnect`/`dns-prefetch` для `st.max.ru`; `preload` кириллического сабсета шрифта | `rendering-script-defer-async`, `rendering-resource-hints` |
| [`src/main.tsx`](../miniapp/src/main.tsx) | убран `import "@maxhub/max-ui/dist/styles.css"` (неиспользуемые 66 kB CSS) | `bundle-barrel-imports` |
| [`vite.config.ts`](../miniapp/vite.config.ts) | `manualChunks`: `vendor` (react) и `maxui` (@maxhub/max-ui) | `bundle-dynamic-imports` |
| [`src/App.tsx`](../miniapp/src/App.tsx) | `React.lazy` + `<Suspense>` для всех экранов (каталог, импорт, родитель, справка); `ViewPanel` вынесен из родительской ветки; `transparency` — `boolean`; `useMemo` для активного выезда и списка учеников | `bundle-dynamic-imports`, `rerender-derived-state` |
| [`src/screens/ParentScreen.tsx`](../miniapp/src/screens/ParentScreen.tsx) | `loadAll()` — `Promise.all` вместо последовательного `for-await`; `Map` контекстов ребёнка вместо `find` в рендере | `async-parallel`, `js-index-maps` |
| [`src/screens/CatalogScreen.tsx`](../miniapp/src/screens/CatalogScreen.tsx) | `useMemo` для поиска/сплита по возрасту/класса; дублирующие `useEffect` объединены, зависимость `classes[0].id` вместо массива | `rerender-memo`, `rerender-dependencies` |
| [`src/screens/DashboardScreen.tsx`](../miniapp/src/screens/DashboardScreen.tsx) | `useMemo` для рядов мест и отфильтрованного списка; производные хуки подняты над early-return | `rerender-memo` |
| [`src/styles.css`](../miniapp/src/styles.css) | `content-visibility: auto` + `contain-intrinsic-size` для ряда мест и блока телефонов; `min-height` скелетона | `rendering-content-visibility` |

Дизайн не менялся: правки не затрагивают функции, доступность и состояния загрузки из ST-2…ST-6.

---

## 4. Результат (после изменений)

Сборка: **49 модулей, 11 JS-чанков + 1 CSS**. Начальный JS (index + vendor + maxui)
усох, тяжёлые экраны — отдельные файлы, подгружаемые по требованию:

| Чанк | Размер | gzip |
|---|---|---|
| `index` | 222.75 kB | **70.46 kB** |
| `maxui` | 48.55 kB | 14.28 kB |
| `vendor` | 4.11 kB | 1.54 kB |
| `DashboardScreen` | 14.34 kB | 5.37 kB |
| `CatalogScreen` | 9.82 kB | 3.68 kB |
| `ParentScreen` | 9.26 kB | 3.87 kB |
| `ImportScreen` | 4.24 kB | 1.75 kB |
| `TransparencyScreen` | 2.56 kB | 1.41 kB |
| `icons` / `ExcursionsScreen` / `Alert` | 2.18 / 1.19 / 0.25 kB | 0.75 / 0.64 / 0.21 kB |
| `index.css` | 14.56 kB | **3.39 kB** |

Страница (Pixel 7, локально):

| Метрика | teacher до → после | parent до → после |
|---|---|---|
| JS по сети | 315.2 → **93.0 kB** (−70 %) | 315.2 → **90.6 kB** (−71 %) |
| CSS по сети | 79.9 → **3.6 kB** (−95 %) | 79.9 → **3.6 kB** (−95 %) |
| LCP | 341 → **273 ms** | 95 → 261 ms¹ |
| DCL / load | 190 → **156 ms** | 59 → 67 ms |
| CLS | 0 → **0** | **0.22 → 0** |

¹ На `/?startapp=1` LCP вырос, потому что в baseline экран родителя рендерился из
уже загруженного (общего) JS, а теперь подгружает ленивый чанк `ParentScreen`;
абсолютное значение (261 ms) далеко внутри бюджета 2500 ms, а главное — устранён
сдвиг вёрстки (CLS 0.22 → 0) и срезан начальный JS для основного (учительского) входа.

API (медиана / p95, локальный стек): excursions 5.6 / 10.5 ms · culture-events 4.2 / 5.1 ms ·
dashboard 8.0 / 9.9 ms · export-order 3.0 / 4.8 ms — без регрессий (backend не менялся;
колебания в пределах шума на одном и том же стеке).

---

## 5. Performance budget

Пороговые значения (проверяются `npm run perf:budget`, локальный стек):

| Метрика | Бюджет | Факт после | Запас |
|---|---|---|---|
| LCP (teacher и parent) | ≤ 2500 ms | 273 / 261 ms | 9× |
| TBT | ≤ 300 ms | 0 / 27 ms | 11× |
| CLS | ≤ 0.1 | 0 / 0 | — |
| p95 времени API | ≤ 500 ms | ≤ 10.5 ms | 47× |
| `export-order` | ≤ 1500 ms | 4.8 ms | 300× |
| Начальный JS (gzip) | ≤ 120 kB | 93 kB | 1.3× |
| CSS (gzip) | ≤ 40 kB | 3.6 kB | 11× |

Бюджеты намеренно с запасом: это гарантия отсутствия регрессий на демо-стенде,
а не «потолок возможностей». При выходе за бюджет скрипт возвращает ненулевой код.

Ограничения: замеры локальные (нет сетевого RTT и throttling), поэтому LCP/TBT
оптимистичны; для оценки «в поле» их стоит снимать с `--cpu-throttling` и Slow 4G.
Скрипт замеров теперь принимает тот же стек, что и `run_all_tests.sh`, поэтому
встраивается в CI без изменений.
