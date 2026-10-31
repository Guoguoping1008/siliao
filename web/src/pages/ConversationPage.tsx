import { useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { api } from "../lib/api"
import type { CitationItem, SearchHit } from "../lib/api"
import { Layout } from "../components/Layout"
import { isMockMode } from "../lib/api"

/**
 * 多轮问答页(C1.5)
 *
 * 与 /qa 页的区别:
 *   · 有**会话状态** —— 追问能接住上一轮的主语
 *   · 展示 `resolvedQuery` —— 让用户看到系统补全成了什么
 *
 * 为什么展示 resolvedQuery:
 *   指代消解是系统的**推断**。用户看到「那鸡呢?」被补成
 *   「维生素C 那鸡呢?」才能判断这个推断对不对 —— 不透明的黑箱在
 *   合规场景是危险的。
 *
 * ⚠️ 非流式: 多轮 prompt 带历史, 流式增量不好配合, 且追问通常很短。
 */

/** 生成会话 id(不引 uuid 依赖, 用 crypto.randomUUID 兜底时间戳)。 */
function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID()
  }
  return `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** 一轮对话(用于界面展示)。 */
interface Turn {
  question: string
  answer: string
  resolvedQuery: string
  citations: CitationItem[]
  retrieval: SearchHit[]
}

export function ConversationPage() {
  const [sessionId, setSessionId] = useState<string>(newSessionId)
  const [question, setQuestion] = useState("")
  const [turns, setTurns] = useState<Turn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 新会话
  const reset = async () => {
    try {
      await api.clearConversation(sessionId)
    } catch {
      // 清空失败不阻塞 —— 旧会话留在 D1 里也只是占点空间
    }
    setSessionId(newSessionId())
    setTurns([])
    setError(null)
  }

  const ask = async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed || loading) return
    setQuestion("")
    setError(null)
    setLoading(true)
    try {
      const r = await api.conversation(sessionId, trimmed)
      setTurns(prev => [
        ...prev,
        {
          question: trimmed,
          answer: r.answer,
          resolvedQuery: r.resolvedQuery,
          citations: r.citations,
          retrieval: r.retrieval,
        },
      ])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // 滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [turns, loading])

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6 sticky top-12 z-10">
        <div className="max-w-4xl mx-auto">
          <Link to="/" className="text-sm text-primary dark:text-primary-dark hover:underline">← 返回首页</Link>
          <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900 dark:text-slate-100">
            多轮问答
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            支持追问 —— 「那鸡呢?」能接住上一轮的主语
          </p>
          <div className="mt-4 flex gap-2">
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
              placeholder="例:维生素C在猪饲料的上限是多少?  然后追问「那鸡呢?」"
              className="flex-1 px-4 py-2 border border-slate-300 dark:border-slate-700 dark:bg-slate-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <button
              onClick={() => ask(question)}
              disabled={!question.trim() || loading}
              className="px-6 py-2 bg-primary text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "思考中..." : "提问"}
            </button>
            <button
              onClick={reset}
              className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600"
              title="清空当前会话"
            >
              新会话
            </button>
          </div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {isMockMode ? "Mock 模式 · 无 LLM" : "生产模式"} · 会话 {sessionId.slice(0, 8)} · {turns.length} 轮
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-8 space-y-8">
        {error && (
          <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-red-700 dark:text-red-300">
            ⚠️ {error}
          </div>
        )}

        {turns.length === 0 && !loading && (
          <div className="text-center text-sm text-slate-500 dark:text-slate-400 py-12">
            <p className="font-medium mb-2">试试这样问:</p>
            <ul className="space-y-1 text-left max-w-md mx-auto">
              <li>· 维生素C在猪饲料中的使用量上限是多少?</li>
              <li>· 那鸡呢?</li>
              <li>· 饲料标签必须标注哪些内容?</li>
            </ul>
          </div>
        )}

        {turns.map((t, i) => {
          // 系统补全了上下文 → 明确告诉用户
          const resolved = t.resolvedQuery !== t.question
          return (
            <section key={i} className="space-y-4">
              {/* 用户问的 */}
              <div className="flex justify-end">
                <div className="max-w-[85%] px-4 py-2 bg-primary text-white rounded-lg rounded-br-sm">
                  {t.question}
                </div>
              </div>

              {/* 系统补全提示 —— 指代消解是推断, 必须可见 */}
              {resolved && (
                <div className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded px-3 py-2">
                  🔗 已结合上文补全检索词:「{t.resolvedQuery}」
                </div>
              )}

              {/* 答案 */}
              <div className="p-5 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
                <div className="prose prose-slate dark:prose-invert max-w-none">
                  <p className="whitespace-pre-wrap text-slate-900 dark:text-slate-100">
                    {t.answer}
                  </p>
                </div>
              </div>

              {/* 引用校验 */}
              {t.citations.length > 0 && (
                <div className="p-4 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-700">
                  <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-2">
                    引用校验({t.citations.filter(c => c.valid).length}/{t.citations.length} 通过)
                  </h3>
                  {t.citations.some(c => !c.valid) && (
                    <p className="text-xs text-amber-600 dark:text-amber-400 mb-2">
                      ⚠️ 以下编号在证据中不存在,可能是 LLM 编造:
                      {t.citations.filter(c => !c.valid).map(c => ` [${c.ref}]`).join("")}
                    </p>
                  )}
                  <ol className="space-y-1 text-sm">
                    {t.citations.map(c => (
                      <li key={c.ref} className={c.valid ? "text-slate-700 dark:text-slate-300" : "text-red-600 dark:text-red-400"}>
                        [{c.ref}] {c.valid
                          ? `${c.chapter_number} ${c.chapter_title} · ${c.article_number}`
                          : "� 无效引用"}
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {/* 检索证据 */}
              {t.retrieval.length > 0 && (
                <details className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-700">
                  <summary className="text-sm font-semibold text-slate-500 dark:text-slate-400 cursor-pointer">
                    检索证据({t.retrieval.length})
                  </summary>
                  <ol className="space-y-2 mt-3">
                    {t.retrieval.map((h, j) => {
                      const c = t.citations.find(c => c.ref === j + 1)
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
                              [{j + 1}]
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
                </details>
              )}
            </section>
          )
        })}

        {loading && (
          <div className="text-center text-sm text-slate-500 dark:text-slate-400">
            思考中...
          </div>
        )}

        <div ref={bottomRef} />
      </main>

      <div className="text-center text-xs text-slate-400 dark:text-slate-600 py-4">
        C1.5 · 多轮会话追问
      </div>
    </Layout>
  )
}
