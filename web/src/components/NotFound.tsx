import { Link } from "react-router-dom"

/**
 * 404 友好页:不光说"页面不存在",给用户可点击出口
 */
export function NotFound() {
  return (
    <div className="min-h-[60vh] flex items-center justify-center px-4">
      <div className="max-w-lg w-full text-center">
        <div className="text-7xl mb-4">🔍</div>
        <h1 className="text-4xl font-bold text-slate-900 dark:text-slate-100 mb-2">
          404
        </h1>
        <p className="text-lg text-slate-600 dark:text-slate-400 mb-8">
          找不到这个页面
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            to="/"
            className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-blue-700"
          >
            � 返回首页
          </Link>
          <Link
            to="/search?q=饲料"
            className="px-6 py-3 bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-lg hover:bg-slate-300"
          >
            � 试试搜 "饲料"
          </Link>
          <Link
            to="/qa"
            className="px-6 py-3 bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-lg hover:bg-slate-300"
          >
            💬 AI 问答
          </Link>
        </div>
      </div>
    </div>
  )
}
