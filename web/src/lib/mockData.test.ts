/**
 * mockData 单测
 *
 * mockData 是 mock 模式下的数据源,被 5 个页面调用。
 * 它的稳定性直接决定 mock 模式用户体验。
 */
import { describe, it, expect, beforeAll } from "vitest"
import { mockApi } from "./mockData"

describe("mockApi.listDocuments", () => {
  it("返回至少 1 部法规", async () => {
    const docs = await mockApi.listDocuments()
    expect(docs.length).toBeGreaterThan(0)
    expect(docs[0]).toHaveProperty("doc_id")
    expect(docs[0]).toHaveProperty("chapter_count")
    expect(docs[0]).toHaveProperty("article_count")
  })

  it("title 字段会被注水(从 raw 第一行读)", async () => {
    const docs = await mockApi.listDocuments()
    // feed-law-2026.md 第一行是"中华人民共和国农业农村部令"
    expect(docs[0].title.length).toBeGreaterThan(0)
    expect(docs[0].title).not.toBe(docs[0].doc_id)
  })
})

describe("mockApi.listChapters", () => {
  it("返回章节按 sort_order 升序", async () => {
    const chapters = await mockApi.listChapters("feed-law-2026")
    expect(chapters.length).toBeGreaterThan(0)
    for (let i = 1; i < chapters.length; i++) {
      expect(chapters[i].sort_order).toBeGreaterThanOrEqual(chapters[i - 1].sort_order)
    }
  })

  it("不返回 markdown 字段(节省传输)", async () => {
    const chapters = await mockApi.listChapters("feed-law-2026")
    expect(chapters[0]).not.toHaveProperty("markdown")
  })
})

describe("mockApi.getChapter", () => {
  it("返回完整 markdown", async () => {
    const detail = await mockApi.getChapter("feed-law-2026", "ch01")
    expect(detail.markdown).toContain("第一章")
    expect(detail.markdown).toContain("第一条")
  })

  it("不存在章节抛错", async () => {
    await expect(mockApi.getChapter("feed-law-2026", "ch99")).rejects.toThrow(/not found/)
  })
})

describe("mockApi.getArticle", () => {
  it("返回单条 markdown", async () => {
    const detail = await mockApi.getArticle("art001")
    expect(detail.markdown).toContain("第一条")
    expect(detail.article_id).toBe("art001")
  })

  it("不存在条文抛错", async () => {
    await expect(mockApi.getArticle("art999")).rejects.toThrow(/not found/)
  })
})

describe("mockApi.search", () => {
  beforeAll(async () => {
    // 预热:第一次调用会触发 markdown 模块加载
    await mockApi.search("init")
  })

  it("找到的条目包含 query 子串", async () => {
    const hits = await mockApi.search("饲料添加剂")
    expect(hits.length).toBeGreaterThan(0)
    for (const h of hits) {
      expect(h.excerpt.toLowerCase()).toContain("饲料添加剂")
    }
  })

  it("按相关度(命中次数)降序排序", async () => {
    const hits = await mockApi.search("饲料")
    for (let i = 1; i < hits.length; i++) {
      expect(hits[i - 1].relevance ?? 0).toBeGreaterThanOrEqual(hits[i].relevance ?? 0)
    }
  })

  it("空 query 返回空数组", async () => {
    expect(await mockApi.search("")).toEqual([])
    expect(await mockApi.search("   ")).toEqual([])
  })
})

describe("mockApi.getEntity", () => {
  it("返回实体 + 关联条文", async () => {
    const { entity, articles } = await mockApi.getEntity("农业农村部")
    expect(entity.name).toBe("农业农村部")
    expect(entity.type).toBe("AGENCY")
    expect(articles.length).toBeGreaterThan(0)
  })

  it("不存在实体抛错", async () => {
    await expect(mockApi.getEntity("不存在的实体xyz")).rejects.toThrow(/not found/)
  })
})
