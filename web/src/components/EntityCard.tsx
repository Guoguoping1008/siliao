/**
 * 实体卡: 显示一个实体及其关联条文
 */
import { Link } from "react-router-dom"

interface Props {
  name: string
  type?: string
  description?: string
  href?: string
}

const TYPE_COLOR: Record<string, string> = {
  AGENCY: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
  PARTY: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  CERTIFICATE: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  DOCUMENT: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
  LAW: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
}

export function EntityCard({ name, type = "ENTITY", description, href }: Props) {
  const target = href || `/entity/${encodeURIComponent(name)}`
  return (
    <Link
      to={target}
      className="block p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700 hover:border-primary dark:hover:border-primary-dark hover:shadow-sm transition"
    >
      <div className="flex items-baseline gap-2">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">{name}</h3>
        <span className={`text-xs px-1.5 py-0.5 rounded ${TYPE_COLOR[type] || "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300"}`}>
          {type}
        </span>
      </div>
      {description && (
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400 line-clamp-2">{description}</p>
      )}
    </Link>
  )
}