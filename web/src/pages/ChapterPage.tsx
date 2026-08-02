import { useEffect, useState } from "react"
import { Link, useParams, useLocation } from "react-router-dom"
import { api } from "../lib/api"
import type { ChapterDetail } from "../lib/api"
import { MarkdownView } from "../components/MarkdownView"
import { SearchBar } from "../components/SearchBar"
import { isMockMode } from "../lib/api"

export function ChapterPage() {
  const { docId = "feed-law-2026", chapterId = "" } = useParams<{ docId: string; chapterId: string }>()
  const location = useLocation()
  const [chapter, setChapter] = useState<ChapterDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.getChapter(docId, chapterId)
      .then(setChapter)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [docId, chapterId])

  // 处理 URL hash 跳转(条文锚点)
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [location.hash, chapter])

  if (loading) return <div className="p-8 text-slate-500">加载中...</div>
  if (error || !chapter) return <div className="p-8 text-red-600">错误:{error || "章节不存在"}</div>

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-4 sm:px-8 py-6 sticky top-0 z-10">
        <div className="max-w-4xl mx-auto">
          <Link to={`/doc/${docId}`} className="text-sm text-primary hover:underline">← 章节目录</Link>
          <h1 className="mt-2 text-xl sm:text-2xl font-bold text-slate-900">
            {chapter.number} {chapter.title}
          </h1>
          <div className="mt-3">
            <SearchBar />
          </div>
          <div className="mt-2 text-xs text-slate-500">
            {chapter.article_count} 条 · {isMockMode ? "Mock" : "Live"}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 bg-white rounded-lg shadow-sm my-4">
        <MarkdownView source={chapter.markdown} chapterId={chapter.chapter_id} />
      </main>

      <footer className="text-center text-xs text-slate-400 py-4">
        阶段 F · 按章节而非按字符切分 · 每条文有独立锚点
      </footer>
    </div>
  )
}