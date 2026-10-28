import { useState } from "react"
import { Link } from "react-router-dom"
import { api, isMockMode } from "../lib/api"
import type { ComplianceResult, ComplianceStatus } from "../lib/api"
import { Layout } from "../components/Layout"

/**
 * 用量合规速查页 (C1)
 *
 * 构想稿的核心场景:「这种预混料在猪饲料中的添加量合规吗?」
 *
 * ⚠️ 三个必须体现在 UI 上的设计决策:
 *
 * 1. **「未覆盖」是一等公民** —— 不用绿色显示「合规」蒙混过去,
 *    而是用醒目的琥珀色 + 「需人工确认」, 并附上检索到的相关条文。
 * 2. **依据条款原文必须可见** —— 每个结论都带 sourceExcerpt,
 *    用户能自己核对, 不必信任系统。
 * 3. **免责标注常驻** —— 「辅助意见, 不构成监管结论」。
 */

/** 判定状态 → 展示配置。 */
const STATUS_UI: Record<
  ComplianceStatus,
  { label: string; cls: string; icon: string; desc: string }
> = {
  compliant: {
    label: "合规",
    cls: "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-300 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300",
    icon: "✓",
    desc: "所填用量在法规规定的允许区间内",
  },
  exceeded: {
    label: "超限",
    cls: "bg-red-50 dark:bg-red-950/40 border-red-300 dark:border-red-800 text-red-800 dark:text-red-300",
    icon: "✕",
    desc: "所填用量超出法规允许区间",
  },
  prohibited: {
    label: "禁用",
    cls: "bg-red-100 dark:bg-red-950/60 border-red-400 dark:border-red-700 text-red-900 dark:text-red-200",
    icon: "⊘",
    desc: "该物质在该动物上被法规禁止使用",
  },
  not_covered: {
    label: "规则未覆盖",
    cls: "bg-amber-50 dark:bg-amber-950/40 border-amber-400 dark:border-amber-700 text-amber-900 dark:text-amber-200",
    icon: "?",
    desc: "规则库未覆盖该物质/动物组合 —— 需人工确认",
  },
}

/** 常用动物(下拉) */
const SPECIES = [
  "猪", "仔猪", "育肥猪", "肉鸡", "蛋鸡", "家禽", "牛", "犊牛", "羊",
  "鱼", "鲤鱼", "草鱼", "鲶鱼", "罗非鱼", "犬", "猫",
]

/** 常用单位 */
const UNITS = ["mg/kg", "g/kg", "IU/kg", "IU/g", "万IU/kg", "%"]

