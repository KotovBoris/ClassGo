/**
 * Быстрые снимки «как видит человек» — в размере вьюпорта (не full-page),
 * чтобы агент мог оценить вёрстку глазами. Пишет в /tmp/classgo-shots.
 * Запуск: node _reviewshots.mjs   (нужен поднятый стек на :8080)
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const OUT = "/tmp/classgo-shots";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 430, height: 932 } });

// 1. Учитель: hero + журнал
await page.goto("http://localhost:8080/");
await page.waitForTimeout(1600);
await page.screenshot({ path: `${OUT}/1-teacher-top.png` });

// 2. Дашборд: статус/действия
await page.getByText("Ведомость класса").scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/2-dashboard-status.png` });

// 3. Signature: ряды мест
await page.getByText("Ряды мест").scrollIntoViewIfNeeded();
await page.waitForTimeout(300);
const seat = page.locator(".kv-seat").nth(1);
if (await seat.isVisible().catch(() => false)) await seat.click();
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/3-seats.png` });

// 4. Каталог
await page.getByRole("button", { name: "Каталог событий" }).click();
await page.waitForTimeout(1400);
await page.screenshot({ path: `${OUT}/4-catalog.png` });

// 5. Экран родителя
await page.goto("http://localhost:8080/?startapp=1");
await page.waitForTimeout(1400);
await page.screenshot({ path: `${OUT}/5-parent.png` });

await browser.close();
console.log("shots written to", OUT);
