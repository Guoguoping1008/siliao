/**
 * Mock 后端 — 从切分器产物动态加载
 *
 * 数据来源: data/markdown/<doc_id>/chapters.json + articles.json
 * (build/ocr/chapter_splitter.py 跑出来的产物)
 *
 * 切换到真实后端:  VITE_USE_MOCK=false npm run dev
 */

import type {
  Document, Chapter, ChapterDetail, Article, ArticleDetail, SearchHit,
  Entity,
} from "./api"

// Vite: build 时把所有 markdown doc 的元数据打包进来
// 路径: web/src/lib/ → ../../../data/markdown/*/...
// 用 eager:true 直接拿到对象(而不是返回 Promise)
const chapterModules = import.meta.glob(
  "../../../data/markdown/*/chapters.json",
  { eager: true }
) as Record<string, { default: RawChapter[] }>

const articleModules = import.meta.glob(
  "../../../data/markdown/*/articles.json",
  { eager: true }
) as Record<string, { default: RawArticle[] }>

interface RawChapter {
  chapter_id: string
  number: string
  title: string
  article_ids: string[]
  start_line: number
  end_line: number
}

interface RawArticle {
  article_id: string
  chapter_id: string
  number: string
  title: string
  text: string
  start_line: number
  end_line: number
}

function docIdFromPath(path: string): string {
  // ../../data/markdown/feed-law-2026/chapters.json  →  feed-law-2026
  const m = path.match(/\/markdown\/([^/]+)\//)
  return m ? m[1] : ""
}

// 派生 documents 列表(从 chapters 数 + articles 数)
// title 从 data/raw/<doc_id>.md 的第一非空行读取(法规原文里的标题)
// 排除 .sample.md 占位文件
const rawDocModules = import.meta.glob(
  "../../../data/raw/!(*.sample).md",
  { eager: false, query: "?raw", import: "default" }
) as Record<string, () => Promise<string>>

function rawMdPathFor(docId: string) {
  return Object.keys(rawDocModules).find(p => p.endsWith(`/${docId}.md`)) ?? null
}

const DOCUMENTS: Document[] = Object.keys(chapterModules).map(path => {
  const docId = docIdFromPath(path)
  const chapters = chapterModules[path].default
  const articles = articleModules[
    path.replace("/chapters.json", "/articles.json")
  ]?.default ?? []
  return {
    doc_id: docId,
    title: docId,            // 占位:首页渲染前若需要更友好标题,见 hydrateDocumentTitles
    chapter_count: chapters.length,
    article_count: articles.length,
  }
})

// 异步给 title 注水:从 raw 文件读第一行,渲染前 await
const docTitleCache: Record<string, string> = {}
async function hydrateDocumentTitles(docs: Document[]): Promise<Document[]> {
  for (const d of docs) {
    if (docTitleCache[d.doc_id]) {
      d.title = docTitleCache[d.doc_id]
      continue
    }
    const p = rawMdPathFor(d.doc_id)
    if (!p) continue
    const text = await rawDocModules[p]()
    const firstLine = text.split("\n").map(l => l.trim()).find(l => l && !l.startsWith("<!--"))
    if (firstLine && firstLine.length <= 50) docTitleCache[d.doc_id] = firstLine
    if (docTitleCache[d.doc_id]) d.title = docTitleCache[d.doc_id]
  }
  return docs
}

// 派生 chapters(扁平 + sort_order)
const CHAPTERS: ChapterDetail[] = Object.keys(chapterModules).flatMap(path => {
  const docId = docIdFromPath(path)
  return chapterModules[path].default.map((c, idx): ChapterDetail => ({
    chapter_id: c.chapter_id,
    doc_id: docId,
    number: c.number,
    title: c.title,
    article_count: c.article_ids.length,
    sort_order: idx + 1,
    markdown: "",  // 由 markdownModules 现场加载,见 getChapter
  }))
})

// markdown 模块,按需懒加载
const markdownModules = import.meta.glob(
  "../../../data/markdown/*/chapters/*.md",
  { eager: false, query: "?raw", import: "default" }
) as Record<string, () => Promise<string>>

// article markdown 也按需
const articleMdModules = import.meta.glob(
  "../../../data/markdown/*/articles/*.md",
  { eager: false, query: "?raw", import: "default" }
) as Record<string, () => Promise<string>>

function markdownPathFor(docId: string, chapterId: string) {
  const want = `../../../data/markdown/${docId}/chapters/${chapterId}.md`
  return Object.keys(markdownModules).find(p => p === want) ?? null
}

function articleMdPathFor(docId: string, articleId: string) {
  const want = `../../../data/markdown/${docId}/articles/${articleId}.md`
  return Object.keys(articleMdModules).find(p => p === want) ?? null
}

// 派生 articles
const ARTICLES: ArticleDetail[] = Object.keys(articleModules).flatMap(path => {
  const docId = docIdFromPath(path)
  const chaptersById = new Map<string, RawChapter>()
  for (const c of (chapterModules[
    path.replace("/articles.json", "/chapters.json")
  ]?.default ?? [])) {
    chaptersById.set(c.chapter_id, c)
  }
  return articleModules[path].default.map((a): ArticleDetail => {
    const ch = chaptersById.get(a.chapter_id)
    return {
      article_id: a.article_id,
      chapter_id: a.chapter_id,
      doc_id: docId,
      number: a.number,
      chapter_number: ch?.number,
      chapter_title: ch?.title,
      markdown: "",  // 按需加载
    }
  })
})

// Entities: 切分器不产出实体,这里用 mockData 的种子 + 简单关键词匹配。
// 后续 GraphRAG 跑完后,改成从 data/index/entities.json 加载。
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

// excerpt: 实际 markdown 加载时计算
function excerptOf(md: string): string {
  return md
    .split("\n")
    .filter(l => !l.startsWith("<!--") && !l.startsWith("#"))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200)
}

