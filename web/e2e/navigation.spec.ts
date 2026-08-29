import { test, expect } from "@playwright/test"

/**
 * 核心页面 e2e:首页 → 章节目录 → 章节详情
 * 验证页面真实可达 + 内容渲染正确 + 路由跳转通畅
 *
 * Mock 模式(USE_MOCK=true,默认)不依赖 wrangler dev
 */

test.describe("核心导航", () => {
  test("首页加载 + 显示法规库", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByRole("heading", { name: /农业饲料法规知识库/ })).toBeVisible()
    // 法规卡(feed-law-2026)
    await expect(page.getByText("中华人民共和国")).toBeVisible()
    // mock 模式标识
    await expect(page.getByText(/Mock 模式/)).toBeVisible()
  })

  test("首页 → 文档目录 → 章节列表", async ({ page }) => {
    await page.goto("/")
    await page.getByText("中华人民共和国").click()
    await expect(page.getByRole("heading", { name: /中华人民共和国/ })).toBeVisible()
    // 至少 6 章
    await expect(page.getByText("第一章")).toBeVisible()
    await expect(page.getByText("总则")).toBeVisible()
    await expect(page.getByText("审定与登记")).toBeVisible()
  })

  test("章节页渲染 markdown + 显示条文", async ({ page }) => {
    await page.goto("/doc/feed-law-2026/chapter/ch01")
    await expect(page.getByRole("heading", { name: /总则/ })).toBeVisible()
    // 第一条 文案
    await expect(page.getByText(/加强对饲料和饲料添加剂的管理/)).toBeVisible()
  })

  test("404 友好页", async ({ page }) => {
    await page.goto("/this-route-does-not-exist")
    await expect(page.getByText("404")).toBeVisible()
    await expect(page.getByText("返回首页")).toBeVisible()
  })

  test("快捷键 / 聚焦搜索框", async ({ page }) => {
    await page.goto("/")
    await page.keyboard.press("/")
    // 搜索框获得焦点(无障碍测试)
    const focused = await page.evaluate(() => document.activeElement?.tagName)
    expect(focused).toBe("INPUT")
  })
})
