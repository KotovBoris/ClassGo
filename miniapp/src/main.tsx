import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MaxUI } from "@maxhub/max-ui";
import "@maxhub/max-ui/dist/styles.css";
import "./styles.css";
import App from "./App";
import { platform } from "./max";

// Платформу передаём явно из MAX Bridge: на iOS и Android компоненты MAX UI
// рисуются по-разному. Тема берётся из prefers-color-scheme — веб-клиент MAX
// прокидывает её в iframe через color-scheme.
const p = platform();
const maxPlatform = p === "ios" ? "ios" : p === "android" ? "android" : undefined;

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <MaxUI platform={maxPlatform}>
      <App />
    </MaxUI>
  </StrictMode>,
);
