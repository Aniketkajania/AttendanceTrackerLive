import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Proxy means no CORS issues and image URLs like /snapshots/... just work
const api = "http://localhost:8000";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": api, "/snapshots": api, "/photos": api } },
});
