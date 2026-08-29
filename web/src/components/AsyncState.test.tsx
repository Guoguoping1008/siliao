/**
 * AsyncState 单测
 *
 * 5 个页面都用它,行为错了 = 5 个页面同时错。
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AsyncState } from "./AsyncState"

describe("AsyncState", () => {
  it("loading=true 时显示 spinner + 文案", () => {
    render(
      <AsyncState loading={true} loadingText="加载法规...">
        <div data-testid="content">真实内容</div>
      </AsyncState>
    )
    expect(screen.getByText("加载法规...")).toBeInTheDocument()
    expect(screen.queryByTestId("content")).not.toBeInTheDocument()
  })

  it("error 时显示错误信息 + 重试按钮", async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(
      <AsyncState loading={false} error={new Error("网络挂了")} onRetry={onRetry}>
        <div data-testid="content">不应显示</div>
      </AsyncState>
    )
    // 文本里有 emoji + 空格,testing-library 默认 exact 匹配会找不到
    // 用正则匹配核心文案
    expect(screen.getByText(/加载失败/)).toBeInTheDocument()
    expect(screen.getByText("网络挂了")).toBeInTheDocument()
    expect(screen.queryByTestId("content")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "重试" }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it("error 是字符串也能显示", () => {
    render(
      <AsyncState loading={false} error="字符串错误">
        <div>child</div>
      </AsyncState>
    )
    expect(screen.getByText("字符串错误")).toBeInTheDocument()
  })

  it("error 但无 onRetry 时不显示重试按钮", () => {
    render(
      <AsyncState loading={false} error={new Error("err")}>
        <div>child</div>
      </AsyncState>
    )
    expect(screen.queryByRole("button", { name: /重试/ })).not.toBeInTheDocument()
  })

  it("loading=false + error=null + isEmpty=true 时显示 empty", () => {
    render(
      <AsyncState
        loading={false}
        isEmpty={true}
        emptyText="暂无章节"
        emptyHint="先跑 ingest.sh"
      >
        <div>child</div>
      </AsyncState>
    )
    expect(screen.getByText("暂无章节")).toBeInTheDocument()
    expect(screen.getByText("先跑 ingest.sh")).toBeInTheDocument()
    expect(screen.queryByText("child")).not.toBeInTheDocument()
  })

  it("三态都为否时正常渲染 children", () => {
    render(
      <AsyncState loading={false}>
        <div data-testid="content">真实数据</div>
      </AsyncState>
    )
    expect(screen.getByTestId("content")).toBeInTheDocument()
  })

  it("priority:loading > error > empty > children", () => {
    // 全部为真时,只显示 loading(避免 spinner 闪烁)
    render(
      <AsyncState
        loading={true}
        error={new Error("err")}
        isEmpty={true}
      >
        <div>child</div>
      </AsyncState>
    )
    expect(screen.queryByText("加载失败")).not.toBeInTheDocument()
    expect(screen.queryByText("暂无数据")).not.toBeInTheDocument()
    expect(screen.queryByText("child")).not.toBeInTheDocument()
  })
})
