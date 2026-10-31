/**
 * API 客户端 + 类型定义
 *
 * 双模式:
 *   - 生产: fetch('/api/...')  → Cloudflare Workers
 *   - 开发: import mockData     → 本地 JSON
 * 通过环境变量 VITE_USE_MOCK 切换 (默认 mock=true,方便离线开发)
 */

// ⚠️ 生产构建必须显式 VITE_USE_MOCK=false —— 否则线上页面会加载
//    mock 语料(3.2MB)并展示离线数据, 看起来"能用"但其实没连 Worker。
//    用 import.meta.env.VITE_USE_MOCK 在 build 时内联, 运行时改不了。
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

/**
 * 目录树(来自 minimax/001目录/目录合并.md)
 *
 * 与 Document 列表是**两套视图**:
 *   - Document 列表: 按 ingest 的目录树顺序, 平铺 196 个文档
 *   - 目录树: 书籍原版的层级(一级分类 → 子类 → 文件), 带文号和起始页
 * 目录树的价值是「有分类结构 + 有文号」, 所以不能拿 Document 列表凑。
 */
export interface CatalogDoc {
  title: string
  doc_number?: string | null
  page?: number | null
  /** 对应 documents 表的 doc_id; 未匹配到实体文档时为 undefined */
  doc_id?: string
  matched: boolean
  match_by?: string | null
  article_count?: number
  chapter_count?: number
}

export interface CatalogSection {
  title: string | null
  page?: number | null
  docs: CatalogDoc[]
}

export interface CatalogScope {
  title: string
  scope_key?: string
  sections: CatalogSection[]
}

export interface Catalog {
  scopes: CatalogScope[]
  stats?: {
    scopes: number
    sections: number
    docs: number
    matched: number
    unmatched: number
    documents_total: number
  }
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

// ---------- C1.5 · 多轮会话 ----------

/** 多轮问答响应。 */
export interface ConversationAnswer {
  sessionId: string
  question: string
  /** 实际用于检索的 query —— 可能含上下文补全(指代消解)。 */
  resolvedQuery: string
  answer: string
  citations: CitationItem[]
  retrieval: SearchHit[]
  elapsed_ms: number
}

// ---------- ② 合规规则(C1) ----------

/** 合规判定状态。 */
export type ComplianceStatus =
  | "compliant"      // 合规
  | "exceeded"       // 超限
  | "prohibited"     // 禁用
  | "not_covered"    // ⚠️ 规则未覆盖 —— 必须显式展示

/** 命中的规则 + 溯源。 */
export interface ComplianceRuleHit {
  ruleId: string
  sourceArticleId: string
  sourceDocId: string
  sourceExcerpt: string | null
  limit: { min: number | null; max: number | null; unit: string | null }
}

/** 检索到的相关条文(未覆盖时给人工参考)。 */
export interface RelatedArticle {
  articleId: string
  chapterTitle?: string
  articleNumber?: string
  excerpt: string
}

/** 合规校验响应。 */
export interface ComplianceResult {
  status: ComplianceStatus
  substance: string
  matchedSubstance: string | null
  matchMethod: string | null
  usage: { species: string; stage: string | null; value: number; unit: string }
  ruleHits: ComplianceRuleHit[]
  suggestion: { maxAllowed: number; unit: string; message: string } | null
  coverageGap: { reason: string; relatedArticles: RelatedArticle[] } | null
  ruleSetVersion: string
  notice: string
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

  // 目录树(书籍原版层级 + 文号 + 起始页)
  async getCatalog(): Promise<Catalog> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      return mockApi.getCatalog()
    }
    const r = await fetchJson<Catalog>("/api/catalog")
    return r
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

