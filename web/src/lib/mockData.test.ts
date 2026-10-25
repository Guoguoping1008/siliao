/**
 * mockData 单测
 *
 * mockData 是 mock 模式下的数据源,被 5 个页面调用。
 * 它的稳定性直接决定 mock 模式用户体验。
 *
 * ⚠️ 测试**不能硬编码 ID** —— 语料换了(minimax/ 1021 页重建)ID 全变,
 *    硬编码的测试会假失败(不是代码坏了,是数据换了)。
 *    正确做法: 从 listDocuments()/listChapters() 拿真实 ID 再断言。
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

  it("title 是可读标题(不等于 doc_id)", async () => {
    const docs = await mockApi.listDocuments()
    // 至少有一条 title 与 doc_id 不同(doc_id 是路径 slug, title 是法规名)
    expect(docs.some(d => d.title && d.title !== d.doc_id)).toBe(true)
  })

  it("doc_id 全局唯一", async () => {
    const docs = await mockApi.listDocuments()
    const ids = docs.map(d => d.doc_id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe("mockApi.listChapters", () => {
  let docId = ""

  beforeAll(async () => {
    const docs = await mockApi.listDocuments()
    // 选一个章节最多的文档, 保证有章节可测
    docId = [...docs].sort((a, b) => b.chapter_count - a.chapter_count)[0].doc_id
  })

  it("返回章节按 sort_order 升序", async () => {
    const chapters = await mockApi.listChapters(docId)
    expect(chapters.length).toBeGreaterThan(0)
    for (let i = 1; i < chapters.length; i++) {
      expect(chapters[i].sort_order).toBeGreaterThanOrEqual(chapters[i - 1].sort_order)
    }
  })

  it("不返回 markdown 字段(节省传输)", async () => {
    const chapters = await mockApi.listChapters(docId)
    expect(chapters[0]).not.toHaveProperty("markdown")
  })
})

describe("mockApi.getChapter", () => {
  it("返回完整 markdown", async () => {
    const docs = await mockApi.listDocuments()
    const docId = [...docs].sort((a, b) => b.chapter_count - a.chapter_count)[0].doc_id
    const chapters = await mockApi.listChapters(docId)
    const ch = chapters.find(c => c.article_count > 0) ?? chapters[0]
    const detail = await mockApi.getChapter(docId, ch.chapter_id)
    expect(detail.markdown.length).toBeGreaterThan(0)
    expect(detail.chapter_id).toBe(ch.chapter_id)
  })

  it("不存在章节抛错", async () => {
    const docs = await mockApi.listDocuments()
    const docId = docs[0].doc_id
    await expect(mockApi.getChapter(docId, "__no_such_chapter__")).rejects.toThrow(/not found/)
  })
})

describe("mockApi.getArticle", () => {
  it("返回单条 markdown", async () => {
    // 从 search 结果拿真实 article_id —— 不要硬编码, 也不要从章节 markdown 里
    // 正则猜 ID (章节 markdown 里是 "### 第一条" 这种标题, 不含 article_id)。
    const hits = await mockApi.search("饲料添加剂")
    expect(hits.length).toBeGreaterThan(0)
    const artId = hits[0].article_id

    const detail = await mockApi.getArticle(artId)
    expect(detail.markdown.length).toBeGreaterThan(0)
    expect(detail.article_id).toBe(artId)
    expect(detail.doc_id).toBeTruthy()
  })

  it("不存在条文抛错", async () => {
    await expect(mockApi.getArticle("__no_such_article__")).rejects.toThrow(/not found/)
  })
})

describe("mockApi.search", () => {
  beforeAll(async () => {
    // 预热:第一次调用会触发 markdown 模块加载
    await mockApi.search("init")
  })

  it("找到的条目 excerpt 含 query 子串", async () => {
    const hits = await mockApi.search("饲料添加剂")
    expect(hits.length).toBeGreaterThan(0)
    for (const h of hits) {
      // excerpt 是围绕 query 截取的, 必须含 query 词
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
