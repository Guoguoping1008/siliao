/**
 * 简化 Markdown 渲染器: 不依赖 react-markdown(避免打包膨胀)
 *
 * 支持: # / ## / ### / 段落 / - 列表 / (一)(二) 列表
 * 输出: 每条文有独立 id (e.g. "ch01_art001"),URL 锚点跳转
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

function parse(md: string, chapterId: string): Block[] {
  const blocks: Block[] = []
  const lines = md.split("\n")
  let i = 0

  while (i < lines.length) {
    const line = lines[i].trim()
    i++

    if (!line) continue
    if (line.startsWith("<!--")) continue

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

    if (line.startsWith("- ") || /^[\(（][一二三四五六七八九十]+[\)）]\s*/.test(line)) {
      blocks.push({ type: "li", text: line.replace(/^-\s*/, "").replace(/^[\(（][一二三四五六七八九十]+[\)）]\s*/, "· ") })
      continue
    }

    const buf = [line]
    while (i < lines.length) {
      const next = lines[i].trim()
      if (!next || next.startsWith("#") || next.startsWith("-") ||
          /^[\(（][一二三四五六七八九十]+[\)）]/.test(next) ||
          next.startsWith("<!--")) break
      buf.push(next)
      i++
    }
    const text = buf.join(" ").replace(/\s+/g, " ").trim()

    const m = text.match(/^(第[一二三四五六七八九十百千零〇0-9]+条)/)
    if (m) {
      const existingArts = blocks.filter(b => b.id?.startsWith(`${chapterId}_art`)).length
      blocks.push({
        type: "p",
        text,
        id: `${chapterId}_art${String(existingArts + 1).padStart(3, "0")}`,
      })
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