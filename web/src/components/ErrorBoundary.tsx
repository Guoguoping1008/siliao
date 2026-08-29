import { Component, ErrorInfo, ReactNode } from "react"

/**
 * 全局错误边界:捕获子树抛错,显示降级 UI 而非白屏
 *
 * 设计原则:
 * - 不静默吞错:console.error 留痕
 * - 不自动恢复:让用户决定 reload(避免错乱状态循环)
 * - 提供"回到首页"逃生通道
 *
 * React 19+ 提供更优雅的 errorBoundary API,这里用 class 写法保持兼容
 */

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error?: Error
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 在真实环境这里应该上报 Sentry / 自建日志
    // 本地开发用 console.error 留痕
    console.error("[ErrorBoundary]", error.message, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return <ErrorFallback error={this.state.error} />
    }
    return this.props.children
  }
}

function ErrorFallback({ error }: { error?: Error }) {
  const handleReload = () => window.location.reload()
  const handleHome = () => {
    window.location.href = "/"
  }
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950 px-4">
      <div className="max-w-md w-full p-8 bg-white dark:bg-slate-900 rounded-lg shadow-lg border border-red-200 dark:border-red-800">
        <div className="text-5xl mb-4">⚠️</div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">
          出错了
        </h1>
        <p className="text-slate-600 dark:text-slate-400 mb-4">
          页面遇到意外错误,已记录到控制台。
        </p>
        {error && (
          <details className="mb-6 text-xs text-slate-500 dark:text-slate-500 bg-slate-50 dark:bg-slate-800 p-3 rounded">
            <summary className="cursor-pointer font-medium">错误详情</summary>
            <pre className="mt-2 whitespace-pre-wrap break-all">{error.message}</pre>
          </details>
        )}
        <div className="flex gap-3">
          <button
            onClick={handleHome}
            className="flex-1 px-4 py-2 bg-primary text-white rounded-lg hover:bg-blue-700"
          >
            返回首页
          </button>
          <button
            onClick={handleReload}
            className="flex-1 px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-900 dark:text-slate-100 rounded-lg hover:bg-slate-300"
          >
            重新加载
          </button>
        </div>
      </div>
    </div>
  )
}
