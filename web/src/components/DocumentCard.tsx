import { Link } from "react-router-dom"
import type { Document } from "../lib/api"

interface Props {
  doc: Document
}

/**
 * 文档卡片: 显示标题、文号、生效日期、章节/条文计数
 */
export function DocumentCard({ doc }: Props) {
  return (
    <Link
      to={`/doc/${doc.doc_id}`}
      className="block p-4 bg-white rounded-lg border border-slate-200 hover:border-primary hover:shadow-sm transition"
    >
      <h3 className="font-semibold text-lg text-slate-900">{doc.title}</h3>
      <div className="mt-2 text-sm text-slate-500 space-y-0.5">
        {doc.doc_number && <div>文号:{doc.doc_number}</div>}
        {doc.issuer && <div>发布:{doc.issuer}</div>}
        {doc.effective_date && <div>生效:{doc.effective_date}</div>}
      </div>
      <div className="mt-3 flex gap-3 text-xs text-slate-600">
        <span className="px-2 py-0.5 bg-slate-100 rounded">{doc.chapter_count} 章</span>
        <span className="px-2 py-0.5 bg-slate-100 rounded">{doc.article_count} 条</span>
      </div>
    </Link>
  )
}