  // ② 合规规则(C1)
  /**
   * 用量合规速查。
   *
   * ⚠️ 这是**确定性**接口 —— 参数错直接 400, 不做模糊猜测。
   *    「规则未覆盖」会返回 status='not_covered', 由前端显式提示转人工。
   */
  async checkCompliance(params: {
    substance: string
    species: string
    stage?: string | null
    value: number
    unit: string
  }): Promise<ComplianceResult> {
    if (USE_MOCK) {
      return {
        status: "not_covered",
        substance: params.substance,
        matchedSubstance: null,
        matchMethod: null,
        usage: {
          species: params.species,
          stage: params.stage ?? null,
          value: params.value,
          unit: params.unit,
        },
        ruleHits: [],
        suggestion: null,
        coverageGap: {
          reason: "Mock 模式:未接入合规规则库",
          relatedArticles: [],
        },
        ruleSetVersion: "mock",
        notice: "本结果为辅助意见，不构成监管结论",
      }
    }
    const r = await fetchJson<ComplianceResult>("/api/compliance/usage", {
      method: "POST",
      body: JSON.stringify(params),
    } as any)
    return r
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
      // mock 模式下不真接 LLM,走检索 + 模板答案模拟 streaming
      return mockStreamFallback(question, handlers)
    }
    return consumeQAStream(question, handlers)
  },

  // ── C1.5 · 多轮会话 ──
  //
  // ⚠️ 与 qaStream 分开: 多轮是**非流式**的 ——
  //    多轮场景下 prompt 里带了历史, 流式增量输出与「完整历史」不好配合,
  //    且用户追问通常很短, 等完整答案的体验损失可接受。
  async conversation(
    sessionId: string,
    question: string
  ): Promise<ConversationAnswer> {
    if (USE_MOCK) {
      const { mockApi } = await import("./mockData")
      const hits = await mockApi.search(question)
      const answer = hits.length
        ? `根据检索结果,${hits[0]!.chapter_title} ${hits[0]!.article_number} 规定如下 [1]。`
        : "未找到相关规定。"
      return {
        sessionId,
        question,
        resolvedQuery: question,
        answer,
        citations: hits.slice(0, 1).map((h, i) => ({
          ref: i + 1,
          article_id: h.article_id,
          chapter_id: h.chapter_id,
          doc_id: h.doc_id,
          chapter_number: h.chapter_number,
          chapter_title: h.chapter_title,
          article_number: h.article_number,
          title: h.title,
          excerpt: h.excerpt,
          valid: true,
        })),
        retrieval: hits,
        elapsed_ms: 0,
      }
    }
    const r = await fetchJson<ConversationAnswer>("/api/qa/conversation", {
      method: "POST",
      body: JSON.stringify({ sessionId, q: question }),
    } as any)
    return r
  },

  /** 清空会话。 */
  async clearConversation(sessionId: string): Promise<void> {
    if (USE_MOCK) return
    await fetchJson<{ ok: boolean }>(
      `/api/qa/conversation?sessionId=${encodeURIComponent(sessionId)}`,
      { method: "DELETE" } as any
    )
  },
}

// Mock 模式下的 RAG streaming 模拟:无 LLM,直接基于检索结果拼一段模板答案
//
// ⚠️ 必须**真的走检索**(mockApi.search),不能塞空 retrieval ——
//    之前硬编码 `retrieval: []`, 结果 QA 页永远显示「当前 0 条证据」,
//    引用区也不渲染, e2e 只能断言一句「Mock 模式」文案, 测不到真东西。
//    现在 mock 模式会: 检索 → 把命中条文的摘要当答案逐字吐出 → 给引用。
function mockStreamFallback(
  question: string,
  handlers: {
    onMeta?: (e: any) => void
    onChunk?: (e: any) => void
    onDone?: (e: any) => void
    onError?: (e: any) => void
  }
): () => void {
  let aborted = false
  // 逐字输出的定时器句柄, 供 abort 清理
  let timer: ReturnType<typeof setTimeout> | undefined

  const run = async () => {
    let retrieval: SearchHit[] = []
    try {
      const { mockApi } = await import("./mockData")
      retrieval = await mockApi.search(question)
    } catch (e) {
      handlers.onError?.({ message: (e as Error).message })
      return
    }
    if (aborted) return

    handlers.onMeta?.({ question, retrieval })

    // 用检索到的条文摘要拼答案(前 3 条), 让引用 [1][2][3] 有实际内容可指
    const top = retrieval.slice(0, 3)
    const parts: string[] = []
    if (top.length === 0) {
      parts.push(`未找到与「${question}」相关的条文。`)
    } else {
      parts.push(`Mock 模式(无 LLM):根据检索到的 ${top.length} 条相关条文,要点如下。`)
      top.forEach((h, i) => {
        const label = h.chapter_title || h.title || h.article_number || ""
        const excerpt = (h.excerpt || "").slice(0, 160)
        parts.push(`[${i + 1}] ${label} ${excerpt}`)
      })
    }
    const text = parts.join("\n\n")

    let i = 0
    const tick = () => {
      if (aborted) return
      if (i >= text.length) {
        handlers.onDone?.({
          citations: top.map((h, idx) => ({
            ref: idx + 1,
            article_id: h.article_id,
            chapter_id: h.chapter_id,
            doc_id: h.doc_id,
            chapter_number: h.chapter_number,
            chapter_title: h.chapter_title,
            article_number: h.article_number,
            excerpt: h.excerpt,
            valid: true,
          })),
        })
        return
      }
      handlers.onChunk?.({ delta: text[i] })
      i++
      timer = setTimeout(tick, 12)
    }
    tick()
  }

  void run()

  return () => {
    aborted = true
    if (timer) clearTimeout(timer)
  }
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