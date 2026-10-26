// «Дебажный браузер»: открывает ai.vk.team с cookie пользователя, логирует все
// запросы к /api/v1/ и печатает ответы по расходам. Запуск:
//   cd ui-e2e && node _vkusage.mjs
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const CURL = path.resolve(process.env.VK_CURL || "../../../.secrets/vk-ai-api-curl.txt");
const src = fs.readFileSync(CURL, "utf8");
const m = src.match(/-H 'Cookie: (.*?)' \\\n/s);
if (!m) throw new Error("не нашёл Cookie в " + CURL);
const cookies = m[1]
  .split(";")
  .map((kv) => kv.trim())
  .filter(Boolean)
  .map((kv) => {
    const i = kv.indexOf("=");
    return { name: kv.slice(0, i), value: kv.slice(i + 1), domain: "ai.vk.team", path: "/" };
  });
console.log("cookies:", cookies.map((c) => c.name).join(", "));

const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "ru-RU" });
await ctx.addCookies(cookies);
const page = await ctx.newPage();

page.on("request", (r) => {
  const u = r.url();
  if (u.includes("/api/v1/")) {
    console.log("→", r.method(), u.replace("https://api.ai.vk.team", ""), r.postData()?.slice(0, 200) ?? "");
  }
});
page.on("response", async (r) => {
  const u = r.url();
  if (u.includes("usage") || u.includes("/api/v1/me")) {
    let body = "";
    try {
      body = (await r.text()).slice(0, 600);
    } catch {}
    console.log("←", r.status(), u.replace("https://api.ai.vk.team", ""), body);
  }
});

await page.goto("https://ai.vk.team", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(6000);

// список ссылок — найдём маршрут страницы статистики
const links = await page.$$eval("a[href]", (as) => Array.from(new Set(as.map((a) => a.getAttribute("href")))));
console.log("ссылки:", links.filter(Boolean).slice(0, 30).join(" | "));

// пробуем типовые маршруты статистики
for (const route of ["/profile", "/usage", "/statistics", "/stats", "/settings", "/account"]) {
  try {
    const resp = await page.goto("https://ai.vk.team" + route, { waitUntil: "domcontentloaded", timeout: 20000 });
    const title = await page.title();
    console.log(`route ${route} -> HTTP ${resp?.status()} title="${title}"`);
    await page.waitForTimeout(2500);
  } catch (e) {
    console.log(`route ${route} -> ошибка ${e.message}`);
  }
}

console.log("итог URL:", page.url(), "title:", await page.title());
await browser.close();
