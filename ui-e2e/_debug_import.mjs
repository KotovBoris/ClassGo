import { chromium } from "@playwright/test";

const base = process.env.BASE_URL || "http://localhost:8080";
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => console.log("[console]", m.type(), m.text()));
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
page.on("requestfailed", (r) => console.log("[reqfail]", r.url(), r.failure()?.errorText));
page.on("response", async (r) => {
  if (r.url().includes("/api/")) console.log("[resp]", r.status(), r.url());
});

await page.goto(base + "/");
await page.getByRole("button", { name: "Импорт класса" }).click();
await page.waitForTimeout(500);
await page.locator('input[type="file"]').setInputFiles("../artifacts/sample_class_import.csv");
await page.waitForTimeout(500);
console.log("--- filename text present:", await page.getByText(/sample_class_import\.csv/).count());
console.log("--- dropzone text:", (await page.locator(".kv-dropzone").innerText()).replace(/\n/g, " | "));
const btn = page.getByRole("button", { name: "Загрузить класс" });
console.log("--- button disabled:", await btn.isDisabled());
await btn.click();
await page.waitForTimeout(2000);
console.log("--- alerts:", await page.locator(".kv-alert").allInnerTexts());
console.log("--- body has 'Учеников':", (await page.locator("body").innerText()).includes("Учеников"));
console.log("--- body tail:\n", (await page.locator("body").innerText()).slice(-800));
await browser.close();
