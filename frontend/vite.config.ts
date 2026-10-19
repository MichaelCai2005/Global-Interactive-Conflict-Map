import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs separately (uvicorn on :8000); /api is proxied to it so the
// browser sees one origin and the backend needs no CORS setup.
const api = {
  "/api": {
    target: process.env.API_URL ?? "http://localhost:8000",
    changeOrigin: true,
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: api },
  preview: { port: 4173, proxy: api },
  // MapLibre alone is about 1 MB minified, and every page needs it.
  build: { chunkSizeWarningLimit: 1600 },
  test: { environment: "jsdom" },
});
