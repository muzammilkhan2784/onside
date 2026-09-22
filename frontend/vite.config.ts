/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8080; proxying keeps the app same-origin so
// there is no CORS to configure and WebSockets use the same host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
      // "^/m/" not "/m": a bare prefix would also swallow the /match/ page route.
      "^/m/": "http://localhost:8080",
      "/docs": "http://localhost:8080",
      "/openapi.json": "http://localhost:8080",
      "/ws": { target: "ws://localhost:8080", ws: true },
    },
  },
  build: { sourcemap: true, chunkSizeWarningLimit: 700 },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], globals: false },
});
