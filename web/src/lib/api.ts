/**
 * API 客户端 + 类型定义
 *
 * 双模式:
 *   - 生产: fetch('/api/...')  → Cloudflare Workers
 *   - 开发: import mockData     → 本地 JSON
 * 通过环境变量 VITE_USE_MOCK 切换 (默认 mock=true,方便离线开发)
 */

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

// ---------- 类型 ----------

export interface Document {
  doc_id: string
  title: string
  doc_number?: string
  issuer?: string
  effective_date?: string
  chapter_count: number
  article_count: number
}

export interface Chapter {
  chapter_id: string
  doc_id: string
  number: string          // "第一章"
  title: string           // "总则"
  article_count: number
  sort_order: number
}

export interface Article {
  article_id: string
  chapter_id: string
  doc_id: string
  number: string          // "第一条"
  title?: string
  chapter_title?: string
  chapter_number?: string
}

export interface SearchHit extends Article {
  excerpt: string
  relevance?: number
}

export interface Entity {
  entity_id: string
  name: string
  type: string
  description?: string
}

export interface ChapterDetail extends Chapter {
  markdown: string
}

export interface ArticleDetail extends Article {
  markdown: string
}

// ---------- API ----------

async function fetchJson<T>(path: string): Promise<T> {
  const resp = await fetch(path)
  if (!resp.ok) throw new Error(`API ${resp.status}: ${path}`)
  return resp.json()
}

export const api = {
  // 文档列表(目录树)
  async listDocuments(): Promise<Document[]> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.listDocuments()
    }
    const r = await fetchJson<{ documents: Document[] }>("/api/documents")
    return r.documents
  },

  // 文档下的章节
  async listChapters(docId: string): Promise<Chapter[]> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.listChapters(docId)
    }
    // Workers 当前没这路由,后续加
    const r = await fetchJson<{ chapters: Chapter[] }>(`/api/documents/${docId}/chapters`)
    return r.chapters
  },

  // 单章详情(Markdown)
  async getChapter(docId: string, chapterId: string): Promise<ChapterDetail> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.getChapter(docId, chapterId)
    }
    return fetchJson<ChapterDetail>(`/api/chapter/${docId}/${chapterId}`)
  },

  // 单条详情
  async getArticle(articleId: string): Promise<ArticleDetail> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.getArticle(articleId)
    }
    return fetchJson<ArticleDetail>(`/api/article/${articleId}`)
  },

  // 检索
  async search(q: string, filters?: { docId?: string; chapterId?: string }): Promise<SearchHit[]> {
    if (!q.trim()) return []
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.search(q)
    }
    const params = new URLSearchParams({ q })
    if (filters?.docId) params.set("doc_id", filters.docId)
    if (filters?.chapterId) params.set("chapter_id", filters.chapterId)
    const r = await fetchJson<{ hits: SearchHit[] }>(`/api/search?${params}`)
    return r.hits
  },

  // 实体
  async getEntity(name: string): Promise<{ entity: Entity; articles: Article[] }> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.getEntity(name)
    }
    return fetchJson<{ entity: Entity; articles: Article[] }>(`/api/entity/${encodeURIComponent(name)}`)
  },
}

export const isMockMode = USE_MOCK