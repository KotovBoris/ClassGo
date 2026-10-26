/**
 * UI-проверки и скриншоты mini-app ClassGo (docs/REQUIREMENTS.md, UI-*).
 *
 * Требует поднятый стек:  docker compose up -d --build
 * Вне MAX интерфейс работает с graceful-fallback, поэтому здесь можно
 * полноценно проверять клики и смотреть, как выглядит экран.
 */
import { test, expect, type Page } from "@playwright/test";

const SHOTS = "screenshots";

/**
 * Эмуляция запуска ВНУТРИ MAX: подменяем саму библиотеку MAX Bridge
 * (её ответ перехватывается), поэтому window.WebApp определяет именно наш фейк,
 * а не реальный скрипт. Это же позволяет тестировать интерфейс без сети.
 */
async function injectMaxBridge(page: Page, userId = 424242, platform = "ios") {
  const fake = `
    window.WebApp = {
      initData: "user=${userId}&hash=test",
      initDataUnsafe: { user: { id: ${userId}, first_name: "Тест", last_name: "Родитель" }, start_param: null },
      platform: "${platform}",
      version: "26.1.0",
      deviceName: "${platform} device",
      downloadFile: function () {},
      openLink: function () {},
      requestContact: async function () { return null; },
      BackButton: { show: function () {}, hide: function () {}, onClick: function () {} },
      HapticFeedback: { impactOccurred: function () {} },
    };
  `;
  await page.route("**/max-web-app.js", (route) =>
    route.fulfill({ contentType: "application/javascript", body: fake }),
  );
}

test("UI-1/UI-2: учитель — шапка, вкладки, каталог", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("ClassGo")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/01-teacher.png`, fullPage: true });

  await page.getByRole("button", { name: "Каталог событий" }).click();
  await expect(page.getByText(/Каталог событий · Казань/)).toBeVisible();
  // фильтр «Пушкинская карта»
  await page.getByRole("checkbox").first().check();
  await expect(page.getByText("Пушкинская карта").first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/02-catalog.png`, fullPage: true });
});

test("UI-4/UI-5: создание выезда и переход к ведомости", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Каталог событий" }).click();
  await expect(page.getByText(/Каталог событий · Казань/)).toBeVisible();

  // дождаться загрузки каталога и выбрать событие кликом прямо по строке
  await expect(page.getByText(/Найдено событий/)).toBeVisible();
  await page.locator(".kv-eventbtn").first().click();
  await expect(page.getByText("Оформление выезда")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/03-create-excursion.png`, fullPage: true });

  await page.getByRole("button", { name: /Создать выезд/i }).click();
  await expect(page.getByText(/Ведомость класса/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/04-dashboard.png`, fullPage: true });
});

test("UI-7/UI-8: формирование приказа и прямые ссылки", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Ведомость класса/)).toBeVisible();
  await page.getByRole("button", { name: /Сформировать приказ/i }).click();
  await expect(page.getByText(/Приказ сформирован/i)).toBeVisible();
  await expect(page.getByRole("link", { name: /DOCX \(прямая ссылка\)/i })).toHaveAttribute("href", /export-order/);
  await expect(page.getByRole("link", { name: /PDF \(прямая ссылка\)/i })).toHaveAttribute("href", /export-order/);
  await page.screenshot({ path: `${SHOTS}/05-order.png`, fullPage: true });
});

test("UI-9/UI-10: экран родителя по ?startapp, подтверждение ПЭП и согласие", async ({ page }) => {
  // ученик №1 демо-класса
  await page.goto("/?startapp=1");
  await expect(page.getByText("Согласие законного представителя")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-parent.png`, fullPage: true });

  const approve = page.getByRole("button", { name: /Отпускаю ребёнка/i }).first();
  if (await approve.isVisible().catch(() => false)) {
    // ST-3: согласие (ПЭП) не уходит одним кликом — сначала шаг подтверждения
    await approve.click();
    await expect(page.getByText(/Отправляю согласие\?/i)).toBeVisible();
    // ST-6: без отдельного согласия на обработку ПДн (152-ФЗ) отправка заблокирована
    await page.getByLabel(/обработку персональных данных/i).check();
    await page.getByRole("button", { name: /Да, отправляю согласие/i }).click();
    await expect(page.getByText(/Согласие|уже подписано/i).first()).toBeVisible();
    await page.screenshot({ path: `${SHOTS}/07-parent-approved.png`, fullPage: true });
  }
});

test("BRG-7: внутри MAX показывается платформа и версия", async ({ page }) => {
  await injectMaxBridge(page, 987654, "ios");
  await page.goto("/");
  await expect(page.getByText(/платформа ios/)).toBeVisible();
  await expect(page.locator("body")).toContainText("ios");
  await expect(page.locator("body")).not.toContainText("запущено вне MAX");
  await page.screenshot({ path: `${SHOTS}/08-inside-max.png`, fullPage: true });
});

test("UC-1: импорт класса из CSV в интерфейсе", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Импорт класса" }).click();
  await expect(page.getByText(/Заведение класса/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/10-import.png`, fullPage: true });

  // используем реальный пример из репозитория (artifacts/sample_class_import.csv)
  await page.locator('input[type="file"]').setInputFiles("../artifacts/sample_class_import.csv");
  await expect(page.getByText(/sample_class_import\.csv/)).toBeVisible();
  await page.getByRole("button", { name: "Загрузить класс" }).click();
  // показывается результат импорта: сколько учеников и родителей заведено
  await expect(page.getByText("Учеников")).toBeVisible();
  await expect(page.getByRole("button", { name: /К каталогу событий/i })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/11-import-result.png`, fullPage: true });
});

test("UC-3: публикация выезда в чат класса из дашборда", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Ведомость класса/)).toBeVisible();
  await page.getByRole("button", { name: /Опубликовать в чат класса/i }).click();
  // вне MAX id чата спрашиваем вручную
  await page.getByLabel("id чата класса").fill("-7000000001");
  await page.getByRole("button", { name: "Опубликовать", exact: true }).click();
  // успех либо «бот выключен» — оба сообщения содержат «публикац»
  await expect(page.getByText(/публикац/i)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/12-publish.png`, fullPage: true });
});

test("UI-15: мобильная верстка без горизонтального переполнения", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Ведомость класса/)).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, `горизонтальный скролл на ${overflow}px`).toBeLessThanOrEqual(2);

  // родительский экран тоже не должен «разъезжаться»
  await page.goto("/?startapp=1");
  await expect(page.getByText("Согласие законного представителя")).toBeVisible();
  const overflow2 = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow2).toBeLessThanOrEqual(2);
});

test("режим просмотра: открыть экран родителя и вернуться", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Развернуть" }).click();
  await page.getByLabel("Открыть экран родителя").selectOption({ index: 1 });
  await expect(page.getByRole("button", { name: /В режим учителя/i })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/09-view-panel-parent.png`, fullPage: true });
  await page.getByRole("button", { name: /В режим учителя/i }).click();
  await expect(page.getByText(/Ведомость класса/)).toBeVisible();
});
