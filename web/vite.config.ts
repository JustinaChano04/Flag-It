/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI calls /api/...; in development Vite forwards that to the API (uvicorn on port 8000),
// so the browser sees one origin and the API needs no CORS settings.
const API = process.env.FLAG_IT_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: { "/api": { target: API, rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
