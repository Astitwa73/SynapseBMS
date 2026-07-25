import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The dashboard is developed against the Vite dev server and shipped as a static
// bundle that FastAPI serves, so the demo runs from one command and one URL.
// Proxying in development keeps the API origin identical in both modes, which
// means no environment-specific base URL anywhere in the client.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../backend/api/static", emptyOutDir: true },
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
