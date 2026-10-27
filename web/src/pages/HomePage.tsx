import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../lib/api"
import type { Document, Catalog } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { DocumentCard } from "../components/DocumentCard"
import { CatalogTree } from "../components/CatalogTree"
import { Layout } from "../components/Layout"
import { AsyncState } from "../components/AsyncState"
import { isMockMode } from "../lib/api"

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-selected={active}
      role="tab"
      className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition ${
        active
          ? "border-primary text-primary dark:border-primary-dark dark:text-primary-dark"
          : "border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300"
      }`}
    >
      {children}
    </button>
  )
}

export function HomePage() {
  const [docs, setDocs] = useState<Document[]>([])
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [view, setView] = useState<"list" | "catalog">("list")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    api.listDocuments()
      .then(setDocs)
      .catch(setError)
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  // 目录树单独加载 —— 失败不该影响法规库列表(两者是独立视图)
  useEffect(() => {
    api.getCatalog()
      .then(setCatalog)
      .catch(() => setCatalog(null))
  }, [])

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800">
        <div className="max-w-3xl mx-auto px-4 sm:px-8 py-8 sm:py-12">
          <h1 className="text-3xl sm:text-4xl font-bold text-primary dark:text-primary-dark">农业饲料法规知识库</h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            基于《中国农业饲料法规》按章节切分的智能检索 · 支持扫描版增量更新
          </p>
          <div className="mt-6">
            <SearchBar />
          </div>
        </div>
      </header>

      <section id="library" className="max-w-3xl mx-auto px-4 sm:px-8 py-8">
        {/* 两个视图: 平铺列表(找特定法规) / 目录树(看书的分类结构)
            ⚠️ 用 tab 切换而不是上下都铺开 —— 196 个卡片 + 178 个目录项
            同时渲染会让首屏非常长。默认显示平铺列表(更常用)。 */}
        <div className="flex items-center gap-1 mb-4 border-b border-slate-200 dark:border-slate-800">
          <TabButton active={view === "list"} onClick={() => setView("list")}>
            法规库
          </TabButton>
          <TabButton active={view === "catalog"} onClick={() => setView("catalog")}>
            目录
            {catalog?.stats && (
              <span className="ml-1.5 text-xs text-slate-400 dark:text-slate-600">
                {catalog.stats.docs}
              </span>
            )}
          </TabButton>
        </div>

        {view === "list" ? (
          <AsyncState
            loading={loading}
            error={error}
            isEmpty={!loading && !error && docs.length === 0}
            emptyText="暂无法规收录"
            emptyHint="请把法规文件放进 data/raw/ 后跑 bash build/run_all.sh"
            onRetry={load}
            loadingText="加载法规列表..."
          >
            <div className="grid gap-3">
              {docs.map(d => <DocumentCard key={d.doc_id} doc={d} />)}
            </div>
          </AsyncState>
        ) : (
          catalog ? (
            <CatalogTree catalog={catalog} />
          ) : (
            <p className="text-sm text-slate-500 dark:text-slate-400 py-4">
              加载目录...
            </p>
          )
        )}
      </section>

      <div className="text-center text-xs text-slate-400 dark:text-slate-600 py-4">
        {isMockMode ? "Mock 模式 · 离线数据" : "生产模式 · Cloudflare Workers"}
      </div>

      {/* 运维文档入口
          ⚠️ 这是**部署运维指南**, 不是给法规查询用户看的功能 ——
          所以放页脚, 不进顶部主导航(主导航是「首页/目录/搜索/问答/实体」,
          加一条运维文档会稀释主流程, 移动端底栏只有 4 格也放不下)。
          用 <a> 而不是 <Link>: 它指向的是 public/ 下的静态 HTML,
          不是 React 路由, 走 <Link> 会被 router 拦截成 SPA 路由。 */}
      <div className="max-w-3xl mx-auto px-4 sm:px-8 pb-8">
        <div className="border-t border-slate-200 dark:border-slate-800 pt-4">
          <a
            href="/cloudflare-token-setup-guide.html"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400 hover:text-primary dark:hover:text-primary-dark transition"
          >
            <span aria-hidden="true">📘</span>
            <span>部署运维指南</span>
            <span className="text-xs text-slate-400 dark:text-slate-600">(Cloudflare Token 配置 · 新窗口打开)</span>
          </a>
        </div>
      </div>
    </Layout>
  )
}
