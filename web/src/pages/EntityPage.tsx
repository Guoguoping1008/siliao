import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { api } from "../lib/api"
import type { Article, Entity } from "../lib/api"
import { EntityCard } from "../components/EntityCard"
import { SearchBar } from "../components/SearchBar"
import { isMockMode } from "../lib/api"

export function EntityPage() {
  const { name = "" } = useParams<{ name: string }>()
  const decoded = decodeURIComponent(name)
  const [entity, setEntity] = useState<Entity | null>(null)
  const [articles, setArticles] = useState<Article[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.getEntity(decoded)
      .then(({ entity, articles }) => {
        setEntity(entity)
        setArticles(articles)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [decoded])

  if (loading) return <div className="p-8 text-slate-500">加载中...</div>
  if (error || !entity) return <div className="p-8 text-red-600">错误:{error || "实体不存在"}</div>

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-4 sm:px-8 py-6">
        <div className="max-w-4xl mx-auto">
          <Link to="/" className="text-sm text-primary hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900">{entity.name}</h1>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs px-2 py-0.5 bg-slate-100 rounded">{entity.type}</span>
            <span className="text-xs text-slate-500">{articles.length} 个相关条文</span>
          </div>
          <div className="mt-4">
            <SearchBar defaultValue={entity.name} />
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 space-y-4">
        {entity.description && (
          <div className="p-4 bg-white rounded-lg border border-slate-200">
            <h2 className="text-sm font-semibold text-slate-500 mb-2">描述</h2>
            <p className="text-slate-700">{entity.description}</p>
          </div>
        )}

        <div>
          <h2 className="text-lg font-semibold mb-3">相关条文</h2>
          {articles.length === 0 ? (
            <div className="text-slate-500 text-sm">暂无关联条文</div>
          ) : (
            <ol className="space-y-2">
              {articles.map(a => (
                <li key={a.article_id}>
                  <Link
                    to={`/doc/${a.doc_id}/chapter/${a.chapter_id}#${a.article_id}`}
                    className="flex items-baseline gap-3 p-3 bg-white rounded-lg border border-slate-200 hover:border-primary hover:shadow-sm transition"
                  >
                    <span className="text-slate-400 font-mono text-sm w-24 flex-shrink-0">
                      {a.chapter_number} · {a.number}
                    </span>
                    <span className="text-slate-700 flex-1">
                      参见 {a.chapter_title} 章 — {a.number}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="text-xs text-slate-400 text-center pt-4">
          {isMockMode ? "Mock 模式" : "生产模式"}
        </div>
      </main>
    </div>
  )
}