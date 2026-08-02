import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { api } from "../lib/api"
import type { Article, Entity } from "../lib/api"
import { EntityCard } from "../components/EntityCard"
import { SearchBar } from "../components/SearchBar"
import { Layout } from "../components/Layout"
import { EntityGraph, type GraphArticle } from "../components/EntityGraph"
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

  if (loading) return (
    <Layout>
      <div className="p-8 text-slate-500 dark:text-slate-400">加载中...</div>
    </Layout>
  )
  if (error || !entity) return (
    <Layout>
      <div className="p-8 text-red-600 dark:text-red-400">错误:{error || "实体不存在"}</div>
    </Layout>
  )

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6">
        <div className="max-w-4xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100">{entity.name}</h1>
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs px-2 py-0.5 bg-slate-100 dark:bg-slate-800 rounded">{entity.type}</span>
            <span className="text-xs text-slate-500 dark:text-slate-400">{articles.length} 个相关条文</span>
          </div>
          <div className="mt-4">
            <SearchBar defaultValue={entity.name} />
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 space-y-6">
        {entity.description && (
          <div className="p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-2">描述</h2>
            <p className="text-slate-700 dark:text-slate-300">{entity.description}</p>
          </div>
        )}

        {articles.length > 0 && (
          <section>
            <h2 className="text-lg font-semibold mb-3">关系图谱</h2>
            <div className="p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
              <EntityGraph
                center={entity.name}
                centerType={entity.type}
                articles={articles as GraphArticle[]}
              />
              <p className="text-xs text-slate-400 dark:text-slate-500 text-center mt-2">
                点击条文节点跳转原文 · {articles.length} 个相关条文 · {Array.from(new Set(articles.map(a => a.doc_id))).length} 部法规
              </p>
            </div>
          </section>
        )}

        <div>
          <h2 className="text-lg font-semibold mb-3">相关条文</h2>
          {articles.length === 0 ? (
            <div className="text-slate-500 dark:text-slate-400 text-sm">暂无关联条文</div>
          ) : (
            <ol className="space-y-2">
              {articles.map(a => (
                <li key={a.article_id}>
                  <Link
                    to={`/doc/${a.doc_id}/chapter/${a.chapter_id}#${a.article_id}`}
                    className="flex items-baseline gap-3 p-3 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm transition"
                  >
                    <span className="text-slate-400 dark:text-slate-500 font-mono text-sm w-24 flex-shrink-0">
                      {a.chapter_number} · {a.number}
                    </span>
                    <span className="text-slate-700 dark:text-slate-300 flex-1">
                      参见 {a.chapter_title} 章 — {a.number}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="text-xs text-slate-400 dark:text-slate-600 text-center pt-4">
          {isMockMode ? "Mock 模式" : "生产模式"}
        </div>
      </main>
    </Layout>
  )
}