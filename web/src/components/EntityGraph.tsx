/**
 * 实体关系图(轻量 SVG)
 *
 * 设计: 中心实体 + 关联条文(环形布局) + 文号(外环)
 * 不依赖 d3/cytoscape,自己布局,纯 SVG,SSR 友好
 *
 * 节点类型:
 *   - center  (中心实体)
 *   - article (条文)
 *   - doc     (所属法规)
 *
 * 用法:
 *   <EntityGraph center="农业农村部" articles={[...]}/>
 */

import { Link } from "react-router-dom"

export interface GraphArticle {
  article_id: string
  chapter_id: string
  doc_id: string
  number: string        // "第一条"
  chapter_title?: string
}

interface Props {
  center: string
  centerType?: string   // 中心实体类型
  articles: GraphArticle[]
  width?: number
  height?: number
}

const TYPE_COLOR: Record<string, string> = {
  AGENCY: "#a855f7",
  PARTY: "#3b82f6",
  CERTIFICATE: "#f59e0b",
  DOCUMENT: "#10b981",
  LAW: "#ef4444",
  ENTITY: "#64748b",
}

/**
 * Ring layout: 中心 + 第1圈 articles + 第2圈 docs
 */
function ringLayout(count: number, radius: number, cx: number, cy: number) {
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * 2 * Math.PI - Math.PI / 2
    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      angle,
    }
  })
}

export function EntityGraph({ center, centerType = "ENTITY", articles, width = 600, height = 480 }: Props) {
  const cx = width / 2
  const cy = height / 2
  const r1 = Math.min(width, height) / 4
  const r2 = r1 * 1.7

  // 文号去重
  const docIds = Array.from(new Set(articles.map(a => a.doc_id)))

  const articlePos = ringLayout(articles.length, r1, cx, cy)
  const docPos = ringLayout(docIds.length, r2, cx, cy)

  const centerColor = TYPE_COLOR[centerType] || TYPE_COLOR.ENTITY

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto max-w-2xl mx-auto"
      role="img"
      aria-label={`${center} 的实体关系图`}
    >
      {/* 边: center -> articles */}
      {articlePos.map((p, i) => (
        <line
          key={`edge-a-${i}`}
          x1={cx} y1={cy} x2={p.x} y2={p.y}
          className="stroke-slate-300 dark:stroke-slate-600"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
      ))}

      {/* 边: articles -> docs */}
      {articles.map((a, i) => {
        const docIdx = docIds.indexOf(a.doc_id)
        if (docIdx < 0 || !articlePos[i] || !docPos[docIdx]) return null
        return (
          <line
            key={`edge-d-${i}`}
            x1={articlePos[i].x} y1={articlePos[i].y}
            x2={docPos[docIdx].x} y2={docPos[docIdx].y}
            className="stroke-slate-200 dark:stroke-slate-700"
            strokeWidth={1}
          />
        )
      })}

      {/* 中心实体 */}
      <g>
        <circle cx={cx} cy={cy} r={36} fill={centerColor} className="opacity-90" />
        <text
          x={cx} y={cy}
          textAnchor="middle"
          dominantBaseline="middle"
          fill="white"
          fontSize="14"
          fontWeight="bold"
        >
          {center.length > 6 ? center.slice(0, 6) + "…" : center}
        </text>
      </g>

      {/* 文号(外环) */}
      {docIds.map((d, i) => {
        const p = docPos[i]
        if (!p) return null
        return (
          <g key={`doc-${i}`}>
            <circle cx={p.x} cy={p.y} r={28} fill="#10b981" className="opacity-30 dark:opacity-40" />
            <circle cx={p.x} cy={p.y} r={28} fill="none" stroke="#10b981" strokeWidth={1.5} />
            <text x={p.x} y={p.y - 4} textAnchor="middle" fontSize="9" className="fill-slate-600 dark:fill-slate-400">DOC</text>
            <text x={p.x} y={p.y + 8} textAnchor="middle" fontSize="10" fontWeight="600" className="fill-slate-900 dark:fill-slate-100">
              {d.length > 8 ? d.slice(0, 8) + "…" : d}
            </text>
          </g>
        )
      })}

      {/* 条文(内环,可点击) */}
      {articles.map((a, i) => {
        const p = articlePos[i]
        if (!p) return null
        return (
          <Link
            key={`art-${i}`}
            to={`/doc/${a.doc_id}/chapter/${a.chapter_id}#${a.article_id}`}
          >
            <g style={{ cursor: "pointer" }}>
              <circle cx={p.x} cy={p.y} r={20} fill="#3b82f6" className="opacity-30 dark:opacity-40" />
              <circle cx={p.x} cy={p.y} r={20} fill="none" stroke="#3b82f6" strokeWidth={1.5} />
              <text
                x={p.x} y={p.y + 4}
                textAnchor="middle"
                fontSize="10"
                fontWeight="600"
                className="fill-slate-900 dark:fill-slate-100 pointer-events-none"
              >
                {a.number.replace(/第|条/g, "")}
              </text>
              <title>{`${a.chapter_title ?? ""} ${a.number}`}</title>
            </g>
          </Link>
        )
      })}
    </svg>
  )
}