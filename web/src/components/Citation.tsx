import { Link } from "react-router-dom"

/**
 * 引用块: 在搜索结果/章节里标注来源条款
 * 例: <Citation docId chapterId articleId chapterTitle="总则" articleNumber="第一条" />
 */
interface Props {
  docId: string
  chapterId: string
  articleId?: string
  chapterTitle?: string
  articleNumber?: string
  source: string  // 完整来源描述,如 "《饲料和饲料添加剂管理条例》第一章 第一条"
}

export function Citation({ docId, chapterId, articleId, chapterTitle, articleNumber, source }: Props) {
  const href = articleId
    ? `/doc/${docId}/chapter/${chapterId}#${articleId}`
    : `/doc/${docId}/chapter/${chapterId}`
  return (
    <Link
      to={href}
      className="inline-flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-50 text-primary rounded hover:bg-blue-100 transition"
    >
      <span>📌</span>
      <span>{source}</span>
      {chapterTitle && <span className="text-slate-500">·{chapterTitle}</span>}
      {articleNumber && <span className="text-slate-500">·{articleNumber}</span>}
    </Link>
  )
}