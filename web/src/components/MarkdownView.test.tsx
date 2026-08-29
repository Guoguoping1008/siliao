/**
 * MarkdownView 单测
 *
 * 锚点解析是核心:必须保证
 * 1. <!-- article_id: art00X --> 注释能让下一段直接拿到正确 id
 * 2. fallback:无注释时,按"第X条"顺序生成 art00X
 * 3. 标题 / 列表 / 注释三种行不会被错误归类
 */
import { describe, it, expect } from "vitest"
import { render } from "@testing-library/react"
import { MarkdownView, parse } from "./MarkdownView"

describe("parse() — 锚点解析", () => {
  it("读 article_id 注释作为段落 id", () => {
    const md = `<!-- article_id: art007 -->

第七条 国务院...`
    const blocks = parse(md, "ch02")
    const art = blocks.find(b => b.type === "p" && b.id === "art007")
    expect(art).toBeDefined()
    expect(art!.text).toContain("第七条")
  })

  it("fallback:无注释时按出现顺序生成 art00X", () => {
    const md = `# 第一章 总则

第一条 内容 A

第二条 内容 B`
    const blocks = parse(md, "ch01")
    const ids = blocks.filter(b => b.id?.startsWith("art")).map(b => b.id)
    expect(ids).toEqual(["art001", "art002"])
  })

  it("多个 article 注释连续使用,各自命中", () => {
    const md = `<!-- article_id: art001 -->

第一条 A

<!-- article_id: art002 -->

第二条 B

<!-- article_id: art003 -->

第三条 C`
    const blocks = parse(md, "ch01")
    const artBlocks = blocks.filter(b => b.id?.startsWith("art"))
    expect(artBlocks.map(b => b.id)).toEqual(["art001", "art002", "art003"])
  })

  it("h1 / h2 / h3 不带 id(只有段落才带)", () => {
    const md = `# 总则

## 第一节

### 子节`
    const blocks = parse(md, "ch01")
    expect(blocks.filter(b => b.type === "h1").every(b => !b.id)).toBe(true)
    expect(blocks.filter(b => b.type === "h2").every(b => !b.id)).toBe(true)
    expect(blocks.filter(b => b.type === "h3").every(b => !b.id)).toBe(true)
  })

  it("(一)(二) 等中文列表被识别为 li", () => {
    const md = `# 章

第一条 含列表:
(一) 申请书
(二) 配方`
    const blocks = parse(md, "ch01")
    const lis = blocks.filter(b => b.type === "li")
    expect(lis.length).toBeGreaterThanOrEqual(2)
    expect(lis[0].text).toMatch(/申请书/)
  })

  it("空 markdown 不崩溃", () => {
    expect(parse("", "ch01")).toEqual([])
  })

  it("article_id 注释后没有第X条,currentArticleId 不污染下一段", () => {
    const md = `<!-- article_id: art001 -->

非条文段落

第一条 实际第一条`
    const blocks = parse(md, "ch01")
    const art = blocks.find(b => b.text.includes("实际第一条"))
    expect(art?.id).toBe("art001")
  })
})

describe("MarkdownView 渲染", () => {
  it("解析后的 id 会成为 DOM 元素的 id 属性", () => {
    const md = `<!-- article_id: art005 -->

第五条 测试条文`
    const { container } = render(<MarkdownView source={md} chapterId="ch02" />)
    const p = container.querySelector("#art005")
    expect(p).not.toBeNull()
    expect(p?.textContent).toContain("第五条")
  })
})
