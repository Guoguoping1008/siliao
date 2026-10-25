import { test, expect } from "@playwright/test"

/**
 * 搜索 + AI 问答 e2e
 * 验证检索框工作 + mock 流式答案正确显示
 */

test.describe("搜索 & AI 问答", () => {
  test("首页搜索 → 跳转 /search?q=... → 显示命中", async ({ page }) => {
    await page.goto("/")
    await page.locator("input[type=search]").fill("审定")
    await page.keyboard.press("Enter")
    await expect(page).toHaveURL(/\/search\?q=/)
    // 搜索结果页应该有命中
    await expect(page.getByText(/条结果/)).toBeVisible()
  })

  test("搜索 0 命中显示 empty state", async ({ page }) => {
    await page.goto("/search?q=zzz不存在xyz")
    await expect(page.getByText("未命中任何条文")).toBeVisible()
    await expect(page.getByText(/试试其他关键词/)).toBeVisible()
  })

  test("AI 问答页输入 → mock 流式答案", async ({ page }) => {
    await page.goto("/qa")
    await expect(page.getByRole("heading", { name: /AI 问答/ })).toBeVisible()
    await page.locator("input[type=text]").fill("饲料添加剂审定")
    await page.getByRole("button", { name: /提问/ }).click()

    // ⚠️ 不要只断言「Mock 模式」—— 那句文案在页脚上**一直都在**,
    //    断言它等于什么都没测。真正要断言的是:
    //    1) 状态栏显示检索到 N 条证据(N > 0, 说明 mock 真的走了检索)
    //    2) 证据区渲染出条文卡片
    const status = page.getByText(/当前 \d+ 条证据/)
    await expect(status).toBeVisible({ timeout: 15_000 })
    await expect(status).toContainText(/当前 [1-9]\d* 条证据/)
    // 证据区有内容
    await expect(page.getByText(/检索证据\(/)).toBeVisible({ timeout: 10_000 })
  })

  test("实体页:农业农村部能打开", async ({ page }) => {
    await page.goto("/entity/%E5%86%9C%E4%B8%9A%E5%86%9C%E6%9D%91%E9%83%A8")
    await expect(page.getByRole("heading", { name: "农业农村部" })).toBeVisible()
    await expect(page.getByText("AGENCY")).toBeVisible()
  })
})
