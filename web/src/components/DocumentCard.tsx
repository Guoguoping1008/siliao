import { Link } from "react-router-dom"
import type { Document } from "../lib/api"

interface Props {
  doc: Document
}

export function DocumentCard({ doc }: Props) {
  return (
    <Link
      to={`/doc/${doc.doc_id}`}
      className="block p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm dark:hover:shadow-slate-700/30 transition"
    >
      <h3 className="font-semibold text-lg text-slate-900 dark:text-slate-100">{doc.title}</h3>
      <div className="mt-2 text-sm text-slate-500 dark:text-slate-400 space-y-0.5">
        {doc.doc_number && <div>文号:{doc.doc_number}</div>}
        {doc.issuer && <div>发布:{doc.issuer}</div>}
        {doc.effective_date && <div>生效:{doc.effective_date}</div>}
      </div>
      <div className="mt-3 flex gap-3 text-xs text-slate-600 dark:text-slate-400">
        <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 rounded">{doc.chapter_count} 章</span>
        <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 rounded">{doc.article_count} 条</span>
      </div>
    </Link>
  )
}