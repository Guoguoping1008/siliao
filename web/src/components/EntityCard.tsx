/**
 * 实体卡: 显示一个实体及其关联条文
 * 用法: <EntityCard name="农业农村部" />
 *       点击后跳到 /entity/农业农村部
 */
import { Link } from "react-router-dom"

interface Props {
  name: string
  type?: string
  description?: string
  href?: string  // 自定义跳转(可选)
}

const TYPE_COLOR: Record<string, string> = {
  AGENCY: "bg-purple-100 text-purple-700",
  PARTY: "bg-blue-100 text-blue-700",
  CERTIFICATE: "bg-amber-100 text-amber-700",
  DOCUMENT: "bg-green-100 text-green-700",
  LAW: "bg-red-100 text-red-700",
}

export function EntityCard({ name, type = "ENTITY", description, href }: Props) {
  const target = href || `/entity/${encodeURIComponent(name)}`
  return (
    <Link
      to={target}
      className="block p-4 bg-white rounded-lg border border-slate-200 hover:border-primary hover:shadow-sm transition"
    >
      <div className="flex items-baseline gap-2">
        <h3 className="font-semibold text-slate-900">{name}</h3>
        <span className={`text-xs px-1.5 py-0.5 rounded ${TYPE_COLOR[type] || "bg-slate-100 text-slate-600"}`}>
          {type}
        </span>
      </div>
      {description && (
        <p className="mt-2 text-sm text-slate-600 line-clamp-2">{description}</p>
      )}
    </Link>
  )
}