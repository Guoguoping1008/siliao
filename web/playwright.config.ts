import { defineConfig, devices } from "@playwright/test"

/**
 * Playwright e2e 配置
 *
 * 设计:
 * - webServer: 自动起 vite dev(无需手动 npm run dev)
 * - reuseExistingServer: 本地开发时如果 vite 已起,直接复用
 * - reporter: list (CI) + html (本地)
 * - 失败自动截图 + trace 上传到 artifacts
 */

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,           // 单用例 30s 超时
  expect: { timeout: 5_000 }, // 断言 5s 超时(默认 5s)
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never", outputFolder: "../../test-results/playwright-report" }]]
    : [["list"], ["html", { open: "never", outputFolder: "../../test-results/playwright-report" }]],

  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",  // 失败时记录 trace
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    // 移动端(可选,先不启用以节省跑测时间)
    // {
    //   name: "mobile-safari",
    //   use: { ...devices["iPhone 13"] },
    // },
  ],

  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
  },
})
