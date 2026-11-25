import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ["panel.workkit-studio.ru"],
    proxy: { "/api": { target: "http://api:18080", changeOrigin: true } },
  },
});
