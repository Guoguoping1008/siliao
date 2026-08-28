import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../lib/api"
import type { CitationItem, SearchHit } from "../lib/api"
import { SearchBar } from "../components/SearchBar"
import { Layout } from "../components/Layout"
import { isMockMode } from "../lib/api"

/**
 * RAG 问答页: 用户输入问题,后端 streaming 返回答案 + 引用校验
 *
 * 事件流:
 *   meta    → 拿到检索证据(retrieval)
 *   chunk×N → LLM 增量输出 answer
 *   done    → 校验后的 citations 列表
 *   error   → 流式错误
 */
export function QAPage() {
  const [question, setQuestion] = useState("")
  const [retrieval, setRetrieval] = useState<SearchHit[]>([])
  const [answer, setAnswer] = useState("")
  const [citations, setCitations] = useState<CitationItem[]>([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<Array<{ q: string; a: string; t: number }>>([])
  const abortRef = useRef<(() => void) | null>(null)

  const ask = (q: string) => {
    const trimmed = q.trim()
    if (!trimmed || streaming) return
    setQuestion(trimmed)
    setRetrieval([])
    setAnswer("")
    setCitations([])
    setError(null)
    setStreaming(true)

    abortRef.current = api.qaStream(trimmed, {
      onMeta: e => setRetrieval(e.retrieval),
      onChunk: e => setAnswer(prev => prev + e.delta),
      onDone: e => setCitations(e.citations),
      onError: e => setError(e.message ?? `LLM 调用失败 (${e.status ?? "?"})`),
    })
    setStreaming(false) // 流开始,UI 让用户看到 streaming 状态
    // 用 setTimeout 让 streaming state 真切到 true 后再 false
    setTimeout(() => setStreaming(true), 0)
  }

  // 卸载时取消 streaming
  useEffect(() => () => abortRef.current?.(), [])

  const stop = () => {
    abortRef.current?.()
    setStreaming(false)
  }

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6 sticky top-12 z-10">
        <div className="max-w-4xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100">AI 问答</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            基于检索证据的回答 · 所有引用条款可在底部点击跳转
          </p>
          <div className="mt-4">
            <SearchBar defaultValue={question} />
          </div>
          <div className="mt-3 flex gap-2">
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  ask(question)
                }
              }}
              placeholder="例:饲料添加剂审定需要哪些材料?"
              className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
            />
            {streaming ? (
              <button
                onClick={stop}
                className="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                停止
              </button>
            ) : (
              <button
                onClick={() => ask(question)}
                disabled={!question.trim()}
                className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                提问
              </button>
            )}
          </div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {isMockMode ? "Mock 模式 · 无 LLM" : "生产模式 · DeepSeek"} · 当前 {retrieval.length} 条证据 · {streaming && "生成中..."}
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 space-y-6">
        {error && (
          <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
            ⚠️ {error}
          </div>
        )}

        {(answer || streaming) && (
          <section className="p-6 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-3">答案</h2>
            <div className="prose prose-slate dark:prose-invert max-w-none">
              <p className="whitespace-pre-wrap text-slate-900 dark:text-slate-100">
                {answer || (streaming ? "..." : "")}
                {streaming && <span className="inline-block w-2 h-4 ml-0.5 bg-primary animate-pulse" />}
              </p>
            </div>
          </section>
        )}

        {retrieval.length > 0 && (
          <section className="p-6 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-3">
              检索证据({retrieval.length})
            </h2>
            <ol className="space-y-2">
              {retrieval.map((h, i) => {
                const c = citations.find(c => c.ref === i + 1)
                const used = c?.valid
                return (
                  <li key={h.article_id}>
                    <Link
                      to={`/doc/${h.doc_id}/chapter/${h.chapter_id}#${h.article_id}`}
                      className={`flex items-start gap-3 p-3 rounded-lg border transition ${
                        used
                          ? "border-primary/40 bg-primary/5 dark:border-primary-dark/40 dark:bg-primary-dark/10 hover:border-primary"
                          : "border-slate-200 dark:border-slate-700 hover:border-slate-300"
                      }`}
                    >
                      <span className="text-xs font-mono px-2 py-0.5 bg-slate-100 dark:bg-slate-800 rounded flex-shrink-0">
                        [{i + 1}]
                      </span>
                      <span className="flex-1">
                        <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                          {h.chapter_number} {h.chapter_title} · {h.article_number}
                        </div>
                        <p className="text-xs text-slate-600 dark:text-slate-400 mt-1 line-clamp-2">
                          {h.excerpt}
                        </p>
                      </span>
                      {used ? (
                        <span className="text-xs text-primary dark:text-primary-dark flex-shrink-0">已引用 ✓</span>
                      ) : (
                        <span className="text-xs text-slate-400 flex-shrink-0">未引用</span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ol>
          </section>
        )}

        {citations.length > 0 && (
          <section className="p-6 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-3">
              引用校验({citations.filter(c => c.valid).length}/{citations.length} 通过)
            </h2>
            {citations.some(c => !c.valid) && (
              <p className="text-xs text-amber-600 dark:text-amber-400 mb-2">
                ⚠️ 以下编号在证据中不存在,可能是 LLM 编造:
                {citations.filter(c => !c.valid).map(c => ` [${c.ref}]`).join("")}
              </p>
            )}
            <ol className="space-y-1 text-sm">
              {citations.map(c => (
                <li key={c.ref} className={c.valid ? "text-slate-700 dark:text-slate-300" : "text-red-600 dark:text-red-400"}>
                  [{c.ref}] {c.valid ? `${c.chapter_number} ${c.chapter_title} · ${c.article_number}` : "� 无效引用"}
                </li>
              ))}
            </ol>
          </section>
        )}

        {history.length > 0 && (
          <section>
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-3">历史</h2>
            <ul className="space-y-1 text-sm">
              {history.map((h, i) => (
                <li key={i}>
                  <button
                    onClick={() => ask(h.q)}
                    className="text-primary dark:text-primary-dark hover:underline"
                  >
                    {h.q}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>

      <div className="text-center text-xs text-slate-400 dark:text-slate-600 py-4">
        阶段二 · RAG QA streaming + citation 校验
      </div>
    </Layout>
  )
}
