/**
 * Компактный снимок каталога с раскрытой формой оформления — ровно то,
 * что видит человек в кадре вьюпорта (430x932), а не длинный full-page
 * (full-page ~8800px ронял просмотр изображений). Пишет в /tmp.
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const OUT = "/tmp/classgo-shots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 430, height: 932 } });

await page.goto("http://localhost:8080/");
await page.waitForTimeout(1500);
await page.getByRole("button", { name: "Каталог событий" }).click();
await page.waitForTimeout(1500);

// выбрать событие (клик по строке) — форма раскрывается inline под ним
await page.locator(".kv-eventbtn").nth(1).click();
await page.waitForTimeout(500);

// прокрутить так, чтобы событие и раскрытая форма попали в кадр
await page.locator(".kv-inline-order").scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/catalog-form.png` });

await browser.close();
console.log("ok ->", `${OUT}/catalog-form.png`);
