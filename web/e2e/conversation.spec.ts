import { test, expect } from "@playwright/test"

/**
 * 多轮问答 e2e(C1.5)
 *
 * 验证会话页能问、能答、能显示引用校验。
 *
 * ⚠️ mock 模式下**没有指代消解**(mock 的 resolvedQuery 恒等于 question)——
 *    指代消解的规则由 worker 的 24 个单测覆盖
 *    (domain/inquiry/conversation-context.vo.test.ts)。
 *    e2e 这里只验证**界面链路**通。
 */

test.describe("多轮问答", () => {
  test("多轮问答页能打开并显示标题", async ({ page }) => {
    await page.goto("/conversation")
    await expect(page.getByRole("heading", { name: /多轮问答/ })).toBeVisible()
    await expect(page.getByRole("button", { name: /新会话/ })).toBeVisible()
  })

  test("导航里有「多轮问答」入口", async ({ page }) => {
    await page.goto("/")
    await expect(page.locator('a[href="/conversation"]').first()).toBeVisible()
  })

  test("提问 → 显示答案 + 引用校验", async ({ page }) => {
    await page.goto("/conversation")
    await page.locator("input[type=text]").fill("维生素C在猪饲料中的使用量上限")
    await page.getByRole("button", { name: /提问/ }).click()

    // 答案区出现
    await expect(page.getByText(/根据检索结果|未找到相关规定/)).toBeVisible({
      timeout: 15_000,
    })
    // 轮次计数变成 1
    await expect(page.getByText(/1 轮/)).toBeVisible({ timeout: 10_000 })
  })

  test("连续追问 → 轮次累加", async ({ page }) => {
    await page.goto("/conversation")
    const input = page.locator("input[type=text]")
    const ask = page.getByRole("button", { name: /提问/ })

    await input.fill("维生素C在猪饲料中的使用量上限")
    await ask.click()
    await expect(page.getByText(/1 轮/)).toBeVisible({ timeout: 15_000 })

    // 追问
    await input.fill("那鸡呢")
    await ask.click()
    await expect(page.getByText(/2 轮/)).toBeVisible({ timeout: 15_000 })
  })

  test("「新会话」清空轮次", async ({ page }) => {
    await page.goto("/conversation")
    await page.locator("input[type=text]").fill("饲料标签要标注什么")
    await page.getByRole("button", { name: /提问/ }).click()
    await expect(page.getByText(/1 轮/)).toBeVisible({ timeout: 15_000 })

    await page.getByRole("button", { name: /新会话/ }).click()
    await expect(page.getByText(/0 轮/)).toBeVisible({ timeout: 10_000 })
  })

  test("空输入时提问按钮禁用", async ({ page }) => {
    await page.goto("/conversation")
    await expect(page.getByRole("button", { name: /提问/ })).toBeDisabled()
  })
})
