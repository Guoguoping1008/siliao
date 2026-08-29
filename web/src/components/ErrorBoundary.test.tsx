/**
 * ErrorBoundary 单测
 *
 * 关键防御层:任一子组件抛错都不应让整页白屏
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { ErrorBoundary } from "./ErrorBoundary"

// 抛错组件 — 渲染时 throw
function Bomb({ shouldThrow = true }: { shouldThrow?: boolean }) {
  if (shouldThrow) throw new Error("💣 测试炸弹")
  return <div>正常内容</div>
}

describe("ErrorBoundary", () => {
  it("正常子组件不受影响", () => {
    render(
      <ErrorBoundary>
        <div>正常内容</div>
      </ErrorBoundary>
    )
    expect(screen.getByText("正常内容")).toBeInTheDocument()
  })

  it("子组件抛错时显示降级 UI", () => {
    // 静默 console.error(React 会打印)
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})

    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    )
    expect(screen.getByText("出错了")).toBeInTheDocument()
    expect(screen.getByText(/返回首页/)).toBeInTheDocument()
    expect(screen.getByText(/重新加载/)).toBeInTheDocument()
    spy.mockRestore()
  })

  it("降级 UI 显示错误详情(可折叠)", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    )
    expect(screen.getByText("错误详情")).toBeInTheDocument()
    // <details> 默认折叠,内容存在但展开看
    const details = document.querySelector("details")
    expect(details).not.toBeNull()
    expect(details?.textContent).toContain("💣 测试炸弹")
    spy.mockRestore()
  })

  it("自定义 fallback 优先于默认", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    render(
      <ErrorBoundary fallback={<div data-testid="custom">自定义降级</div>}>
        <Bomb />
      </ErrorBoundary>
    )
    expect(screen.getByTestId("custom")).toBeInTheDocument()
    expect(screen.queryByText("出错了")).not.toBeInTheDocument()
    spy.mockRestore()
  })

  it("抛错信息会被 console.error 记录", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>
    )
    expect(spy).toHaveBeenCalled()
    expect(spy.mock.calls.some(c =>
      String(c[0]).includes("ErrorBoundary") ||
      String(c[1] ?? "").includes("测试炸弹")
    )).toBe(true)
    spy.mockRestore()
  })
})