export const mockApi = {
  async listDocuments(): Promise<Document[]> {
    await new Promise(r => setTimeout(r, 50))
    return hydrateDocumentTitles(DOCUMENTS)
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
    const mdPath = markdownPathFor(docId, chapterId)
    const markdown = mdPath ? await markdownModules[mdPath]() : ""
    return { ...base, markdown }
  },

  async getArticle(articleId: string): Promise<ArticleDetail> {
    await new Promise(r => setTimeout(r, 50))
    const art = ARTICLES.find(a => a.article_id === articleId)
    if (!art) throw new Error(`article not found: ${articleId}`)
    const mdPath = articleMdPathFor(art.doc_id, articleId)
    const markdown = mdPath ? await articleMdModules[mdPath]() : ""
    return { ...art, markdown }
  },

  async search(q: string): Promise<SearchHit[]> {
    await new Promise(r => setTimeout(r, 80))
    const query = q.toLowerCase().trim()
    if (!query) return []  // 空 query 短路(对齐 api.ts 的 searchArticles 行为)
    const hits: SearchHit[] = []
    for (const art of ARTICLES) {
      const mdPath = articleMdPathFor(art.doc_id, art.article_id)
      const text = mdPath ? (await articleMdModules[mdPath]()).toLowerCase() : ""
      if (!text) continue
      if (text.includes(query)) {
        const raw = mdPath ? await articleMdModules[mdPath]() : ""
        hits.push({
          ...art,
          excerpt: excerptOf(raw),
          relevance: (text.match(new RegExp(query, "g")) || []).length,
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
    // 扫所有 article 的 markdown,匹配 entity 关键词
    const keywords = (ent.description ?? "")
      .replace(/[^\w\u4E00-\u9FFF]+/g, " ")
      .split(/\s+/)
      .filter(s => s.length >= 4)
    for (const art of ARTICLES) {
      const mdPath = articleMdPathFor(art.doc_id, art.article_id)
      const md = mdPath ? await articleMdModules[mdPath]() : ""
      if (keywords.some(k => md.includes(k))) ids.add(art.article_id)
    }
    const arts = ARTICLES.filter(a => ids.has(a.article_id))
      .map(({ markdown, ...rest }) => rest)
    return { entity: ent, articles: arts }
  },
}
