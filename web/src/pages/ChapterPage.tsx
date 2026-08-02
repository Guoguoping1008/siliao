import { useEffect, useState } from "react"
import { Link, useParams, useLocation } from "react-router-dom"
import { api } from "../lib/api"
import type { ChapterDetail } from "../lib/api"
import { MarkdownView } from "../components/MarkdownView"
import { SearchBar } from "../components/SearchBar"
import { Layout } from "../components/Layout"
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

  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [location.hash, chapter])

  if (loading) return (
    <Layout>
      <div className="p-8 text-slate-500 dark:text-slate-400">加载中...</div>
    </Layout>
  )
  if (error || !chapter) return (
    <Layout>
      <div className="p-8 text-red-600 dark:text-red-400">错误:{error || "章节不存在"}</div>
    </Layout>
  )

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6 sticky top-12 z-10">
        <div className="max-w-4xl mx-auto">
          <Link to={`/doc/${docId}`} className="text-sm text-primary dark:text-primary-dark hover:underline">← 章节目录</Link>
          <h1 className="mt-2 text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">
            {chapter.number} {chapter.title}
          </h1>
          <div className="mt-3">
            <SearchBar />
          </div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {chapter.article_count} 条 · {isMockMode ? "Mock" : "Live"}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 bg-white dark:bg-slate-900 rounded-lg shadow-sm dark:shadow-slate-800/30 my-4 transition-colors">
        <MarkdownView source={chapter.markdown} chapterId={chapter.chapter_id} />
      </main>
    </Layout>
  )
}