import { Link } from "react-router-dom"

interface Props {
  docId: string
  chapterId: string
  articleId?: string
  chapterTitle?: string
  articleNumber?: string
  source: string
}

export function Citation({ docId, chapterId, articleId, chapterTitle, articleNumber, source }: Props) {
  const href = articleId
    ? `/doc/${docId}/chapter/${chapterId}#${articleId}`
    : `/doc/${docId}/chapter/${chapterId}`
  return (
    <Link
      to={href}
      className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-50 dark:bg-blue-900/30 text-primary dark:text-primary-dark rounded hover:bg-blue-100 dark:hover:bg-blue-900/50 transition"
    >
      <span>📌</span>
      <span>{source}</span>
      {chapterTitle && <span className="text-slate-500 dark:text-slate-400">·{chapterTitle}</span>}
      {articleNumber && <span className="text-slate-500 dark:text-slate-400">·{articleNumber}</span>}
    </Link>
  )
}