import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxies keep the app same-origin with the Python backend (single port story).
// Build outputs into backend static dir so `monoline start` serves it directly.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/src/monoline/static", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/w": "http://127.0.0.1:8787",
    },
  },
});
