/**
 * Mock 后端 —— 从 ingest_minimax.py 的产物动态加载
 *
 * 数据来源: data/index/minimax/{documents,chapters,articles}.json
 * (build/export/ingest_minimax.py 从 minimax/ 目录树切出来的产物)
 *
 * 新语料与旧语料(data/markdown/<doc_id>/*)的结构差异:
 *   - 旧: 一个 doc 一个目录, 各带 chapters.json / articles.json / *.md
 *   - 新: **全部文档共用一份** documents.json / chapters.json / articles.json
 *         (196 份文件, 529 章, 3145 条), markdown 文件名带 hash 后缀
 *
 * 切换到真实后端:  VITE_USE_MOCK=false npm run dev
 */

import type {
  Document, Chapter, ChapterDetail, Article, ArticleDetail, SearchHit,
  Entity,
} from "./api"

// Vite: build 时把索引产物打包进 bundle
// 路径: web/src/lib/ → ../../../data/index/minimax/...
// ⚠️ glob 必须**精确列出**要打包的文件, 不能用 "*.json" ——
//    否则会把 articles.json(含全文, 4.9MB)一起 eager 打进 bundle。
//    实测: 用 *.json 时 mockData chunk 8.2MB; 精确列 3 个文件后降到 ~1.5MB。
const indexModules = {
  ...import.meta.glob(
    "../../../data/index/minimax/documents.json",
    { eager: true }
  ),
  ...import.meta.glob(
    "../../../data/index/minimax/chapters.json",
    { eager: true }
  ),
  ...import.meta.glob(
    "../../../data/index/minimax/articles.light.json",
    { eager: true }
  ),
} as Record<string, { default: unknown }>

// 搜索语料: **懒加载**单文件。
// ⚠️ 不能 eager —— 3.2MB 语料 eager 打包会让 mockData chunk 涨到 3.8MB
//    (932KB gzip), 首屏就下载整个语料。懒加载后是独立 chunk,
//    只有真正搜索时才拉。
const corpusModules = import.meta.glob(
  "../../../data/index/minimax/search-corpus.json"
) as Record<string, () => Promise<{ default: { article_id: string; text: string }[] }>>

// markdown 模块,按需懒加载 (文件名带 hash 后缀)
const markdownModules = import.meta.glob(
  "../../../data/index/minimax/articles/*.md",
  { eager: false, query: "?raw", import: "default" }
) as Record<string, () => Promise<string>>

const chapterMdModules = import.meta.glob(
  "../../../data/index/minimax/chapters/*.md",
  { eager: false, query: "?raw", import: "default" }
) as Record<string, () => Promise<string>>

interface RawDocument {
  doc_id: string
  title: string
  dir_name: string
  scope: string
  scope_id: string
  section: string | null
  section_id: string | null
  doc_number: string
  page_count: number
  article_count: number
  is_toc: boolean
  article_ids: string[]
}

interface RawChapter {
  chapter_id: string
  doc_id: string
  number: string
  title: string
  kind: "section" | "chapter"
  sort_order: number
  article_count: number
  article_ids: string[]
  doc_number: string
  source: string
}

interface RawArticle {
  article_id: string
  chapter_id: string
  doc_id: string
  number: string
  title: string
  heading: string
  chapter_number: string
  chapter_title: string
  kind: string
}

function pick<T>(name: string): T[] {
  const key = Object.keys(indexModules).find(p => p.endsWith(`/${name}.json`))
  if (!key) {
    console.warn(`[mockData] 索引清单缺失: ${name}.json`)
    return []
  }
  return (indexModules[key].default as T[]) ?? []
}

const RAW_DOCUMENTS: RawDocument[] = pick<RawDocument>("documents")
const RAW_CHAPTERS: RawChapter[] = pick<RawChapter>("chapters")
// 用轻量清单(不含 text) —— 完整 articles.json 有 4.8MB,
// eager 打包会把整个语料塞进 bundle(实测 mockData chunk 3.6MB)。
// 正文从 articles/*.md 按需加载。
const RAW_ARTICLES: RawArticle[] = pick<RawArticle>("articles.light")

// 搜索语料: article_id → 全文 (懒加载单文件 + 内存缓存)
let CORPUS_BY_ID: Map<string, string> | null = null
let corpusPromise: Promise<Map<string, string>> | null = null

