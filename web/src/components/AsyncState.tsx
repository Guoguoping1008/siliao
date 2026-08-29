import { ReactNode } from "react"

/**
 * AsyncState: 统一封装 loading / empty / error 三态
 *
 * 用法:
 *   <AsyncState
 *     loading={loading}
 *     error={error}
 *     isEmpty={docs.length === 0}
 *     emptyText="暂无法规"
 *     onRetry={refetch}
 *   >
 *     {docs.map(d => <Card ... />)}
 *   </AsyncState>
 */

interface Props {
  loading: boolean
  error?: Error | string | null
  isEmpty?: boolean
  emptyText?: string
  emptyHint?: string
  onRetry?: () => void
  loadingText?: string
  children: ReactNode
}

export function AsyncState({
  loading,
  error,
  isEmpty = false,
  emptyText = "暂无数据",
  emptyHint,
  onRetry,
  loadingText = "加载中...",
  children,
}: Props) {
  if (loading) {
    return (
      <div className="p-8 text-center text-slate-500 dark:text-slate-400">
        <div className="inline-block w-6 h-6 border-2 border-slate-300 border-t-primary rounded-full animate-spin mb-3" />
        <div>{loadingText}</div>
      </div>
    )
  }

  if (error) {
    const message = error instanceof Error ? error.message : String(error)
    return (
      <div className="p-8 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
        <div className="text-red-700 dark:text-red-300 font-medium mb-1">
          ⚠️ 加载失败
        </div>
        <div className="text-sm text-red-600 dark:text-red-400 mb-3">{message}</div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 text-sm"
          >
            重试
          </button>
        )}
      </div>
    )
  }

  if (isEmpty) {
    return (
      <div className="p-8 text-center text-slate-500 dark:text-slate-400">
        <div className="text-3xl mb-2">📭</div>
        <div className="font-medium mb-1">{emptyText}</div>
        {emptyHint && <div className="text-sm">{emptyHint}</div>}
      </div>
    )
  }

  return <>{children}</>
}