export function CompliancePage() {
  const [substance, setSubstance] = useState("")
  const [species, setSpecies] = useState("猪")
  const [stage, setStage] = useState("")
  const [value, setValue] = useState("")
  const [unit, setUnit] = useState("mg/kg")
  const [result, setResult] = useState<ComplianceResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const check = async () => {
    const num = Number(value)
    if (!substance.trim()) {
      setError("请填写物质名称")
      return
    }
    if (!value.trim() || !Number.isFinite(num) || num < 0) {
      setError("请填写有效的用量数值(非负数)")
      return
    }
    setError(null)
    setLoading(true)
    try {
      const r = await api.checkCompliance({
        substance: substance.trim(),
        species: species.trim(),
        stage: stage.trim() || null,
        value: num,
        unit,
      })
      setResult(r)
    } catch (e) {
      setError((e as Error).message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const ui = result ? STATUS_UI[result.status] : null

  return (
    <Layout>
      <header className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-8 py-6 sticky top-12 z-10">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100">
            用量合规速查
          </h1>
          <p className="text-sm text-slate-600 dark:text-slate-400 mt-1">
            输入物质、动物与用量,对照《饲料添加剂安全使用规范》等法规的限量规定给出判定,
            并附**依据条款原文**。
          </p>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-8 py-6 space-y-6">
        {/* ── 输入表单 ── */}
        <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block sm:col-span-2">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                物质名称 <span className="text-red-500">*</span>
              </span>
              <input
                type="text"
                value={substance}
                onChange={e => setSubstance(e.target.value)}
                placeholder="如: 维生素C / L-抗坏血酸 / 烟酰胺"
                className="mt-1 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
              <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
                支持中文名、英文名、简称(如「维生素C」会匹配到「L-抗坏血酸(维生素C)」)
              </span>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                动物种类 <span className="text-red-500">*</span>
              </span>
              <input
                type="text"
                list="species-list"
                value={species}
                onChange={e => setSpecies(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
              <datalist id="species-list">
                {SPECIES.map(s => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                阶段(可选)
              </span>
              <input
                type="text"
                value={stage}
                onChange={e => setStage(e.target.value)}
                placeholder="如: 育肥猪 / 鱼苗 / 乳猪"
                className="mt-1 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                用量 <span className="text-red-500">*</span>
              </span>
              <input
                type="number"
                min="0"
                step="any"
                value={value}
                onChange={e => setValue(e.target.value)}
                placeholder="如: 200"
                className="mt-1 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                单位 <span className="text-red-500">*</span>
              </span>
              <select
                value={unit}
                onChange={e => setUnit(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
              >
                {UNITS.map(u => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">⚠ {error}</p>
          )}

          <button
            onClick={check}
            disabled={loading}
            className="mt-4 px-4 py-2 rounded-md bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white text-sm font-medium"
          >
            {loading ? "判定中…" : "查询合规判定"}
          </button>
        </section>

        {/* ── 判定结果 ── */}
        {result && ui && (
          <section className="space-y-4">
            <div className={`border rounded-lg p-5 ${ui.cls}`}>
              <div className="flex items-start gap-3">
                <span className="text-2xl font-bold leading-none mt-0.5">{ui.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 flex-wrap">
                    <h2 className="text-lg font-bold">{ui.label}</h2>
                    {result.matchedSubstance && (
                      <span className="text-xs opacity-75">
                        匹配到标准名:{result.matchedSubstance}
                      </span>
                    )}
                  </div>
                  <p className="text-sm mt-1 opacity-90">{ui.desc}</p>
                  <p className="text-xs mt-2 opacity-70">
                    {result.usage.species}
                    {result.usage.stage ? ` / ${result.usage.stage}` : ""} ·{" "}
                    {result.usage.value} {result.usage.unit}
                  </p>
                </div>
              </div>
            </div>

            {/* 调整建议 */}
            {result.suggestion && (
              <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-4 bg-white dark:bg-slate-900">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  调整建议
                </h3>
                <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                  {result.suggestion.message}
                  {result.suggestion.maxAllowed > 0 && (
                    <>
                      ;允许上限为{" "}
                      <strong className="font-mono">
                        {result.suggestion.maxAllowed} {result.suggestion.unit}
                      </strong>
                    </>
                  )}
                </p>
              </div>
            )}

            {/* 未覆盖 → 显式提示 + 相关条文 */}
            {result.coverageGap && (
              <div className="border border-amber-300 dark:border-amber-700 rounded-lg p-4 bg-amber-50/50 dark:bg-amber-950/20">
                <h3 className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                  ⚠ 需要人工确认
                </h3>
                <p className="mt-1 text-sm text-amber-900/90 dark:text-amber-100/90">
                  {result.coverageGap.reason}
                </p>
                <p className="mt-2 text-xs text-amber-800/80 dark:text-amber-200/70">
                  ⚠ 本系统**不判定**未覆盖的情形 —— 请由合规人员核对下列相关条款后决定。
                </p>

                {result.coverageGap.relatedArticles.length > 0 && (
                  <ul className="mt-3 space-y-2">
                    {result.coverageGap.relatedArticles.map(a => (
                      <li
                        key={a.articleId}
                        className="text-sm border border-amber-200 dark:border-amber-800 rounded-md p-2 bg-white/60 dark:bg-slate-900/40"
                      >
                        <Link
                          to={`/article/${encodeURIComponent(a.articleId)}`}
                          className="text-sky-700 dark:text-sky-300 hover:underline font-medium"
                        >
                          {a.chapterTitle || a.articleNumber || a.articleId}
                        </Link>
                        <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-400 line-clamp-2">
                          {a.excerpt}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* 依据条款原文 */}
            {result.ruleHits.length > 0 && (
              <div className="border border-slate-200 dark:border-slate-800 rounded-lg p-4 bg-white dark:bg-slate-900">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  依据条款({result.ruleHits.length} 条)
                </h3>
                <ul className="mt-2 space-y-3">
                  {result.ruleHits.map(hit => (
                    <li
                      key={hit.ruleId}
                      className="border border-slate-200 dark:border-slate-700 rounded-md p-3"
                    >
                      <div className="flex items-center gap-3 flex-wrap text-xs">
                        <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">
                          {hit.limit.min !== null && hit.limit.min !== undefined
                            ? `${hit.limit.min}~`
                            : ""}
                          {hit.limit.max !== null && hit.limit.max !== undefined
                            ? `${hit.limit.max}`
                            : "—"}
                          {hit.limit.unit ? ` ${hit.limit.unit}` : ""}
                        </span>
                        <Link
                          to={`/article/${encodeURIComponent(hit.sourceArticleId)}`}
                          className="text-sky-700 dark:text-sky-300 hover:underline"
                        >
                          查看原文
                        </Link>
                      </div>
                      {hit.sourceExcerpt && (
                        <pre className="mt-2 text-xs text-slate-600 dark:text-slate-400 whitespace-pre-wrap break-words font-mono bg-slate-50 dark:bg-slate-950 rounded p-2">
                          {hit.sourceExcerpt}
                        </pre>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="text-xs text-slate-500 dark:text-slate-400 text-center">
              {result.notice} · 规则集版本 {result.ruleSetVersion}
            </p>
          </section>
        )}

        {isMockMode && (
          <p className="text-xs text-slate-500 dark:text-slate-400 text-center">
            Mock 模式 —— 未接入真实合规规则库
          </p>
        )}
      </main>
    </Layout>
  )
}
