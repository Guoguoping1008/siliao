import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../lib/api"
import type { Document } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { DocumentCard } from "../components/DocumentCard"
import { isMockMode } from "../lib/api"

export function HomePage() {
  const [docs, setDocs] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listDocuments().finally(() => setLoading(false)).then(setDocs)
  }, [])

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-3xl mx-auto px-4 sm:px-8 py-8 sm:py-12">
          <h1 className="text-3xl sm:text-4xl font-bold text-primary">农业饲料法规知识库</h1>
          <p className="mt-2 text-slate-600">
            基于《中国农业饲料法规》按章节切分的智能检索 · 支持扫描版增量更新
          </p>
          <div className="mt-6">
            <SearchBar />
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-8 py-8">
        <h2 className="text-lg font-semibold mb-4">法规库</h2>
        {loading ? (
          <div className="text-slate-500">加载中...</div>
        ) : docs.length === 0 ? (
          <div className="text-slate-500">暂无收录法规。请把法规文件放进 data/raw/ 后跑 bash build/ingest.sh。</div>
        ) : (
          <div className="grid gap-3">
            {docs.map(d => <DocumentCard key={d.doc_id} doc={d} />)}
          </div>
        )}
      </main>

      <footer className="text-center text-xs text-slate-400 py-6">
        {isMockMode ? "Mock 模式 · 离线数据" : "生产模式 · Cloudflare Workers"}
        <div className="mt-1">阶段 F · Vite + React 18 + Tailwind</div>
      </footer>
    </div>
  )
}