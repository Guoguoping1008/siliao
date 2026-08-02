import { useState, FormEvent } from "react"
import { useNavigate } from "react-router-dom"

/**
 * 搜索栏: 回车跳转 /search?q=
 * 也支持点击搜索按钮
 */
export function SearchBar({ defaultValue = "" }: { defaultValue?: string }) {
  const [q, setQ] = useState(defaultValue)
  const navigate = useNavigate()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const trimmed = q.trim()
    if (trimmed) navigate(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  return (
    <form onSubmit={submit} className="flex gap-2">
      <input
        type="search"
        value={q}
        onChange={e => setQ(e.target.value)}
        placeholder="例:饲料添加剂审定 / 农业农村部 / 罚款"
        className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
      />
      <button
        type="submit"
        className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        disabled={!q.trim()}
      >
        搜索
      </button>
    </form>
  )
}