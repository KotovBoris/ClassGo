# MOTION_AND_A11Y.md — анимация, производительность и доступность для аудитории 50+ (ClassGo)

> Сдаваемый документ. Отвечает на 5 вопросов владельца про анимации, слабые устройства и
> крупный системный текст; даёт конкретное предложение под ClassGo. Компаньоны:
> [`DESIGN.md`](DESIGN.md) (§2 «Движение»), [`PERFORMANCE.md`](PERFORMANCE.md) (бюджет и замеры),
> [`UX_PLAYBOOK.md`](UX_PLAYBOOK.md) (§1.12/§4.5/§4.10), [`COLOR.md`](COLOR.md) (контраст).
>
> **Статус: реализовано (27.09).** Правки P0–P2 применены в `miniapp/src/styles.css`,
> `ImportScreen.tsx`, `CatalogScreen.tsx`; `DESIGN.md` §2/§3 и `UX_PLAYBOOK.md` §4.5/§4.6
> синхронизированы. Проверки: `vite build` OK, `tsc --noEmit` чисто, `vitest` 85/85,
> `avoid-ai-design` — 0 находок. Скриншоты/презентацию нужно перегенерировать (сдвиг вёрстки).
>
> Контекст продукта: сервис школьных культурных выездов в MAX, основной пользователь —
> **классный руководитель 40–55+** (вторичный — родитель), продукт **документный**
> (согласия, приказы, отчётность), а не развлекательный. Метрика — оценка жюри.

---

## 0. TL;DR — 7 выводов

