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
  article_number?: string
  chapter_number?: string
  chapter_title?: string
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

// RAG QA streaming 事件类型(对应 Worker 的 SSE)
export interface QAMetaEvent {
  question: string
  retrieval: SearchHit[]
}

export interface QAChunkEvent {
  delta: string
}

export interface CitationItem {
  ref: number
  article_id?: string
  chapter_id?: string
  doc_id?: string
  chapter_title?: string
  chapter_number?: string
  article_number?: string
  title?: string
  excerpt?: string
  valid: boolean
}

export interface QADoneEvent {
  citations: CitationItem[]
}

export interface QAAnswerFull {
  question: string
  answer: string
  citations: CitationItem[]
  retrieval: SearchHit[]
  elapsed_ms: number
}

// ---------- API ----------

/**
 * 统一 API 错误:带 status + endpoint + 原始 body
 * 前端组件用 instanceof ApiError 区分网络错误 / 业务错误
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly endpoint: string,
    public readonly body?: string
  ) {
    super(message)
    this.name = "ApiError"
  }
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(path, init)
  } catch (e) {
    // 网络层错误(offline / CORS / DNS)
    throw new ApiError(
      `网络错误: ${(e as Error).message}`,
      0,
      path
    )
  }
  if (!resp.ok) {
    const body = await resp.text().catch(() => "")
    throw new ApiError(
      `API ${resp.status}: ${path}`,
      resp.status,
      path,
      body.slice(0, 500)
    )
  }
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

  // RAG 问答(同步):返回完整 JSON,适用于不要求 streaming 的场景
  async qa(question: string): Promise<QAAnswerFull> {
    if (USE_MOCK) {
      // mock 模式无 LLM,固定模板答案
      return {
        question,
        answer: `Mock 模式:未配置 LLM API Key,无法生成答案。请在生产模式下(VITE_USE_MOCK=false)提问 "${question}"`,
        citations: [],
        retrieval: [],
        elapsed_ms: 0,
      }
    }
    const r = await fetchJson<QAAnswerFull>("/api/qa", {
      method: "POST",
      body: JSON.stringify({ q: question }),
    } as any)
    return r
  },

  // RAG 问答(streaming):用 fetch + ReadableStream 订阅 SSE(EventSource 不支持 POST body)
  // handlers: { onMeta, onChunk, onDone, onError }
  // 返回 abort 函数
  qaStream(
    question: string,
    handlers: {
      onMeta?: (e: QAMetaEvent) => void
      onChunk?: (e: QAChunkEvent) => void
      onDone?: (e: QADoneEvent) => void
      onError?: (e: { message?: string; status?: number }) => void
    }
  ): () => void {
    if (USE_MOCK) {
      // mock 模式下不真接 LLM,直接拼一段固定 answer 模拟 streaming
      mockStreamFallback(question, handlers)
      return () => undefined
    }
    return consumeQAStream(question, handlers)
  },
}

// Mock 模式下的 RAG streaming 模拟:无 LLM,直接基于检索结果拼一段模板答案
function mockStreamFallback(
  question: string,
  handlers: {
    onMeta?: (e: any) => void
    onChunk?: (e: any) => void
    onDone?: (e: any) => void
    onError?: (e: any) => void
  }
) {
  // 异步执行,避免阻塞调用方
  setTimeout(() => {
    handlers.onMeta?.({ question, retrieval: [] })
    const text = `Mock 模式:未配置 LLM API Key,无法生成答案。请在生产模式下(VITE_USE_MOCK=false)提问 "${question}"`
    let i = 0
    const tick = () => {
      if (i >= text.length) {
        handlers.onDone?.({ citations: [] })
        return
      }
      handlers.onChunk?.({ delta: text[i] })
      i++
      setTimeout(tick, 12)
    }
    tick()
  }, 0)
}

// 用 fetch + ReadableStream 订阅 SSE(EventSource 不支持 POST body)
function consumeQAStream(
  question: string,
  handlers: {
    onMeta?: (e: QAMetaEvent) => void
    onChunk?: (e: QAChunkEvent) => void
    onDone?: (e: QADoneEvent) => void
    onError?: (e: { message?: string; status?: number }) => void
  }
): () => void {
  const ac = new AbortController()
  fetch("/api/qa?stream=true", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ q: question, stream: true }),
    signal: ac.signal,
  })
    .then(async resp => {
      if (!resp.ok || !resp.body) {
        handlers.onError?.({ status: resp.status })
        return
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ""
      let currentEvent = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        // SSE 帧:`event: <name>\ndata: <json>\n\n`
        const frames = buf.split("\n\n")
        buf = frames.pop() ?? ""
        for (const frame of frames) {
          let ev = ""
          let data = ""
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) ev = line.slice(6).trim()
            else if (line.startsWith("data:")) data += line.slice(5).trim()
          }
          if (!ev || !data) continue
          let payload: any
          try { payload = JSON.parse(data) } catch { continue }
          if (ev === "meta") handlers.onMeta?.(payload)
          else if (ev === "chunk") handlers.onChunk?.(payload)
          else if (ev === "done") handlers.onDone?.(payload)
          else if (ev === "error") handlers.onError?.(payload)
        }
      }
    })
    .catch(e => {
      if ((e as any).name !== "AbortError") {
        handlers.onError?.({ message: (e as Error).message })
      }
    })
  return () => ac.abort()
}

export const isMockMode = USE_MOCK