function loadCorpus(): Promise<Map<string, string>> {
  if (corpusPromise) return corpusPromise
  const path = Object.keys(corpusModules)[0]
  if (!path) {
    corpusPromise = Promise.resolve(new Map())
    return corpusPromise
  }
  corpusPromise = corpusModules[path]().then(mod => {
    const list = (mod as any)?.default ?? []
    const m = new Map<string, string>()
    for (const r of list) m.set(r.article_id, r.text)
    CORPUS_BY_ID = m
    return m
  })
  return corpusPromise
}

// 直接按文件名建索引, 避免运行时重算 hash
const ARTICLE_MD_BY_ID: Record<string, string> = {}
for (const p of Object.keys(markdownModules)) {
  const fname = p.split("/").pop() ?? ""
  const id = fname.replace(/\.md$/, "").replace(/__[0-9a-f]{8}$/, "")
  ARTICLE_MD_BY_ID[id] = p
}
const CHAPTER_MD_BY_ID: Record<string, string> = {}
for (const p of Object.keys(chapterMdModules)) {
  const fname = p.split("/").pop() ?? ""
  const id = fname.replace(/\.md$/, "").replace(/__[0-9a-f]{8}$/, "")
  CHAPTER_MD_BY_ID[id] = p
}

// ---------- 派生视图 ----------

// ⚠️ 目录/封面文档**不进前端文档列表** —— 它们不是法规正文,
//    首页第一屏全是「000封面」「目录」没有意义。
//    (DB 里仍然保留, 可追溯; 只是不展示。)
const DOCUMENTS: Document[] = RAW_DOCUMENTS
  .filter(d => !d.is_toc)
  .map(d => ({
    doc_id: d.doc_id,
    title: d.title,
    doc_number: d.doc_number || undefined,
    issuer: d.scope,
    effective_date: undefined,
    chapter_count: RAW_CHAPTERS.filter(c => c.doc_id === d.doc_id).length,
    article_count: d.article_count,
  }))

const CHAPTERS: ChapterDetail[] = RAW_CHAPTERS.map(c => ({
  chapter_id: c.chapter_id,
  doc_id: c.doc_id,
  number: c.number,
  title: c.title,
  article_count: c.article_count,
  sort_order: c.sort_order,
  markdown: "",
}))

const ARTICLE_BY_ID = new Map<string, RawArticle>(RAW_ARTICLES.map(a => [a.article_id, a]))
const CHAPTER_BY_ID = new Map<string, RawChapter>(RAW_CHAPTERS.map(c => [c.chapter_id, c]))

const ARTICLES: ArticleDetail[] = RAW_ARTICLES.map(a => {
  const ch = CHAPTER_BY_ID.get(a.chapter_id)
  return {
    article_id: a.article_id,
    chapter_id: a.chapter_id,
    doc_id: a.doc_id,
    number: a.number,
    title: a.title,
    chapter_number: a.chapter_number || ch?.number,
    chapter_title: a.chapter_title || ch?.title,
    markdown: "",
  }
})

// Entities: 切分器不产出实体,这里用 mockData 的种子 + 简单关键词匹配。
const ENTITIES: Entity[] = [
  {
    entity_id: "ent_001",
    name: "农业农村部",
    type: "AGENCY",
    description: "国务院农业农村主管部门,负责全国饲料和饲料添加剂的监督管理工作。",
  },
  {
    entity_id: "ent_002",
    name: "饲料添加剂审定证书",
    type: "CERTIFICATE",
    description: "国家对饲料添加剂实行审定制度。申请饲料添加剂审定应当向农业农村部提交申请书、产品配方等材料。",
  },
  {
    entity_id: "ent_003",
    name: "饲料生产企业",
    type: "PARTY",
    description: "从事饲料生产的企业,应当具备厂房、设备、质量检验机构等条件。",
  },
]

// 正文缓存 —— mock 模式下 search 要扫 3145 条, 不缓存的话每次 5s+
const mdCache = new Map<string, string>()

async function getArticleMd(articleId: string): Promise<string> {
  const cached = mdCache.get(articleId)
  if (cached !== undefined) return cached
  const path = ARTICLE_MD_BY_ID[articleId]
  if (!path) {
    mdCache.set(articleId, "")
    return ""
  }
  const md = await markdownModules[path]()
  mdCache.set(articleId, md)
  return md
}

