/**
 * 简化 Markdown 渲染器: 不依赖 react-markdown(避免打包膨胀)
 *
 * 支持: # / ## / ### / 段落 / - 列表 / (一)(二) 列表
 * 输出: 每条文有独立 id,与切分器产物中的 article_id 对齐
 *
 * 锚点解析策略:
 * - chapter 文件首行可能是 `<!-- ... article_id: art00X -->`(chapter_splitter 产物),
 *   或 `> doc_id: ... chapter_id: ...`(同样合法,但不含 article_id)
 * - 解析时维护 currentArticleId,遇到 article_id 注释就更新
 * - 遇到"第X条"段落,优先用 currentArticleId;否则 fallback 到序号生成
 * - 这避免了 mockData 用 art001 全局编号、MarkdownView 用 ch01_art001 的错位
 */

interface Props {
  source: string
  chapterId: string
}

interface Block {
  type: "h1" | "h2" | "h3" | "p" | "li"
  text: string
  id?: string
}

const ARTICLE_ID_RE = /article_id:\s*(art\d+)/
const LIST_RE = /^[(\uFF08][\u4E00\u4E8C\u4E09\u56DB\u4E94\u516D\u4E03\u516B\u4E5D\u5341]+[)\uFF09]\s*/

function parse(md: string, chapterId: string): Block[] {
  const blocks: Block[] = []
  const lines = md.split("\n")
  let i = 0
  let currentArticleId: string | null = null

  while (i < lines.length) {
    const raw = lines[i]
    const line = raw.trim()
    i++

    if (!line) continue

    if (line.startsWith("<!--")) {
      const m = line.match(ARTICLE_ID_RE)
      if (m) currentArticleId = m[1]
      continue
    }

    if (line.startsWith("# ")) {
      blocks.push({ type: "h1", text: line.slice(2) })
      continue
    }
    if (line.startsWith("## ")) {
      blocks.push({ type: "h2", text: line.slice(3) })
      continue
    }
    if (line.startsWith("### ")) {
      blocks.push({ type: "h3", text: line.slice(4) })
      continue
    }

    if (line.startsWith("- ") || LIST_RE.test(line)) {
      blocks.push({ type: "li", text: line.replace(/^-\s*/, "").replace(LIST_RE, "· ") })
      continue
    }

    const buf = [line]
    while (i < lines.length) {
      const next = lines[i].trim()
      if (!next || next.startsWith("#") || next.startsWith("-") ||
          LIST_RE.test(next) ||
          next.startsWith("<!--")) break
      buf.push(next)
      i++
    }
    const text = buf.join(" ").replace(/\s+/g, " ").trim()

    const isArticle = /^第[一二三四五六七八九十百千零〇0-9]+条/.test(text)
    if (isArticle) {
      // 优先用切分器产物里的 article_id(注释里读到的)
      // fallback: 按"第X条"在文档中出现顺序,生成全局 art00X
      //   这样 mockData / D1 schema / 搜索结果链接 三方对齐
      const id = currentArticleId
        ?? `art${String(blocks.filter(b => /^art\d+$/.test(b.id ?? "")).length + 1).padStart(3, "0")}`
      blocks.push({ type: "p", text, id })
    } else {
      blocks.push({ type: "p", text })
    }
  }
  return blocks
}

export function MarkdownView({ source, chapterId }: Props) {
  const blocks = parse(source, chapterId)

  return (
    <article className="prose prose-slate dark:prose-invert max-w-none">
      {blocks.map((b, i) => {
        const key = `${b.type}-${i}`
        const cn = "leading-relaxed"
        if (b.type === "h1") return <h1 key={key} id={b.id} className="text-2xl font-bold mt-6 mb-3 text-slate-900 dark:text-slate-100">{b.text}</h1>
        if (b.type === "h2") return <h2 key={key} id={b.id} className="text-xl font-semibold mt-5 mb-2 text-slate-900 dark:text-slate-100">{b.text}</h2>
        if (b.type === "h3") return <h3 key={key} id={b.id} className="text-lg font-semibold mt-4 mb-2 text-slate-900 dark:text-slate-100">{b.text}</h3>
        if (b.type === "li") return <li key={key} className={`${cn} ml-6 list-disc text-slate-700 dark:text-slate-300`}>{b.text}</li>
        return <p key={key} id={b.id} className={`${cn} mb-3 text-slate-700 dark:text-slate-300 ${b.id ? "scroll-mt-32" : ""}`}>{b.text}</p>
      })}
    </article>
  )
}