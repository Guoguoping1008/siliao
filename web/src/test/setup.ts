/**
 * vitest 全局 setup:在每个测试文件运行前加载
 * - jest-dom 匹配器(toBeInTheDocument 等)
 * - 全局 mock(window.matchMedia 等)
 */
import "@testing-library/jest-dom/vitest"
import { afterEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"

// jsdom 不实现 matchMedia,主题切换 hook 用到
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// localStorage 干净
afterEach(() => {
  cleanup()
  localStorage.clear()
})
