import { test, expect } from "@playwright/test"

/**
 * 核心页面 e2e:首页 → 章节目录 → 章节详情
 * 验证页面真实可达 + 内容渲染正确 + 路由跳转通畅
 *
 * Mock 模式(USE_MOCK=true,默认)不依赖 wrangler dev
 *
 * ⚠️ 测试**不能硬编码语料内容** —— 语料换过(minimax/ 1021 页重建),
 *    写死 "feed-law-2026" / "第一条" 这类断言会假失败
 *    (不是代码坏了,是数据换了)。正确做法: 断言**结构性事实**
 *    (列表有内容、标题非空、markdown 渲染出段落), 不断言具体条文文本。
 */

test.describe("核心导航", () => {
  test("首页加载 + 显示法规库", async ({ page }) => {
    await page.goto("/")
    await expect(page.getByRole("heading", { name: /农业饲料法规知识库/ })).toBeVisible()
    // mock 模式标识
    await expect(page.getByText(/Mock 模式/)).toBeVisible()
    // 法规卡列表非空(文档标题来自语料, 不硬编码具体名字)
    const cards = page.locator("#library a[href^='/doc/']")
    await expect(cards.first()).toBeVisible({ timeout: 15_000 })
    expect(await cards.count()).toBeGreaterThan(0)
  })

  test("首页 → 文档目录 → 章节列表", async ({ page }) => {
    await page.goto("/")
    const firstDoc = page.locator("#library a[href^='/doc/']").first()
    // ⚠️ mock 数据是**动态 import** 的, 首屏渲染要等一会儿。
    //    不等就断言会假失败("找不到章节链接")。
    await expect(firstDoc).toBeVisible({ timeout: 15_000 })
    await firstDoc.click()
    // 文档标题 heading 可见
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    // 章节列表: 至少一条链接
    const chapterLinks = page.locator("a[href*='/chapter/']")
    await expect(chapterLinks.first()).toBeVisible({ timeout: 15_000 })
    expect(await chapterLinks.count()).toBeGreaterThan(0)
  })

  test("章节页渲染 markdown + 显示条文", async ({ page }) => {
    // 从首页点进去, 拿到真实 chapter id
    await page.goto("/")
    const firstDoc = page.locator("#library a[href^='/doc/']").first()
    await expect(firstDoc).toBeVisible({ timeout: 15_000 })
    await firstDoc.click()
    const firstChapter = page.locator("a[href*='/chapter/']").first()
    await expect(firstChapter).toBeVisible({ timeout: 15_000 })
    await firstChapter.click()

    // 章节页有 heading
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible()
    // markdown 正文渲染出了段落(不是空壳)
    const paragraphs = page.locator("p")
    expect(await paragraphs.count()).toBeGreaterThan(0)
    // 且有非空文本
    const text = (await paragraphs.first().innerText()).trim()
    expect(text.length).toBeGreaterThan(0)
  })

  test("404 友好页", async ({ page }) => {
    await page.goto("/this-route-does-not-exist")
    await expect(page.getByText("404")).toBeVisible()
    await expect(page.getByText("返回首页")).toBeVisible()
  })

  test("快捷键 / 聚焦搜索框", async ({ page }) => {
    await page.goto("/")
    // 等搜索框渲染出来再按快捷键(mock 数据异步加载)
    await expect(page.locator("input[type=search]").first()).toBeVisible({ timeout: 15_000 })
    await page.keyboard.press("/")
    // 搜索框获得焦点(无障碍测试)
    const focused = await page.evaluate(() => document.activeElement?.tagName)
    expect(focused).toBe("INPUT")
  })
})

/**
 * 运维指南入口 e2e
 *
 * 指南是 web/public/ 下的**静态 HTML**, 不是 React 路由:
 * - 用 <a href> 而不是 <Link>, 走 <Link> 会被 router 拦截成 SPA 路由 → 404
 * - 链接指向 /cloudflare-token-setup-guide (Pages 会把 .html 308 到无扩展名 URL)
 *
 * 这个测试防的是「入口链接静默失效」—— 文件被误删 / 改名 / 路由改成 <Link>
 * 都会让运维找不到指南, 但不会让任何现有测试变红。
 */
test.describe("运维指南入口", () => {
  test("首页页脚有部署运维指南入口, 指向静态 HTML", async ({ page }) => {
    await page.goto("/")
    // 页脚入口(不在 nav 里 —— 桌面导航也有一个, 用 not.closest('nav') 区分)
    const link = page.locator("a[href='/cloudflare-token-setup-guide.html']").first()
    await expect(link).toBeVisible({ timeout: 15_000 })
    await expect(link).toHaveText(/部署运维指南|运维指南/)
    // 必须是普通 <a> + 新窗口打开, 不能是 React Router 的 <Link>
    await expect(link).toHaveAttribute("target", "_blank")
    await expect(link).toHaveAttribute("rel", /noopener/)
  })

  test("运维指南入口指向的页面真的能打开(200 + 是指南本体)", async ({ page }) => {
    // 直接访问静态 HTML, 断言拿到的是指南内容而不是 SPA 的 index.html
    const resp = await page.goto("/cloudflare-token-setup-guide.html")
    expect(resp?.status()).toBe(200)
    // 指南的标志性内容
    // ⚠️ h1 里含 <br>, accessible name 会被规范化成带空格的一整串 ——
    //    用 getByRole 匹配不如直接查 h1 的文本稳。
    await expect(page.locator("h1")).toContainText("Cloudflare API Token")
    // 不能是 SPA 壳(index.html 里只有 <div id="root">)
    await expect(page.locator("#root")).toHaveCount(0)
  })
})
