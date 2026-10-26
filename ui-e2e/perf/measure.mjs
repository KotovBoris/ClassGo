/**
 * Замеры производительности ClassGo (ST-8 «Задача 2»).
 *
 * Собирает объективные цифры:
 *   1) время и разброс ответов ключевых API (excursions, culture-events, dashboard,
 *      export-order) — последовательно, с прогревом;
 *   2) Web Vitals локального mini-app (LCP, TBT, CLS, DOMContentLoaded/load,
 *      объём переданных JS/CSS) на двух сценариях: учитель и родитель.
 *
 * Требует поднятый стек:  docker compose up -d --build   (mini-app на :8080)
 *
 *   node perf/measure.mjs           # только печать цифр + JSON-отчёт
 *   node perf/measure.mjs --budget  # дополнительно проверить performance budget
 *
 * Отчёт сохраняется в perf/last-run.json, чтобы цифры «до/после» можно было
 * сравнивать, не переписывая их руками.
 */
import { chromium } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE_URL || "http://localhost:8080";
const CHECK_BUDGET = process.argv.includes("--budget");
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), "last-run.json");

/** Пороговые значения (бюджет) — заведомо достижимы на локальном стеке. */
export const BUDGET = {
  lcpMs: 2500,
  tbtMs: 300,
  cls: 0.1,
  apiP95Ms: 500,
  exportOrderMs: 1500,
  initialJsKb: 120,
  cssKb: 40,
};

/** Ключевые API: путь + метод (POST / export-order создаёт файл). */
const API_ENDPOINTS = [
  { name: "GET /api/v1/excursions", method: "GET", path: "/api/v1/excursions" },
  { name: "GET /api/v1/culture-events", method: "GET", path: "/api/v1/culture-events?city=%D0%9A%D0%B0%D0%B7%D0%B0%D0%BD%D1%8C&sort=date&order_by=asc" },
  { name: "GET /dashboard", method: "GET", path: "/api/v1/excursions/1/dashboard" },
  { name: "POST /export-order", method: "POST", path: "/api/v1/excursions/1/export-order?fmt=docx" },
];

function percentile(values, p) {
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, idx)];
}

async function measureApi(endpoint, iterations = 7) {
  const times = [];
  for (let i = 0; i < iterations; i++) {
    const started = performance.now();
    const res = await fetch(`${BASE}${endpoint.path}`, { method: endpoint.method });
    await res.arrayBuffer(); // читаем тело, иначе замеряем только заголовки
    if (!res.ok) throw new Error(`${endpoint.name}: HTTP ${res.status}`);
    times.push(performance.now() - started);
  }
  // первый запрос — прогрев (JIT, коннект), в статистику не берём
  const warm = times.slice(1);
  return {
    name: endpoint.name,
    samples: times.length,
    minMs: +Math.min(...warm).toFixed(1),
    medianMs: +percentile(warm, 50).toFixed(1),
    p95Ms: +percentile(warm, 95).toFixed(1),
    maxMs: +Math.max(...warm).toFixed(1),
  };
}

/** Хук для Web Vitals: LCP, CLS и суммарное время длинных задач (TBT). */
const vitalsHook = () => {
  window.__vitals = { lcp: 0, cls: 0, tbt: 0, longTasks: 0 };
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) window.__vitals.lcp = entry.startTime;
    }).observe({ type: "largest-contentful-paint", buffered: true });
  } catch { /* Safari/старый Chromium */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__vitals.cls += entry.value;
      }
    }).observe({ type: "layout-shift", buffered: true });
  } catch { /* ignore */ }
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__vitals.longTasks += 1;
        window.__vitals.tbt += Math.max(0, entry.duration - 50);
      }
    }).observe({ type: "longtask", buffered: true });
  } catch { /* ignore */ }
};

