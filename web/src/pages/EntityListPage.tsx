/**
 * 实体列表页 —— ④ 知识图谱的入口
 *
 * ## 为什么需要这个页面
 *
 * 2026-11-03 实测:图谱有 **481 个实体**(387 条物质 + 94 个 GraphRAG 概念),
 * 但前端**没有任何入口**能列出它们:
 *
 * - 顶栏「实体」硬编码跳 `/entity/农业农村部` —— 那个实体**根本不存在**
 *   (生产实测 `entities` 表 name='农业农村部' 命中 0 条)
 * - 没有实体列表页、没有实体搜索框
 *
 * 结果:481 个实体里,只有手动拼 URL 才能到达 —— 等于图谱是半残的。
 *
 * ## 设计
 *
 * - **类型筛选**:SUBSTANCE(物质,398)/ LAW / PARTY / AGENCY … 先按类型分桶
 * - **名称搜索**:走服务端 `?q=`(SQL LIKE),不是前端过滤 —— 前端过滤只能
 *   看当前页,搜不到的东西就永远搜不到
 * - **分页**:每页 50,支持「上一页/下一页」
 */
import { useCallback, useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { api } from "../lib/api"
import type { Entity } from "../lib/api"
import { Layout } from "../components/Layout"
import { AsyncState } from "../components/AsyncState"

const PAGE_SIZE = 50

/** 类型筛选条 —— 顺序按实体数从多到少(生产实测 2026-11-03)。 */
const TYPE_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "全部" },
  { value: "SUBSTANCE", label: "物质" },
  { value: "ACTION", label: "行为" },
  { value: "DOCUMENT", label: "文件" },
  { value: "PARTY", label: "主体" },
  { value: "AGENCY", label: "机构" },
  { value: "LAW", label: "法律" },
  { value: "PENALTY", label: "处罚" },
  { value: "GEO", label: "地域" },
  { value: "PERSON", label: "人员" },
  { value: "EVENT", label: "事件" },
  { value: "CERTIFICATE", label: "证书" },
  { value: "ORGANIZATION", label: "组织" },
]

export function EntityListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const type = searchParams.get("type") ?? ""
  const q = searchParams.get("q") ?? ""
  const offset = Number.parseInt(searchParams.get("offset") ?? "0", 10) || 0

  const [entities, setEntities] = useState<Entity[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  /** 输入框的即时值 —— 防抖后才写进 URL */
  const [keyword, setKeyword] = useState(q)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .listEntities({ type: type || undefined, q: q || undefined, limit: PAGE_SIZE, offset })
      .then((r) => {
        setEntities(r.entities)
        setCount(r.count)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [type, q, offset])

  useEffect(load, [load])

  // 关键词防抖 300ms —— 否则每敲一个字就打一次生产 API
  useEffect(() => {
    if (keyword === q) return
    const t = setTimeout(() => {
      const next = new URLSearchParams(searchParams)
      if (keyword) next.set("q", keyword)
      else next.delete("q")
      next.delete("offset") // 换关键词 → 回到第一页
      setSearchParams(next)
    }, 300)
    return () => clearTimeout(t)
  }, [keyword, q, searchParams, setSearchParams])

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setSearchParams(next)
  }

  const hasPrev = offset > 0
  const hasNext = count === PAGE_SIZE

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6">
        <div className="max-w-5xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">
            ← 返回首页
          </Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100">
            知识图谱实体
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            共 {count} 个实体{count === PAGE_SIZE ? "(本页)" : ""} · 点实体看关联条文
          </p>

          <div className="mt-4">
            <input
              type="search"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜实体名(如 维生素C / 经营者)"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-primary dark:focus:ring-primary-dark"
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.value || "all"}
                onClick={() => update({ type: f.value || null, offset: null })}
                className={`text-xs px-3 py-1.5 rounded-full border transition ${
                  type === f.value
                    ? "bg-primary text-white border-primary dark:bg-primary-dark dark:border-primary-dark"
                    : "bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-primary"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 sm:px-8 py-8 space-y-6">
        <AsyncState
          loading={loading}
          error={error}
          isEmpty={!loading && !error && entities.length === 0}
          emptyText="没有匹配的实体 —— 换个关键词或类型试试"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {entities.map((e) => (
              <Link
                key={e.entity_id}
                to={`/entity/${encodeURIComponent(e.name)}`}
                className="block p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm transition"
              >
                <div className="flex items-baseline gap-2">
                  <h3 className="font-semibold text-slate-900 dark:text-slate-100 break-all">
                    {e.name}
                  </h3>
                  <span className="text-xs px-1.5 py-0.5 rounded shrink-0 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
                    {e.type}
                  </span>
                </div>
                {e.description && (
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 line-clamp-2">
                    {e.description}
                  </p>
                )}
              </Link>
            ))}
          </div>

          {(hasPrev || hasNext) && (
            <div className="flex items-center justify-between pt-4">
              <button
                onClick={() => update({ offset: String(Math.max(offset - PAGE_SIZE, 0)) })}
                disabled={!hasPrev}
                className="px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm disabled:opacity-40 hover:border-primary disabled:hover:border-slate-200"
              >
                ← 上一页
              </button>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                第 {Math.floor(offset / PAGE_SIZE) + 1} 页
              </span>
              <button
                onClick={() => update({ offset: String(offset + PAGE_SIZE) })}
                disabled={!hasNext}
                className="px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm disabled:opacity-40 hover:primary hover:border-primary disabled:hover:border-slate-200"
              >
                下一页 →
              </button>
            </div>
          )}
        </AsyncState>
      </main>
    </Layout>
  )
}
