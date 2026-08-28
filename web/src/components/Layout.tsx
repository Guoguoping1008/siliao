import { useEffect, useState } from "react"
import { Link, useLocation } from "react-router-dom"
import { ThemeToggle } from "../hooks/useTheme"
import { useGlobalShortcuts } from "../hooks/useGlobalShortcuts"

interface Props {
  children: React.ReactNode
}

interface NavLink {
  path: string
  label: string
  icon: string
}

const NAV_LINKS: NavLink[] = [
  { path: "/", label: "首页", icon: "🏠" },
  { path: "/doc/feed-law-2026", label: "目录", icon: "📖" },
  { path: "/search", label: "搜索", icon: "🔍" },
  { path: "/qa", label: "AI 问答", icon: "💬" },
  { path: "/entity/农业农村部", label: "实体", icon: "🏛" },
]

/**
 * 全局布局: 顶栏 + 主区 + 移动端底部导航
 * 主题切换 + 当前模式标识
 */
export function Layout({ children }: Props) {
  const location = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)

  // 全局快捷键: Esc 关抽屉
  useGlobalShortcuts({ onEscape: () => setDrawerOpen(false) })

  // 路由变化时关闭抽屉
  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 transition-colors pb-16 md:pb-0">
      {/* 顶栏(桌面 + 移动) */}
      <nav className="sticky top-0 z-30 bg-white/80 dark:bg-slate-900/80 backdrop-blur border-b border-slate-200 dark:border-slate-800">
        <div className="max-w-5xl mx-auto px-4 sm:px-8 h-12 flex items-center gap-3">
          {/* 移动端抽屉按钮 */}
          <button
            onClick={() => setDrawerOpen(true)}
            className="md:hidden p-2 -ml-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="打开菜单"
          >
            ☰
          </button>

          <Link to="/" className="font-semibold text-slate-900 dark:text-slate-100 hover:text-primary dark:hover:text-primary-dark">
            农业饲料法规
          </Link>
          <span className="hidden sm:inline text-xs text-slate-400">· 知识库</span>
          <span className="flex-1" />

          {/* 桌面导航 */}
          <div className="hidden md:flex items-center gap-2 text-sm">
            {NAV_LINKS.map(l => (
              <Link
                key={l.path}
                to={l.path}
                className={`px-3 py-1.5 rounded-lg transition ${
                  location.pathname === l.path.split("?")[0]
                    ? "bg-primary/10 text-primary dark:bg-primary-dark/20 dark:text-primary-dark"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
                }`}
              >
                <span className="mr-1">{l.icon}</span>{l.label}
              </Link>
            ))}
          </div>

          <ThemeToggle />
        </div>
      </nav>

      {/* 抽屉(移动) */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="absolute left-0 top-0 bottom-0 w-64 bg-white dark:bg-slate-900 shadow-lg p-4">
            <div className="flex items-center justify-between mb-4">
              <span className="font-semibold">导航</span>
              <button
                onClick={() => setDrawerOpen(false)}
                className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="关闭"
              >
                ✕
              </button>
            </div>
            <nav className="flex flex-col gap-1">
              {NAV_LINKS.map(l => (
                <Link
                  key={l.path}
                  to={l.path}
                  className="flex items-center gap-2 p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
                >
                  <span>{l.icon}</span>{l.label}
                </Link>
              ))}
            </nav>
          </aside>
        </div>
      )}

      <main className="text-slate-900 dark:text-slate-100">
        {children}
      </main>

      {/* 底部导航(仅移动) */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-30 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800">
        <div className="grid grid-cols-4 h-16">
          {NAV_LINKS.map(l => (
            <Link
              key={l.path}
              to={l.path}
              className={`flex flex-col items-center justify-center text-xs transition ${
                location.pathname === l.path.split("?")[0]
                  ? "text-primary dark:text-primary-dark"
                  : "text-slate-500 dark:text-slate-400"
              }`}
            >
              <span className="text-xl">{l.icon}</span>
              <span className="mt-0.5">{l.label}</span>
            </Link>
          ))}
        </div>
      </nav>

      <footer className="hidden md:block text-center text-xs text-slate-400 dark:text-slate-600 py-6">
        <div>
          <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 rounded border border-slate-300 dark:border-slate-700">/</kbd>
          {" "}搜索 ·{" "}
          <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 rounded border border-slate-300 dark:border-slate-700">g h</kbd>
          {" "}首页 ·{" "}
          <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 rounded border border-slate-300 dark:border-slate-700">g d</kbd>
          {" "}目录
        </div>
        <div className="mt-1">阶段 F 增强 · 深色模式 + 移动端导航 + 实体图谱</div>
      </footer>
    </div>
  )
}