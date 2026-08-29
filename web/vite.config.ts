/// <reference types="vitest" />
import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"

// 默认代理 → wrangler dev 默认 8787
// 可用 VITE_API_TARGET 环境变量覆盖(部署到线上时改成 Workers URL)
const API_TARGET = process.env.VITE_API_TARGET ?? "http://localhost:8788";

export default defineConfig({
  plugins: [react()],
  // 全局 fs 允许(mockData 通过 import.meta.glob 加载仓库外的 data/ 目录)
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        ws: false,
      },
    },
    fs: {
      // 允许访问 web/.. 和 web/../.. 和 data/raw/data/markdown
      // vitest 不读 test.server.fs.allow,只能放根 server
      allow: ["..", "../..", "../data", "../data/raw", "../data/markdown"],
    },
  },
  build: {
    outDir: "dist",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      exclude: [
        "node_modules/",
        "dist/",
        "src/test/",
        "src/main.tsx",
        "**/*.d.ts",
      ],
    },
  },
});
