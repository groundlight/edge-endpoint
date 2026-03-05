import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const EDGE_ENDPOINT = process.env.EDGE_ENDPOINT_URL || "http://localhost:30101";

export default defineConfig({
  plugins: [react()],
  base: "/status/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    proxy: {
      "/status/metrics.json": EDGE_ENDPOINT,
      "/status/gpu.json": EDGE_ENDPOINT,
      "/status/static/icon_gold_dark.svg": EDGE_ENDPOINT,
      "/status/static/favicon.ico": EDGE_ENDPOINT,
    },
  },
});
