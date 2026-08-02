/**
 * 主题切换: light / dark / system
 * 持久化到 localStorage
 * 默认 system(跟随 OS)
 *
 * 用法:
 *   const { theme, setTheme, resolvedTheme } = useTheme()
 *   <button onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}>
 */

import { useEffect, useState, useCallback } from "react"

export type Theme = "light" | "dark" | "system"
export type ResolvedTheme = "light" | "dark"

const STORAGE_KEY = "siliao.theme"

function getSystemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light"
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function readStoredTheme(): Theme {
  if (typeof window === "undefined") return "system"
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === "light" || stored === "dark" || stored === "system") return stored
  return "system"
}

function applyTheme(resolved: ResolvedTheme) {
  const root = document.documentElement
  root.classList.toggle("dark", resolved === "dark")
  root.style.colorScheme = resolved
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme)
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>(getSystemTheme)

  const resolvedTheme: ResolvedTheme = theme === "system" ? systemTheme : theme

  // 应用主题到 DOM
  useEffect(() => {
    applyTheme(resolvedTheme)
  }, [resolvedTheme])

  // 监听系统主题变化
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const handler = () => setSystemTheme(mq.matches ? "dark" : "light")
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [])

  // 持久化
  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    window.localStorage.setItem(STORAGE_KEY, t)
  }, [])

  // 切换下一档(light <-> dark)
  const toggle = useCallback(() => {
    setTheme(resolvedTheme === "dark" ? "light" : "dark")
  }, [resolvedTheme, setTheme])

  return { theme, setTheme, resolvedTheme, toggle }
}

/**
 * 主题切换按钮组件(自包含)
 * 渲染: 🌙 / ☀️ 图标
 */
export function ThemeToggle() {
  const { resolvedTheme, toggle } = useTheme()
  return (
    <button
      onClick={toggle}
      title={resolvedTheme === "dark" ? "切换到浅色" : "切换到深色"}
      className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition"
      aria-label="切换主题"
    >
      {resolvedTheme === "dark" ? "🌙" : "☀️"}
    </button>
  )
}