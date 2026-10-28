import { test, expect } from "@playwright/test"

/**
 * 合规速查页 e2e (C1)
 *
 * ⚠️ 重点断言**「未覆盖」是一等公民**:
 *    mock 模式下没有真实规则库, 返回的必然是 not_covered。
 *    这个用例守住的是「未覆盖时**不能**显示成『合规』」——
 *    那是 ADR-004 功能设计里最关键的不变量之一。
 */

test.describe("合规速查", () => {
  test("页面可打开, 有完整表单", async ({ page }) => {
    await page.goto("/compliance")
    await expect(page.getByRole("heading", { name: /用量合规速查/ })).toBeVisible()

    // 四个必填项都在
    await expect(page.getByPlaceholder(/维生素C \/ L-抗坏血酸/)).toBeVisible()
    await expect(page.getByPlaceholder(/如: 200/)).toBeVisible()
    await expect(page.getByRole("button", { name: /查询合规判定/ })).toBeVisible()
  })

  test("空物质 → 前端校验报错, 不发请求", async ({ page }) => {
    await page.goto("/compliance")
    await page.getByRole("button", { name: /查询合规判定/ }).click()
    await expect(page.getByText(/请填写物质名称/)).toBeVisible()
  })

  test("空用量 → 报错", async ({ page }) => {
    await page.goto("/compliance")
    await page.getByPlaceholder(/维生素C \/ L-抗坏血酸/).fill("维生素C")
    // ⚠️ 不填用量 —— input[type=number] 过滤掉非数字, 填 "abc" 会被清空
    await page.getByRole("button", { name: /查询合规判定/ }).click()
    await expect(page.getByText(/请填写有效的用量数值/)).toBeVisible()
  })

  test("⚠️ 未覆盖时显示「规则未覆盖」, 绝不是「合规」", async ({ page }) => {
    await page.goto("/compliance")
    await page.getByPlaceholder(/维生素C \/ L-抗坏血酸/).fill("维生素C")
    await page.getByPlaceholder(/如: 200/).fill("200")
    await page.getByRole("button", { name: /查询合规判定/ }).click()

    // Mock 模式无规则库 → 必然 not_covered
    await expect(page.getByRole("heading", { name: "规则未覆盖" })).toBeVisible()
    // ⚠️ 核心断言: 绝不能出现「合规」结论
    //    ⚠️ 用 exact: true —— 否则会匹配到页面标题「用量合规速查」里的「合规」。
    await expect(page.getByRole("heading", { name: "合规", exact: true })).not.toBeVisible()
    await expect(page.getByRole("heading", { name: "超限", exact: true })).not.toBeVisible()
    await expect(page.getByRole("heading", { name: "禁用", exact: true })).not.toBeVisible()
  })

  test("未覆盖时提示需人工确认 + 免责标注常驻", async ({ page }) => {
    await page.goto("/compliance")
    await page.getByPlaceholder(/维生素C \/ L-抗坏血酸/).fill("维生素C")
    await page.getByPlaceholder(/如: 200/).fill("200")
    await page.getByRole("button", { name: /查询合规判定/ }).click()

    await expect(page.getByText(/需要人工确认/)).toBeVisible()
    await expect(page.getByText(/不构成监管结论/)).toBeVisible()
  })

  test("导航里有「合规速查」入口", async ({ page }) => {
    await page.goto("/")
    await expect(page.locator('a[href="/compliance"]').first()).toBeVisible()
  })
})
