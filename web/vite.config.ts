import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` serves the app on port 5173 and forwards API calls to the backend on port 8000.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000", "/privacy": "http://127.0.0.1:8000", "/terms": "http://127.0.0.1:8000" },
  },
  // assetsInlineLimit 0: never embed small files as data: URLs, which the Content-Security-Policy refuses for fonts.
  build: { outDir: "dist", assetsDir: "assets", assetsInlineLimit: 0 },
  test: { environment: "jsdom", globals: true },
});