// excerpt: 实际 markdown 加载时计算
//
// ⚠️ excerpt 必须是**围绕 query 截取**, 不能是正文开头的前 200 字 ——
//    否则搜「饲料添加剂」命中的是一条讲「生产许可」的条文,
//    excerpt 里根本没有 query 词, 用户点进去才发现不对(实测 202 页表格文档)。
//    做法: 找 query 在正文里的首次出现位置, 从那里往前后各取一段。
function excerptOf(md: string, query?: string): string {
  const body = md
    .split("\n")
    .filter(l => !l.startsWith("<!--"))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()

  if (!query) return body.slice(0, 200)

  const idx = body.toLowerCase().indexOf(query.toLowerCase())
  if (idx < 0) return body.slice(0, 200)

  const half = 100
  const start = Math.max(0, idx - half)
  const end = Math.min(body.length, idx + query.length + half)
  return (start > 0 ? "…" : "") + body.slice(start, end).trim() + (end < body.length ? "…" : "")
}

export const mockApi = {
  async listDocuments(): Promise<Document[]> {
    await new Promise(r => setTimeout(r, 50))
    return DOCUMENTS
  },

  async listChapters(docId: string): Promise<Chapter[]> {
    await new Promise(r => setTimeout(r, 50))
    return CHAPTERS
      .filter(c => c.doc_id === docId)
      .map(({ markdown, ...rest }) => rest)
      .sort((a, b) => a.sort_order - b.sort_order)
  },

  async getChapter(docId: string, chapterId: string): Promise<ChapterDetail> {
    await new Promise(r => setTimeout(r, 50))
    const base = CHAPTERS.find(c => c.doc_id === docId && c.chapter_id === chapterId)
    if (!base) throw new Error(`chapter not found: ${chapterId}`)
    const mdPath = CHAPTER_MD_BY_ID[chapterId]
    const markdown = mdPath ? await chapterMdModules[mdPath]() : ""
    return { ...base, markdown }
  },

  async getArticle(articleId: string): Promise<ArticleDetail> {
    await new Promise(r => setTimeout(r, 50))
    const art = ARTICLES.find(a => a.article_id === articleId)
    if (!art) throw new Error(`article not found: ${articleId}`)
    const markdown = await getArticleMd(articleId)
    return { ...art, markdown }
  },

  async search(q: string): Promise<SearchHit[]> {
    await new Promise(r => setTimeout(r, 80))
    const query = q.toLowerCase().trim()
    if (!query) return []  // 空 query 短路(对齐 api.ts 的 searchArticles 行为)

    // ⚠️ 搜索必须走 **search-corpus.json**(单文件, 一次 import)。
    //    不能遍历 import.meta.glob 的 3145 个逐条 markdown —— 每个 import()
    //    都要过 Vite 模块解析器, 实测单次 search >5s(测试直接超时)。
    const corpus = await loadCorpus()
    const hits: SearchHit[] = []
    for (const art of ARTICLES) {
      const md = corpus.get(art.article_id) ?? ""
      if (!md) continue
      const text = md.toLowerCase()
      if (text.includes(query)) {
        hits.push({
          ...art,
          excerpt: excerptOf(md, query),
          relevance: (text.match(new RegExp(escapeRe(query), "g")) || []).length,
        })
      }
    }
    return hits.sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
  },

  async getEntity(name: string): Promise<{ entity: Entity; articles: Article[] }> {
    await new Promise(r => setTimeout(r, 50))
    const ent = ENTITIES.find(e => e.name === name)
    if (!ent) throw new Error(`entity not found: ${name}`)
    const ids = new Set<string>()
    const keywords = (ent.description ?? "")
      .replace(/[^\w一-鿿]+/g, " ")
      .split(/\s+/)
      .filter(s => s.length >= 4)
    // 走 search-corpus(单文件), 不要遍历 3145 个动态 import
    const corpus = await loadCorpus()
    for (const art of ARTICLES) {
      const md = corpus.get(art.article_id) ?? ""
      if (md && keywords.some(k => md.includes(k))) ids.add(art.article_id)
    }
    const arts = ARTICLES.filter(a => ids.has(a.article_id))
      .map(({ markdown, ...rest }) => rest)
    return { entity: ent, articles: arts }
  },
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
