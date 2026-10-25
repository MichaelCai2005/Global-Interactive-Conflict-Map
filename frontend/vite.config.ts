import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
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
  // GitHub Pages serves the site under /<repo>/; the Pages workflow sets BASE_PATH.
  base: process.env.BASE_PATH ?? "/",
  plugins: [react(), tailwindcss()],
  // "@/" is src/, the import alias shadcn/ui components use.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { port: 5173, proxy: api },
  preview: { port: 4173, proxy: api },
  // MapLibre alone is about 1 MB minified, and every page needs it; Radix (under the
  // shadcn/ui components) and the panel library add a little more.
  build: { chunkSizeWarningLimit: 1800 },
  test: { environment: "jsdom" },
});
