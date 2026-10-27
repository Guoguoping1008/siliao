import { useState } from "react"
import { Link } from "react-router-dom"
import type { Catalog, CatalogScope, CatalogSection } from "../lib/api"

/**
 * 目录树 —— 书籍原版的层级视图
 *
 * 与首页的「法规库」平铺列表是**两套视图**:
 *   - 法规库: 196 个文档平铺, 按 ingest 顺序, 适合「我知道要找哪部法规」
 *   - 目录树: 一级分类 → 子类 → 文件, 带文号和起始页, 适合「我想知道这本书怎么分的」
 *
 * 交互:
 *   - 一级分类默认展开, 二级子类默认收起(否则首屏太长)
 *   - 点文件标题跳到文档详情
 *   - 文号显示在右侧, 起始页用「p123」标注
 *   - 未匹配到实体文档的条目(目录里有但语料没收录)仍然显示, 但不可点击
 */

interface Props {
  catalog: Catalog
}

export function CatalogTree({ catalog }: Props) {
  const [openScopes, setOpenScopes] = useState<Set<string>>(
    () => new Set(catalog.scopes.map(s => s.title))
  )
  const [openSections, setOpenSections] = useState<Set<string>>(new Set())

  const toggle = (
    setter: React.Dispatch<React.SetStateAction<Set<string>>>,
    key: string
  ) => {
    setter(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const total = catalog.stats?.docs ?? 0
  const matched = catalog.stats?.matched ?? 0

  return (
    <div className="space-y-4">
      {catalog.scopes.map(scope => (
        <ScopeBlock
          key={scope.title}
          scope={scope}
          open={openScopes.has(scope.title)}
          onToggle={() => toggle(setOpenScopes, scope.title)}
          openSections={openSections}
          toggleSection={k => toggle(setOpenSections, k)}
        />
      ))}

      {catalog.scopes.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          暂无目录数据
        </p>
      )}

      {total > 0 && (
        <p className="text-xs text-slate-400 dark:text-slate-600 pt-1">
          目录共 {total} 项 · {matched} 项可跳转
          {catalog.stats && catalog.stats.unmatched > 0 && (
            <> · {catalog.stats.unmatched} 项语料未收录(不可点击)</>
          )}
        </p>
      )}
    </div>
  )
}

function ScopeBlock({
  scope,
  open,
  onToggle,
  openSections,
  toggleSection,
}: {
  scope: CatalogScope
  open: boolean
  onToggle: () => void
  openSections: Set<string>
  toggleSection: (key: string) => void
}) {
  const docCount = scope.sections.reduce((n, s) => n + s.docs.length, 0)

  return (
    <section className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden bg-white dark:bg-slate-900">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition"
      >
        <span
          aria-hidden="true"
          className="text-slate-400 text-xs w-3 shrink-0 transition-transform"
          style={{ transform: open ? "rotate(90deg)" : "none" }}
        >
          ▶
        </span>
        <span className="font-semibold text-slate-900 dark:text-slate-100 flex-1">
          {scope.title}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
          {scope.sections.length} 类 · {docCount} 项
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-200 dark:border-slate-700">
          {scope.sections.map(sec => (
            <SectionBlock
              key={sec.title ?? `__anon_${sec.docs[0]?.title ?? ""}`}
              section={sec}
              open={openSections.has(secKey(scope, sec))}
              onToggle={() => toggleSection(secKey(scope, sec))}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function secKey(scope: CatalogScope, sec: CatalogSection): string {
  return `${scope.title}::${sec.title ?? "__anon"}`
}

function SectionBlock({
  section,
  open,
  onToggle,
}: {
  section: CatalogSection
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="border-b border-slate-100 dark:border-slate-800 last:border-b-0">
      <button
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center gap-2.5 px-4 py-2.5 pl-8 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition"
      >
        <span
          aria-hidden="true"
          className="text-slate-400 text-[10px] w-3 shrink-0 transition-transform"
          style={{ transform: open ? "rotate(90deg)" : "none" }}
        >
          ▶
        </span>
        <span className="text-sm text-slate-700 dark:text-slate-300 flex-1">
          {section.title ?? "（本类无子类）"}
          {section.page != null && (
            <span className="ml-2 text-xs text-slate-400 dark:text-slate-600">
              p{section.page}
            </span>
          )}
        </span>
        <span className="text-xs text-slate-400 dark:text-slate-600 shrink-0">
          {section.docs.length}
        </span>
      </button>

      {open && (
        <ul className="pb-1.5">
          {section.docs.map(doc => (
            <li key={doc.doc_id ?? doc.title}>
              {doc.matched && doc.doc_id ? (
                <Link
                  to={`/doc/${doc.doc_id}`}
                  className="flex items-start gap-3 pl-12 pr-4 py-1.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800/50 group"
                >
                  <span className="flex-1 min-w-0">
                    <span className="text-slate-800 dark:text-slate-200 group-hover:text-primary dark:group-hover:text-primary-dark">
                      {doc.title}
                    </span>
                    {doc.doc_number && (
                      <span className="ml-2 text-xs text-slate-400 dark:text-slate-600">
                        {doc.doc_number}
                      </span>
                    )}
                  </span>
                  {doc.page != null && (
                    <span className="text-xs text-slate-400 dark:text-slate-600 shrink-0 tabular-nums">
                      p{doc.page}
                    </span>
                  )}
                </Link>
              ) : (
                <div
                  className="flex items-start gap-3 pl-12 pr-4 py-1.5 text-sm cursor-not-allowed"
                  title="语料未收录该文件"
                >
                  <span className="flex-1 min-w-0 text-slate-400 dark:text-slate-600">
                    {doc.title}
                    <span className="ml-2 text-xs">(未收录)</span>
                  </span>
                  {doc.page != null && (
                    <span className="text-xs text-slate-300 dark:text-slate-700 shrink-0 tabular-nums">
                      p{doc.page}
                    </span>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
