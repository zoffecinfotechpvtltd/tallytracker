import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend (main.py) serves this project's build output (frontend/dist) as
// static files - see StaticFiles mount at the bottom of main.py. In dev,
// `npm run dev` proxies /api straight to the FastAPI server on 8731 so you
// don't need to run a build for every change.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8731",
    },
  },
});