1. **Анимация нужна не как украшение, а как обратная связь.** Мера пользы движения в утилитарном
   сервисе — «объясняет ли оно, что произошло». Декоративные fade-up/«летающие карточки» не
   добавляют ценности и только жгут кадры. ([NN/g — Role of Animation and Motion](https://www.nngroup.com/articles/animation-purpose-ux/))
2. **Дёшево и безопасно — только `transform`/`opacity`.** Эти два свойства браузер отдаёт
   композитору (отдельный поток), они не вызывают layout/repaint и **не попадают в INP**.
   Всё остальное (`background-color`, `width`, `height`, `box-shadow`, `background-position`)
   гоняет главный поток. ([web.dev — Animations and performance](https://web.dev/articles/animations-and-performance), [web.dev — Optimize INP](https://web.dev/articles/optimize-inp))
3. **Длительность: 100–300 мс, `prefers-reduced-motion` обязателен.** Для частых действий — короче;
   для редких/крупных — до ~300–400 мс. Долгие/повторяющиеся анимации на слабом Android дают jank
   и утомляют. ([Material 3 — Easing and duration](https://m3.material.io/styles/motion/easing-and-duration),
   [NN/g — Animation duration](https://www.nngroup.com/articles/animation-duration/))
4. **`prefers-reduced-motion` — реальная потребность, а не «галочка».** Его включают люди с
   вестибулярными расстройствами и те, кому движение мешает; чувствительность к движению растёт с
   возрастом. У нас уже частично учтено — надо довести до «no-motion-first».
   ([MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion),
   [Tatiana Mac](https://www.tatianamac.com/posts/prefers-reduced-motion))
5. **Аудитория 50+ — реальная, и крупный текст часто включён.** Зрение заметно падает уже после 40;
   часть пользователей 55+ чувствуют себя неуверенно в цифровой среде. Вёрстка обязана жить при
   масштабе текста, а не ломаться: **относительные единицы, гибкие высоты, перенос вместо обрезки,
   тап-зоны ≥ 44px, минимум 16px для основного текста.** ([NN/g — Usability for Older Adults](https://www.nngroup.com/articles/usability-for-senior-citizens/),
   [WCAG 2.2 Resize text / Reflow](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html), [NAFI — цифровой разрыв 55+](https://nafi.ru/polls/tsifrovoy-razryv-kazhdyy-tretiy-rossiyanin-starshe-55-let-boitsya-ostatsya-za-bortom-tekhnologiy/))
6. **Для документных сервисов важнее предсказуемость и скорость, чем «вау».** Правительственные
   системы (GOV.UK) намеренно аскетичны: минимум движения, максимум однозначности. Aesthetic-Usability
   Effect («красивое кажется удобнее») работает, но **маскирует** проблемы и не заменяет скорость и
   понятность. ([NN/g — Aesthetic-Usability Effect](https://www.nngroup.com/articles/aesthetic-usability-effect/),
   [GOV.UK — Dos and don'ts for accessibility](https://accessibility.blog.gov.uk/2016/09/02/dos-and-donts-on-designing-for-accessibility/))
7. **Вывод для ClassGo: анимаций мало и они точечные.** Заслуживают движения 3–4 места (отклик
   кнопки, раскрытие inline-формы, переключение вкладки, смена статуса). Всё остальное — «нет».
   Деньги «вау» вкладываем в скорость, понятность и доступность, а не в движение.

---

## 1. Ответы на 5 вопросов (с источниками)

### 1.1 Нужны ли анимации этой аудитории в таком продукте?

**Да, но только функциональные.** В UX-терминах движение делится на три роли:
**обратная связь** (клик сработал), **метафора состояния/навигации** (откуда пришёл экран),
**привлечение внимания** (что-то появилось). Для утилитарного, документного сервиса ценны первые
две; третья почти не нужна (внимание отбираем у задачи). ([NN/g — Role of Animation and Motion](https://www.nngroup.com/articles/animation-purpose-ux/),
[NN/g — Animation for Attention and Comprehension](https://www.nngroup.com/articles/animation-usability/))

Что реально даёт пользу:
- **обратная связь на действие** — снятие неопределённости «нажалось ли» (0.1 с — порог «мгновенно»);
- **perceived performance** — скелетон/оптимистик вместо пустоты сокращают *ощущаемое* ожидание;
- **ориентация** — понимание, что открылось, что изменилось (без движения этого не видно).

Что такое декор: `fade-up` на каждом блоке при скролле, «летающие» карточки, параллакс,
hover-подъёмы с `box-shadow`. Они не несут смысла, зато создают работу главному потоку и
утомляют на повторных заходах. Порог восприятия отклика: **0.1 с — «мгновенно», 1 с — не рвётся
поток мысли, 10 с — предел удержания внимания** ([NN/g — Response Time Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)),
Doherty Threshold — **< 400 мс** ([Doherty threshold](https://www.ux-guidelines.com/doherty-threshold.html)).

**Как делать легко:** только CSS `transition`/`@keyframes` на `transform`/`opacity`, без JS-анимаций
(`requestAnimationFrame` + style — дороже и на главном потоке), длительность 100–300 мс,
`prefers-reduced-motion` выключает всё несущественное ([web.dev — prefers-reduced-motion](https://web.dev/articles/prefers-reduced-motion)).

### 1.2 Производительность на слабых устройствах

Что «убивает» веб-приложение на бюджетном Android (примерно **в 9 раз слабее флагмана по одному
ядру** — [Infrequently, 2026](https://infrequently.org/2025/11/performance-inequality-gap-2026/),
[CSS Wizardry, 2025](https://csswizardry.com/2025/08/low-and-mid-tier-mobile-for-the-real-world-2025/)):

1. **JS-бандл и его парсинг/исполнение** — главный фактор (у нас уже срезан на −70 %,
   см. [`PERFORMANCE.md`](PERFORMANCE.md)).
2. **Длинные списки и большие DOM** — много узлов → дорогие layout/paint (частично лечится
   `content-visibility`, у нас уже применено к `.kv-bay`/`.kv-emergency`).
3. **Тяжёлые шрифты** — у нас локальный Golos Text, кириллический сабсет, `preload` — ок.
4. **Анимации на не-composited свойствах** — единственная категория, которую мы можем случайно
   «добавить» и испортить. `width/height/top/left/background-position/box-shadow/filter` требуют
   пересчёта layout или отрисовки на **каждом кадре** → jank на слабом CPU. `transform`/`opacity`
   идут на GPU-композиторе и не блокируют главный поток.

**Пороги и термины:**
- **Кадровый бюджет.** 60 fps = кадр каждые **16.7 мс**; 120 fps = **8.3 мс**. Всё, что длиннее,
  = видимый jank. Для анимации это значит: работать только на композиторе, где кадр рисует GPU.
- **INP (Interaction to Next Paint)** — Core Web Vital «отзывчивость». **Good ≤ 200 мс**,
  Poor > 500 мс ([web.dev — INP](https://web.dev/articles/inp)). INP = input delay + обработка +
  presentation delay. **Compositor-анимации не удлиняют INP** — они не блокируют главный поток;
  анимации на `width`/`background` — удлиняют. ([web.dev — Optimize INP](https://web.dev/articles/optimize-inp))
- **TBT (Total Blocking Time)** — суммарное время, когда главный поток был занят > 50 мс подряд
  (lab-метрика, наш бюджет ≤ 300 мс). Анимации на главном потоке растят TBT; композиторные — нет.

**Сколько безопасно:** держать одновременно ≤ 1–2 коротких композиторных анимации, длительность
≤ 300 мс, запускать по действию пользователя (не авто-плей в цикле, кроме индикатора загрузки).
`will-change` — только точечно и не навсегда: постоянный `will-change: transform` на многих
элементах = лишние слои и память, хуже, чем без него. ([MDN — will-change](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/will-change),
[MDN — CSS performance optimization](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Performance/CSS))

### 1.3 Аудитория 50+ и крупный текст

**Насколько это реально.** Старение зрения начинается не в 60, а примерно с 20: **у людей 40+
зрение уже требует шрифта крупнее**, чем у дизайнеров-двадцатилетних ([NN/g — Usability for Older Adults](https://www.nngroup.com/articles/usability-for-senior-citizens/)).
Часть аудитории 55+ в РФ чувствует себя неуверенно в цифровой среде: **45 % называют себя уязвимыми
перед интернет-технологиями, каждый третий боится «остаться за бортом»** ([NAFI](https://nafi.ru/polls/tsifrovoy-razryv-kazhdyy-tretiy-rossiyanin-starshe-55-let-boitsya-ostatsya-za-bortom-tekhnologiy/)),
при этом активность 55+ в интернете растёт ([RBC](https://www.rbc.ru/life/news/68efb4039a794730278bd965)).
Крупный системный шрифт — распространённый способ компенсации; продукт обязан его выдержать.

**Что говорят гайдлайны:**
- **Минимум 16 px для основного текста**; для пожилых/слабовидящих рекомендуется больше; интерлиньяж
  ≥ 1.5 ([Health.gov — readable font](https://odphp.health.gov/healthliteracyonline/design-easy-scanning/use-readable-font-thats-least-16-pixels),
  [A11Y Collective — font size](https://www.a11y-collective.com/blog/wcag-minimum-font-size/)).
- **WCAG 1.4.4 Resize text (AA):** текст масштабируется до **200 %** без потери контента.
  **1.4.10 Reflow (AA):** контент не требует горизонтального скролла при ширине **320 CSS px**.
  ([WCAG 2.2 Resize text](https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html))
- **WCAG 2.5.8 Target Size Minimum (AA):** тап-зона ≥ **24×24 px** с исключением «достаточного зазора»;
  **2.5.5 (AAA) и практика мобильных — 44×44 px**. Ниже 24 px — прямое нарушение.
  ([WCAG 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html))
- **WCAG 2.3.3 Animation from Interactions (AAA):** движение, вызванное взаимодействием, можно
  отключить (у нас это делает `prefers-reduced-motion`).
  ([WCAG 2.3.3](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html))
- **Контраст:** текст ≥ 4.5:1 (у нас уже проверен, см. [`COLOR.md`](COLOR.md) §6).

**Почему `rem`, а не `px`:** размеры в `px` игнорируют системную настройку крупного шрифта; `rem`
масштабируется вместе с ней. При этом не всякая вёрстка из `rem` автоматически безопасна — важны
**гибкие высоты** (без фиксированных `height` под текст) и **перенос вместо обрезки**.
([Josh Comeau — Pixels and accessibility](https://www.joshwcomeau.com/css/surprising-truth-about-pixels-and-accessibility/),
[matuzo — user preferences](https://www.matuzo.at/blog/writing-even-more-css-with-accessibility-in-mind-user-preferences/))

### 1.4 «Красивое и плавное» vs «строгое и надёжное»

**Для документных/утилитарных сервисов ценнее предсказуемость и скорость.** Аргументы:
- **GOV.UK** строит всё на минимуме декора и движении: цель — однозначность и доступность, а не
  впечатление. Практическое правило их гайдов — не злоупотреблять анимацией, уважать
  `prefers-reduced-motion`. ([GOV.UK — Dos and don'ts](https://accessibility.blog.gov.uk/2016/09/02/dos-and-donts-on-designing-for-accessibility/),
  [Home Office — Moving and flashing content](https://design.homeoffice.gov.uk/accessibility/providing-alternatives/moving-and-flashing-content))
- **Material** тоже рассматривает движение как **функциональный** инструмент (easing/duration для
  отклика и навигации), а не как самоцель ([Material 3 — Easing and duration](https://m3.material.io/styles/motion/easing-and-duration)).
- **Aesthetic-Usability Effect** действительно есть: привлекательное воспринимается как более удобное,
  пользователь терпимее к мелким проблемам. Но две оговорки: эффект **маскирует** дефекты и **не
  спасает от медленного/ошибочного** сервиса; в исследованиях эффект на объективные метрики
  удобства нестабилен. ([NN/g — Aesthetic-Usability Effect](https://www.nngroup.com/articles/aesthetic-usability-effect/),
  [UX Knowledge Base — что говорят исследования](https://uxknowledgebase.com/aesthetic-usability-effect-what-does-the-research-say-7d5cae2d9785))
- «Вау»-анимации сильнее там, где продукт **удерживает** (игры, медиа, маркетинг). У нас задача —
  быстро довести учителя до результата; движение здесь = трение, если не несёт смысла.

**Вывод:** плавность — да (она часть скорости и качества), «вау ради вау» — нет. Для жюри
выигрывает **уверенное и быстрое** прохождение сценария, а не пара эффектов.

### 1.5 Что реально важно (драйверы доверия/удовлетворённости)

По совокупности исследований и практик для утилитарных сервисов порядок важности:

| # | Драйвер | Почему важнее «красоты» | Источник |
|---|---|---|---|
| 1 | **Работает и не падает** | дисквалификация/штраф и в регламенте, и в доверии | критерии жюри (`docs/input`), 30–60 % техоценки |
| 2 | **Быстро откликается** | Doherty < 400 мс, 0.1/1/10 с — пороги восприятия | [Doherty](https://www.ux-guidelines.com/doherty-threshold.html), [NN/g](https://www.nngroup.com/articles/response-times-3-important-limits/) |
| 3 | **Понятно без обучения** | узнавание важнее вспоминания; язык пользователя | [`UX_PLAYBOOK.md`](UX_PLAYBOOK.md) §1 |
| 4 | **Доступно** | значимая доля 50+; крупный текст, контраст, тап-зоны | [WCAG](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [NN/g 50+](https://www.nngroup.com/articles/usability-for-senior-citizens/) |
| 5 | **Без ошибок и с ясной обратной связью** | «проглоченный» клик = повтор и потеря доверия | [`UX_PLAYBOOK.md`](UX_PLAYBOOK.md) §2.1 |
| 6 | **Эстетика (чистота, порядок)** | есть, но работает на 1–5, а не вместо них | [NN/g Aesthetic-Usability](https://www.nngroup.com/articles/aesthetic-usability-effect/) |

**Итог: акцент на анимациях делать не стоит.** Движение — тонкий слой поверх 1–5. Заслуживают его
**2–4 места** (ниже §2): отклик кнопки, раскрытие inline-формы, переключение вкладки, смена статуса/появление алерта.

---

## 2. Таблица: элемент → анимация да/нет

Все «да» — только `transform`/`opacity`, только CSS, всегда под `prefers-reduced-motion`.

| Элемент (класс/UX) | Анимация | Как | Длительность / свойство | Риск на слабом телефоне |
|---|---|---|---|---|
| Нажатие кнопки `.kv-btn` (главное действие) | **ДА** | лёгкий отклик: смена фона/рамки (уже есть) + опц. `transform: scale(0.98)` на `:active` | 90–150 мс, `background-color`/`transform` | низкий; смена цвета — лёгкий paint, ок для одной кнопки |
| Кнопка в состоянии загрузки (`.kv-btn.busy`, `.kv-spin`) | **ДА** | вращение индикатора (уже есть) | 700 мс, `transform: rotate` | низкий; композиторное; выключается `reduced-motion` |
| Скелетон загрузки `.kv-skel-bar` | **ДА (опц.)** | статичный блок предпочтительнее; если shimmer — только `opacity` «дыхание» | 1000–1500 мс, `opacity` | средний: `background-position`-shimmer = paint каждый кадр → заменить |
| Раскрытие inline-формы события (`.kv-order-row`, `.kv-inline-order`) | **ДА** | появление под строкой: `opacity` + малый `translateY`, при плавной высоте — `grid-template-rows`/`max-height` осознанно | 150–200 мс, `opacity`/`transform` | средний: анимация `height` дорога → использовать `transform`+`opacity`, не `height` |
| Переключение вкладок `.kv-tabs` | **ДА (минимально)** | смена активной пилюли без «переезда»: цвет/фон | ≤ 120 мс, `background-color` | низкий |
| Смена статуса места/чипа (`.kv-seat-*`, `.badge-*`) | **ДА (мягко)** | короткий «пульс» `opacity` при переходе статуса | 150–200 мс, `opacity` | низкий |
| Появление алерта/тоста (`.kv-alert`) | **ДА (вход)** | мягкий вход `opacity` (+2–4 px `translateY`) | 150–200 мс, `opacity`/`transform` | низкий; не крутить в цикле |
| Появление строк списка/таблицы (fade-up при скролле) | **НЕТ** | — | — | декор без смысла; на длинном списке = много работы |
| Hover-подъём карточек (`translateY`+`box-shadow`) | **НЕТ** | вместо этого мгновенная подсветка строки (уже есть) | — | `box-shadow` = paint; на тач-устройствах hover не нужен |
| Переходы между экранами (slide/fade страниц) | **НЕТ** | экран появляется сразу | — | усложняет, замедляет, конфликтует с CLS-контролем |
| Параллакс / авто-карусели / фоновое движение | **НЕТ** | — | — | вестибулярный риск + постоянная нагрузка |
| `content-visibility` для дальних рядов `.kv-bay` | **ДА (перф, не анимация)** | уже есть; не анимировать | — | снижает работу, оставить |

**Правило-фильтр перед добавлением любой анимации:** «Что пользователь поймёт из движения, чего
не поймёт без него?» Если ответа нет — не добавлять.

---

## 3. Крупный текст и доступность 50+ — изменения в CSS (P0/P1/P2)

Основа: [`miniapp/src/styles.css`](miniapp/src/styles.css). Базовый текст сейчас **15 px**,
много подписей **12–13 px** — ниже минимума 16 px для основного текста. Тап-зоны: кнопка
`min-height: 40px`, место `.kv-seat` **38×38**, чекбокс **16 px** — ниже 44 px.

### P0 — ломает читаемость/нажатие при крупном тексте (до защиты)

1. **Основной текст → 16 px.** `body { font-size: 15px }` ([`styles.css:69`](miniapp/src/styles.css:69)) → `16px` (или `1rem`).
   Перевести тип-шкалу в `rem`/`em`: заголовки/подписи масштабируются с системной настройкой.
2. **Отказ от жёстких зон под текст.** Пройти по фиксированным `height`/`width`, где внутри текст:
   `.kv-seat` 38×38 ([`styles.css:523`](miniapp/src/styles.css:523)), фиксированные высоты скелетона
   ([`styles.css:758`](miniapp/src/styles.css:758), `:780`), `.kv-dot` 9×9, `.kv-progress` `height: 10px`.
   Заменить на `min-height`/`aspect-ratio`/`padding` — чтобы крупный текст не обрезался.
3. **Убрать `white-space: nowrap` там, где текст может стать длиннее** при масштабе:
   [`styles.css:172`](miniapp/src/styles.css:172), `:374`, `:488`, `:583`, `:658`. Заменить на перенос
   (`overflow-wrap: anywhere`) или `nowrap` только для действительно коротких меток (время, число).
4. **Тап-зоны ≥ 44×44.** Кнопка `.kv-btn` `min-height: 40px` ([`styles.css:225`](miniapp/src/styles.css:225)) → 44px;
   место `.kv-seat` 38→44 ([`styles.css:524`](miniapp/src/styles.css:524)); чекбокс-зона увеличить
   паддингом до ≥ 44 px ([`styles.css:710`](miniapp/src/styles.css:710)). WCAG 2.5.8 (24 px) — минимум,
   44 px — цель для аудитории 50+ и касаний.
5. **`-webkit-text-size-adjust: 100%`** на `html/body` — не давать мобильному браузеру самовольно
   «бустить» или ломать масштаб текста. ([matuzo](https://www.matuzo.at/blog/writing-even-more-css-with-accessibility-in-mind-user-preferences/))

### P1 — заметно улучшает при крупном тексте

6. **Гибкая сетка `Ряды мест`.** `grid-template-columns: repeat(4, 38px)` ([`styles.css:519`](miniapp/src/styles.css:519)) —
   переход на `repeat(auto-fill, minmax(44px, 1fr))`, чтобы ряды переупаковывались, а не вылезали.
7. **Интерлиньяж и переносы.** `line-height ≥ 1.5` (есть) подтвердить для мелких подписей;
   добавить `overflow-wrap: anywhere` для длинных ФИО/названий событий; проверить hero на длинном названии.
8. **Проверка зума 200 % и ширины 320 px.** Прогнать экраны в браузере: текст +200 %, окно 320 px —
   нет горизонтального скролла, ничего не обрезано (WCAG 1.4.4/1.4.10).
9. **Контраст мелких подписей** после смены размеров перепроверить (`--ink-2` на `--sheet` = 5.8:1 — ок).

### P2 — полировка

10. **`text-wrap: pretty`** уже есть ([`styles.css:73`](miniapp/src/styles.css:73)) — оставить, добавить
    `text-wrap: balance` для коротких заголовков, если поддерживается.
11. **Проверить `min-width`/`width` у колонок таблицы** (`.kv-alias` 46px, колонка даты 88px,
    [`styles.css:512`](miniapp/src/styles.css:512), `:653`) — не должны выдавливать контент при крупном тексте.
12. **Не полагаться на цвет статуса** — уже решено (текст + `aria-label`), сохранить при рефакторинге.

> Приоритет P0 = соответствие WCAG 1.4.4/1.4.10/2.5.8 + базовая читаемость для 50+; P1 = комфорт;
> P2 = косметика.

---

## 4. Performance-бюджет для анимаций

Проверяется вручную/Playwright на Pixel 7 + CPU-throttle 4×, Slow 4G (расширение бюджета из
[`PERFORMANCE.md`](PERFORMANCE.md) §5).

| Параметр | Бюджет | Почему |
|---|---|---|
| Одновременных анимаций | **≤ 2** | больше — риск конкуренции за композитор/память |
| Длительность одной анимации | **100–300 мс** (макс. 400 для крупных переходов) | длиннее — утомляет и заметнее jank ([NN/g duration](https://www.nngroup.com/articles/animation-duration/)) |
| Анимируемые свойства | **только `transform`, `opacity`** | compositor-only, не влияют на layout/INP |
| Анимации в цикле | **только индикатор загрузки** (`.kv-spin`) | постоянное движение жжёт батарею и внимание |
| `will-change` | **0 постоянных**, максимум 1 точечно и снимать после | иначе лишние слои/память ([MDN](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/will-change)) |
| INP (в поле) | **≤ 200 мс (good)** | Core Web Vital; композиторные анимации не удлиняют |
| TBT (lab) | **≤ 300 мс** | анимации на главном потоке его растят |
| Кадровый бюджет | цель **60 fps (16.7 мс/кадр)** | jank = пропуск кадров |
| `prefers-reduced-motion` | **покрытие 100 %** не-essential движения | сегодня: все transition off, но проверить новые |

**Анти-паттерны бюджета (что сразу превышает):** `width/height`-транзишены на списках,
`background-position` shimmer в цикле, `box-shadow` при hover на длинном списке, `filter: blur`
в анимации, JS-анимации через `rAF` + смена стилей.

---

## 5. Влияние на критерии жюри

Веса из `docs/input/Презентация.md` (слайды 11–14):

- **UX/UI и удобство — 20 % продуктовой оценки** (40 % онлайн-этапа). Логика «пользователь проходит
  главный сценарий без трения» — ровно то, что усиливают §2 (точечное движение) и §3 (крупный текст).
  Прямо закрывает анти-паттерны из [`UX_PLAYBOOK.md`](UX_PLAYBOOK.md) §2/§6.
- **Пользовательская ценность — 25 %.** Явная подстройка под реального пользователя 40–55+ (а не
  «средний мобильный юзер») — сильный аргумент на защите: «мы знаем, что у учителя часто включён
  крупный текст и бюджетный Android».
- **Стабильность и обработка ошибок — 10 % техоценки.** Композиторные анимации и отсутствие тяжёлых
  эффектов = меньше шансов на jank/подвисание на слабом устройстве проверяющего; это прямо про
  «стабильно работает при повторном прохождении».
- **Работоспособность и полнота функций — 30 %.** Анимации **не должны** мешать пройти сценарий;
  поэтому декоративные эффекты в списке «нет» — снижают риск регрессий.
- **Платформенный бонус +0,15.** Не относится к движению напрямую, но `prefers-reduced-motion` и
  аккуратный веб-слой (Web Interface Guidelines) поддерживают общее качество интеграции с MAX.
- **Доступность** отдельного критерия не имеет, но «вшита» в UX/UI: WCAG 2.2 AA (`1.4.4`, `1.4.10`,
  `2.5.8`) и уважение `prefers-reduced-motion` — это готовые пункты для ответов жюри.

**Формулировка для защиты:** «Мы осознанно не делаем «вау»-анимаций: на слабом телефоне и при
крупном системном тексте это стоит кадров и читаемости. Вместо этого — короткое движение только как
обратная связь, полная поддержка reduce-motion и вёрстка, которая живёт при +200 % текста.»

---

## 6. Предложение к реализации (файлы и классы)

Код **не менялся**. Ниже — что и где править в отдельной подзадаче (приоритет P0 → P1).

| Файл | Что сделать | Приоритет |
|---|---|---|
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | `body` 15px→16px/1rem; тип-шкала → `rem`; `html/body` + `-webkit-text-size-adjust: 100%` | P0 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | `.kv-btn` `min-height` 40→44px; `.kv-seat` 38→44px; чекбокс-зона ≥ 44px | P0 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | убрать/переосмыслить `white-space: nowrap` (`:172/:374/:488/:583/:658`), добавить `overflow-wrap` | P0 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | `.kv-seat-grid` → `repeat(auto-fill, minmax(44px, 1fr))` | P1 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | shimmer `.kv-skel-bar` (`background-position`) → статичный или `opacity`-пульс | P1 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | раскрытие `.kv-order-row`/`.kv-inline-order` — вход `opacity`+`translateY` 150–200 мс (не `height`) | P1 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | `:active`-отклик кнопки (`transform: scale(.98)`), ≤ 150 мс | P2 |
| [`miniapp/src/styles.css`](miniapp/src/styles.css) | расширить `@media (prefers-reduced-motion: reduce)` на новые анимации (сейчас `:995`) | P1 |
| [`miniapp/index.html`](miniapp/index.html) | при необходимости — уточнить viewport (`maximum-scale` **не** ставить) | P2 |
| [`ui-e2e/perf/measure.mjs`](ui-e2e/perf/measure.mjs) | добавить проверку: +200 % текста и 320 px без горизонтального скролла; INP-сценарий | P1 |

Отдельно зафиксировать в [`DESIGN.md`](DESIGN.md) §2 «Движение» (после реализации): список
разрешённых анимаций и правило «только `transform`/`opacity`, ≤ 300 мс».

---

## 7. Что НЕ делать (осознанно)

- Не добавлять `fade-up`/scroll-reveal на блоки и строки списка.
- Не анимировать `width`/`height`/`top`/`left`/`box-shadow`/`background-position`/`filter` в цикле.
- Не использовать JS-анимации и внешние animation-библиотеки (лишний вес бандла и главный поток).
- Не ставить постоянный `will-change` в расчёте «пусть будет быстрее» — будет хуже.
- Не делать переходы между экранами и параллакс.
- Не наращивать контент/декор ради «красоты» в ущерб плотности и скорости.
- Не блокировать зум: **никакого** `user-scalable=no` / `maximum-scale=1`.
- Не задавать вёрстку только в `px` там, где размер должен расти с системным текстом.
- Не полагаться на цвет статуса без текста/подписи (уже соблюдено — не ломать).

---

## 8. Источники

**Анимация и движение (UX)**
- NN/g — The Role of Animation and Motion in UX: https://www.nngroup.com/articles/animation-purpose-ux/
- NN/g — Executing UX Animations: Duration and Motion Characteristics: https://www.nngroup.com/articles/animation-duration/
- NN/g — Animation for Attention and Comprehension: https://www.nngroup.com/articles/animation-usability/
- Material 3 — Easing and duration: https://m3.material.io/styles/motion/easing-and-duration

**Воспринимаемая скорость и отклик**
- NN/g — Response Time Limits (0.1 / 1 / 10 c): https://www.nngroup.com/articles/response-times-3-important-limits/
- Doherty Threshold (< 400 мс, IBM 1982): https://www.ux-guidelines.com/doherty-threshold.html

**Производительность рендера и метрики**
- web.dev — Animations and performance (только `transform`/`opacity`): https://web.dev/articles/animations-and-performance
- web.dev — Interaction to Next Paint (INP): https://web.dev/articles/inp
- web.dev — Optimize INP: https://web.dev/articles/optimize-inp
- web.dev — Defining Core Web Vitals thresholds: https://web.dev/articles/defining-core-web-vitals-thresholds
- MDN — will-change: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/will-change
- MDN — CSS performance optimization: https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Performance/CSS
- Инфраструктура слабых устройств: https://infrequently.org/2025/11/performance-inequality-gap-2026/ · https://csswizardry.com/2025/08/low-and-mid-tier-mobile-for-the-real-world-2025/
- GPU-композитинг и слои: https://www.mironsoft.de/en/blog/performance-gpu-compositing-and-layers-explained

**Reduce-motion и доступность движения**
- MDN — prefers-reduced-motion: https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion
- web.dev — prefers-reduced-motion: https://web.dev/articles/prefers-reduced-motion
- Tatiana Mac — no-motion-first: https://www.tatianamac.com/posts/prefers-reduced-motion
- WCAG 2.3.3 Animation from Interactions: https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html

**Аудитория 50+ и крупный текст**
- NN/g — Usability for Older Adults: https://www.nngroup.com/articles/usability-for-senior-citizens/
- NN/g — UX Design for Seniors (report): https://www.nngroup.com/reports/senior-citizens-on-the-web/
- Health.gov — readable font ≥ 16 px: https://odphp.health.gov/healthliteracyonline/design-easy-scanning/use-readable-font-thats-least-16-pixels
- A11Y Collective — minimum font size: https://www.a11y-collective.com/blog/wcag-minimum-font-size/
- Frontiers — font size for older adults: https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2022.931646/full
- Josh Comeau — Pixels and accessibility (rem vs px): https://www.joshwcomeau.com/css/surprising-truth-about-pixels-and-accessibility/
- matuzo — respecting user preferences: https://www.matuzo.at/blog/writing-even-more-css-with-accessibility-in-mind-user-preferences/
- NAFI — цифровой разрыв 55+: https://nafi.ru/polls/tsifrovoy-razryv-kazhdyy-tretiy-rossiyanin-starshe-55-let-boitsya-ostatsya-za-bortom-tekhnologiy/
- RBC — рост активности 55+: https://www.rbc.ru/life/news/68efb4039a794730278bd965

**WCAG 2.2 (критерии)**
- Resize text (1.4.4) / Reflow (1.4.10): https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html
- Target Size Minimum (2.5.8): https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- Target Size (2.5.5, AAA): https://www.w3.org/WAI/WCAG21/Understanding/target-size.html
- WCAG 2.2 AA checklist (Deque): https://media.dequeuniversity.com/en/docs/web-accessibility-checklist-wcag-2.2.pdf

**Красота vs строгость**
- NN/g — Aesthetic-Usability Effect: https://www.nngroup.com/articles/aesthetic-usability-effect/
- UX Knowledge Base — что говорят исследования об Aesthetic-Usability: https://uxknowledgebase.com/aesthetic-usability-effect-what-does-the-research-say-7d5cae2d9785
- GOV.UK — Dos and don'ts on designing for accessibility: https://accessibility.blog.gov.uk/2016/09/02/dos-and-donts-on-designing-for-accessibility/
- Home Office — Moving and flashing content: https://design.homeoffice.gov.uk/accessibility/providing-alternatives/moving-and-flashing-content
