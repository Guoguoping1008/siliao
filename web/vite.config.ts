import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 默认代理 → wrangler dev 默认 8787
// 可用 VITE_API_TARGET 环境变量覆盖(部署到线上时改成 Workers URL)
const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8788";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        // SSE streaming 不能被缓存
        ws: false,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
