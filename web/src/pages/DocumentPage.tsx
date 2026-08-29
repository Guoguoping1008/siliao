import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { api } from "../lib/api"
import type { Chapter } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { DocumentCard } from "../components/DocumentCard"
import { Layout } from "../components/Layout"
import { AsyncState } from "../components/AsyncState"
import { isMockMode } from "../lib/api"

export function DocumentPage() {
  const { docId = "feed-law-2026" } = useParams<{ docId: string }>()
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [title, setTitle] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([api.listDocuments(), api.listChapters(docId)])
      .then(([docs, chs]) => {
        const doc = docs.find(d => d.doc_id === docId)
        setTitle(doc?.title || docId)
        setChapters(chs)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }

  useEffect(load, [docId])

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100">{title}</h1>
          <div className="mt-4">
            <SearchBar />
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-8 py-8">
        <h2 className="text-lg font-semibold mb-4">章节目录</h2>
        <AsyncState
          loading={loading}
          error={error}
          isEmpty={!loading && !error && chapters.length === 0}
          emptyText="该法规暂无章节"
          onRetry={load}
          loadingText="加载章节..."
        >
          <ol className="space-y-2">
            {chapters.map(c => (
              <li key={c.chapter_id}>
                <Link
                  to={`/doc/${docId}/chapter/${c.chapter_id}`}
                  className="flex items-baseline gap-3 p-3 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm transition"
                >
                  <span className="text-slate-400 dark:text-slate-500 font-mono text-sm w-20 flex-shrink-0">
                    {c.number}
                  </span>
                  <span className="font-medium flex-1">{c.title}</span>
                  <span className="text-xs text-slate-400 dark:text-slate-500">{c.article_count} 条</span>
                </Link>
              </li>
            ))}
          </ol>
        </AsyncState>
      </main>

      <div className="text-center text-xs text-slate-400 dark:text-slate-600 py-4">
        {isMockMode ? "Mock 模式 · 离线数据" : "生产模式 · Cloudflare Workers"}
      </div>
    </Layout>
  )
}
