import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { api } from "../lib/api"
import type { Chapter } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { DocumentCard } from "../components/DocumentCard"
import { isMockMode } from "../lib/api"

/**
 * 文档详情页: 顶部搜索 + 文号元数据 + 左侧章节目录树 + 右侧"点击章节查看"
 */
export function DocumentPage() {
  const { docId = "feed-law-2026" } = useParams<{ docId: string }>()
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [title, setTitle] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.listDocuments(), api.listChapters(docId)])
      .then(([docs, chs]) => {
        const doc = docs.find(d => d.doc_id === docId)
        setTitle(doc?.title || docId)
        setChapters(chs)
      })
      .finally(() => setLoading(false))
  }, [docId])

  if (loading) return <div className="p-8 text-slate-500">加载中...</div>

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-4 sm:px-8 py-6">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-sm text-primary hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900">{title}</h1>
          <div className="mt-4">
            <SearchBar />
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-8 py-8">
        <h2 className="text-lg font-semibold mb-4">章节目录</h2>
        <ol className="space-y-2">
          {chapters.map(c => (
            <li key={c.chapter_id}>
              <Link
                to={`/doc/${docId}/chapter/${c.chapter_id}`}
                className="flex items-baseline gap-3 p-3 bg-white rounded-lg border border-slate-200 hover:border-primary hover:shadow-sm transition"
              >
                <span className="text-slate-400 font-mono text-sm w-20 flex-shrink-0">
                  {c.number}
                </span>
                <span className="font-medium flex-1">{c.title}</span>
                <span className="text-xs text-slate-400">{c.article_count} 条</span>
              </Link>
            </li>
          ))}
        </ol>
      </main>

      <footer className="text-center text-xs text-slate-400 py-4">
        {isMockMode ? "Mock 模式 · 离线数据" : "生产模式 · Cloudflare Workers"}
      </footer>
    </div>
  )
}