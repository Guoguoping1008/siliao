/**
 * 全局快捷键
 *   /         聚焦搜索框
 *   g 然后 h  回首页(2 击)
 *   g 然后 d  去文档目录
 *   g 然后 s  去搜索页
 *   Esc       关闭抽屉
 */

import { useEffect, useRef } from "react"
import { useNavigate } from "react-router-dom"

export function useGlobalShortcuts(opts: { onEscape?: () => void } = {}) {
  const navigate = useNavigate()
  const lastG = useRef<number>(0)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      // 在输入框内不响应(允许正常输入)
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") {
        if (e.key === "Escape" && opts.onEscape) opts.onEscape()
        return
      }

      if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
        e.preventDefault()
        const search = document.querySelector<HTMLInputElement>("input[type=search]")
        search?.focus()
        return
      }

      // g-prefixed shortcuts(2 击,2 秒内)
      if (e.key === "g") {
        lastG.current = Date.now()
        return
      }
      if (Date.now() - lastG.current < 2000) {
        if (e.key === "h") navigate("/")
        if (e.key === "d") navigate("/doc/feed-law-2026")
        if (e.key === "s") navigate("/search")
        lastG.current = 0
      }

      if (e.key === "Escape" && opts.onEscape) opts.onEscape()
    }

    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [navigate, opts])
}