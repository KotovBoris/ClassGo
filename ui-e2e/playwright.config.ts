import { defineConfig, devices } from "@playwright/test";

/**
 * UI-харнесс ClassGo.
 * Ожидает поднятый стек: docker compose up (mini-app на http://localhost:8080).
 * Прогоняет интерфейс на desktop и мобильных вьюпортах, делает скриншоты.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 40_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:8080",
    screenshot: "only-on-failure",
    video: "off",
    trace: "off",
  },
  // Все проекты на Chromium: покрываем узкий мобильный и широкий вьюпорт одним браузером.
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 430, height: 900 } } },
    { name: "pixel", use: { ...devices["Pixel 7"] } },
  ],
});