async function measurePage(page, label, url) {
  await page.addInitScript(vitalsHook);
  await page.goto(`${BASE}${url}`, { waitUntil: "load" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1200); // даём догореть LCP/длинным задачам

  const nav = await page.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0] || {};
    return {
      domContentLoadedMs: +(n.domContentLoadedEventEnd || 0).toFixed(1),
      loadMs: +(n.loadEventEnd || n.duration || 0).toFixed(1),
      requestStartMs: +(n.requestStart || 0).toFixed(1),
    };
  });
  const vitals = await page.evaluate(() => window.__vitals || { lcp: 0, cls: 0, tbt: 0 });
  const resources = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((r) => ["script", "link", "css", "fetch"].includes(r.initiatorType) || /\.(js|css|woff2)$/.test(r.name))
      .map((r) => ({ name: r.name, transferSize: r.transferSize, encodedBodySize: r.encodedBodySize })),
  );
  const jsKb = resources.filter((r) => r.name.endsWith(".js")).reduce((s, r) => s + r.transferSize, 0) / 1024;
  const cssKb = resources.filter((r) => r.name.endsWith(".css")).reduce((s, r) => s + r.transferSize, 0) / 1024;

  return {
    label,
    url,
    ...nav,
    lcpMs: +vitals.lcp.toFixed(1),
    tbtMs: +vitals.tbt.toFixed(1),
    cls: +vitals.cls.toFixed(4),
    jsTransferKb: +jsKb.toFixed(1),
    cssTransferKb: +cssKb.toFixed(1),
    jsRequests: resources.filter((r) => r.name.endsWith(".js")).length,
  };
}

function checkBudgets(report) {
  const failures = [];
  const check = (name, value, limit, unit) => {
    const ok = value <= limit;
    console.log(`  ${ok ? "✓" : "✗"} ${name}: ${value}${unit} (бюджет ${limit}${unit})`);
    if (!ok) failures.push(`${name}: ${value}${unit} > ${limit}${unit}`);
  };
  console.log("\n=== Проверка performance budget ===");
  for (const p of report.pages) {
    check(`${p.label}: LCP`, p.lcpMs, BUDGET.lcpMs, "ms");
    check(`${p.label}: TBT`, p.tbtMs, BUDGET.tbtMs, "ms");
    check(`${p.label}: CLS`, p.cls, BUDGET.cls, "");
  }
  for (const a of report.api) {
    const limit = a.name.includes("export-order") ? BUDGET.exportOrderMs : BUDGET.apiP95Ms;
    check(`${a.name}: p95`, a.p95Ms, limit, "ms");
  }
  const teacher = report.pages.find((p) => p.label === "teacher");
  if (teacher) {
    check("initial JS (gzip)", teacher.jsTransferKb, BUDGET.initialJsKb, "kB");
    check("CSS (gzip)", teacher.cssTransferKb, BUDGET.cssKb, "kB");
  }
  return failures;
}

async function main() {
  const report = { when: new Date().toISOString(), base: BASE, api: [], pages: [] };

  console.log(`Замеры API (${BASE}):`);
  for (const endpoint of API_ENDPOINTS) {
    const result = await measureApi(endpoint);
    report.api.push(result);
    console.log(
      `  ${result.name.padEnd(28)} min ${result.minMs} / median ${result.medianMs} / p95 ${result.p95Ms} / max ${result.maxMs} ms`,
    );
  }

  const browser = await chromium.launch();
  const deviceOptions =
    process.env.MOBILE === "0"
      ? { viewport: { width: 430, height: 900 }, deviceScaleFactor: 1 }
      : { ...(await import("@playwright/test")).devices["Pixel 7"] };

  console.log("\nЗамеры страницы (Web Vitals):");
  // Каждый экран меряем в СВЕЖЕМ контексте: иначе второй замер берёт JS/CSS из кэша
  // и transferSize обнуляется — цифры «до/после» были бы несравнимы.
  for (const [label, url] of [
    ["teacher", "/"],
    ["parent", "/?startapp=1"],
  ]) {
    const context = await browser.newContext(deviceOptions);
    const page = await context.newPage();
    const result = await measurePage(page, label, url);
    report.pages.push(result);
    console.log(
      `  ${label.padEnd(8)} DCL ${result.domContentLoadedMs} / load ${result.loadMs} ms · LCP ${result.lcpMs} / TBT ${result.tbtMs} ms · CLS ${result.cls} · JS ${result.jsTransferKb} kB (${result.jsRequests} req) · CSS ${result.cssTransferKb} kB`,
    );
    await context.close();
  }

  await browser.close();

  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, `${JSON.stringify(report, null, 2)}\n`);
  console.log(`\nОтчёт: ${OUT}`);

  if (CHECK_BUDGET) {
    const failures = checkBudgets(report);
    if (failures.length) {
      console.error(`\n❌ Бюджет не выполнен (${failures.length}):\n - ${failures.join("\n - ")}`);
      process.exit(1);
    }
    console.log("\n✅ Все бюджеты выполнены");
  }
}

main().catch((error) => {
  console.error("Ошибка замеров:", error);
  process.exit(1);
});
