import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  // сбрасываем мост MAX между тестами
  delete (globalThis as Record<string, unknown>).WebApp;
  window.history.replaceState({}, "", "/");
});
