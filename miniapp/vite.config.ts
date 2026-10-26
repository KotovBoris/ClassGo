import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base './' — чтобы собранные ассеты корректно грузились при любом пути размещения.
// В dev-режиме API и вебхук проксируются на backend (localhost:8000).
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        // React и MAX UI меняются редко — в отдельный vendor-чанк: он кэшируется
        // надолго, а код экранов грузится лениво (см. App.tsx), поэтому начальный
        // JS меньше и обновление экрана не инвалидирует vendor.
        manualChunks: {
          vendor: ["react", "react-dom", "react/jsx-runtime"],
          maxui: ["@maxhub/max-ui"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/webhook": "http://localhost:8000",
      "/healthz": "http://localhost:8000",
    },
  },
});
