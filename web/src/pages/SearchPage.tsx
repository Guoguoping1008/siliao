import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { api } from "../lib/api"
import type { SearchHit } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { Layout } from "../components/Layout"
import { AsyncState } from "../components/AsyncState"
import { isMockMode } from "../lib/api"

export function SearchPage() {
  const [params] = useSearchParams()
  const q = params.get("q") || ""
  const [hits, setHits] = useState<SearchHit[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const load = (query: string) => {
    if (!query) {
      setHits([])
      return
    }
    setLoading(true)
    setError(null)
    api.search(query)
      .then(setHits)
      .catch(setError)
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load(q)
  }, [q])

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6 sticky top-12">
        <div className="max-w-3xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">← 返回首页</Link>
          <div className="mt-3">
            <SearchBar defaultValue={q} />
          </div>
          {q && (
            <div className="mt-2 text-sm text-slate-600 dark:text-slate-400">
              搜索 "<span className="font-semibold">{q}</span>"
              {!loading && !error && ` — ${hits.length} 条结果`}
            </div>
          )}
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-8 py-6">
        {!q ? (
          <div className="text-slate-500 dark:text-slate-400">在上方输入关键词检索条文。</div>
        ) : (
          <AsyncState
            loading={loading}
            error={error}
            isEmpty={!loading && !error && hits.length === 0}
            emptyText="未命中任何条文"
            emptyHint="试试其他关键词,或检查拼写"
            loadingText="搜索中..."
          >
            <ol className="space-y-3">
              {hits.map(h => (
                <li key={h.article_id}>
                  <Link
                    to={`/doc/${h.doc_id}/chapter/${h.chapter_id}#${h.article_id}`}
                    className="block p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm transition"
                  >
                    <div className="flex items-baseline gap-2 mb-1">
                      <span className="text-xs font-mono text-slate-500 dark:text-slate-400">{h.chapter_number}</span>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {h.chapter_title} · {h.number}
                      </span>
                      {h.relevance && (
                        <span className="ml-auto text-xs text-slate-400 dark:text-slate-500">
                          相关度:{h.relevance}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-700 dark:text-slate-300 line-clamp-3">{h.excerpt}</p>
                  </Link>
                </li>
              ))}
            </ol>
          </AsyncState>
        )}
      </main>

      <div className="text-center text-xs text-slate-400 dark:text-slate-600 py-4">
        {isMockMode ? "Mock 模式 · 文本匹配" : "生产模式 · GraphRAG + 向量检索"}
      </div>
    </Layout>
  )
}
