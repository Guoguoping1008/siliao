/**
 * RAG Prompt 组装 —— 应用层
 *
 * 上下文: ③ 问答 Inquiry
 *
 * 这是**应用层**的编排逻辑, 不是领域逻辑 —— 它关心「怎么把证据塞给 LLM」,
 * 而不关心「什么算合法引用」。引用校验在 domain/inquiry/citation-validator。
 *
 * ⚠️ 本文件从 index.ts 原样迁移, 行为不变。
 */

/**
 * 拼 RAG prompt: system + evidence + user question
 *
 * 设计原则:
 * - system 强制「未找到则明说」, 避免 LLM 编造
 * - evidence 限 8 条, 过长会稀释 LLM 注意
 *
 * ⚠️ 元数据允许 null —— D1 LEFT JOIN 缺失时就是 null,
 *    这里原样插值(null 会变成字符串 "null" 出现在 prompt 里,
 *    与重构前行为一致, 故不改)。
 */
export function buildRagPrompt(
  q: string,
  hits: {
    chapter_number?: string | null;
    chapter_title?: string | null;
    article_number?: string | null;
    excerpt: string;
  }[]
): { systemPrompt: string; userPrompt: string } {
  const context = hits
    .slice(0, 8)
    .map((h, i) => `[${i + 1}] ${h.chapter_number} ${h.chapter_title} · ${h.article_number}: ${h.excerpt}`)
    .join("\n\n");

  const systemPrompt = `你是"中国农业饲料法规知识库"的检索助手,严格基于下方"检索证据"用中文回答用户问题。

# 行为准则
1. **必须只基于检索证据**回答,不要引用未在证据中出现的条文、法律或事实。
2. 若证据不足以回答,直接回复:"未找到相关规定",不要编造或猜测。
3. 引用条款时使用证据前方的编号格式 \`[N]\`,不要写"第一条"这种裸引用。
4. 答案简洁,优先列条文要点;不要堆砌废话。

# 输出格式(可选)
- 直接答案(1-3 句话)
- 涉及到的引用编号列表(\`[1] [3]\`)
- 如果多条证据相关,按编号顺序引用`;

  const userPrompt = `# 检索证据
${context || "(无相关证据)"}

# 用户问题
${q}

# 答案`;

  return { systemPrompt, userPrompt };
}

/**
 * 拼**多轮** RAG prompt: system + 历史 + evidence + user question
 *
 * ## 为什么历史要进 prompt
 *
 * 用户问「维生素C在猪饲料中的上限?」再问「那鸡呢?」——
 * 第二句脱离上下文就没有主语。LLM 必须看到历史问句才知道「那」指什么。
 *
 * ⚠️ **历史只给问题与答案摘要, 不给历史的 evidence** ——
 *    历史 evidence 已经不在当前检索结果里, 给了会诱导 LLM 引用旧编号
 *    (当前 prompt 里编号是重新分配的, 引用旧编号 = 引用错条文)。
 *
 * ⚠️ **编号纪律**: prompt 里明确要求「只引用本轮证据的编号」,
 *    这是多轮场景下最容易出错的地方。
 */
export function buildConversationPrompt(
  q: string,
  hits: {
    chapter_number?: string | null;
    chapter_title?: string | null;
    article_number?: string | null;
    excerpt: string;
  }[],
  history: { question: string; answer: string }[]
): { systemPrompt: string; userPrompt: string } {
  const context = hits
    .slice(0, 8)
    .map((h, i) => `[${i + 1}] ${h.chapter_number} ${h.chapter_title} · ${h.article_number}: ${h.excerpt}`)
    .join("\n\n");

  const systemPrompt = `你是"中国农业饲料法规知识库"的检索助手,严格基于下方"检索证据"用中文回答用户问题。

# 行为准则
1. **必须只基于检索证据**回答,不要引用未在证据中出现的条文、法律或事实。
2. 若证据不足以回答,直接回复:"未找到相关规定",不要编造或猜测。
3. 引用条款时使用证据前方的编号格式 \`[N]\`,不要写"第一条"这种裸引用。
4. 答案简洁,优先列条文要点;不要堆砌废话。
5. **多轮追问时**:当前问题可能是省略了主语的追问(如"那鸡呢?"),
   要结合对话历史理解它在问什么;但**引用编号只能用本轮证据里的编号**。

# 输出格式(可选)
- 直接答案(1-3 句话)
- 涉及到的引用编号列表(\`[1] [3]\`)
- 如果多条证据相关,按编号顺序引用`;

  const historyBlock = history.length
    ? history
        .map((t, i) => `## 第 ${i + 1} 轮\n问: ${t.question}\n答: ${summarize(t.answer)}`)
        .join("\n\n")
    : "(无历史对话)";

  const userPrompt = `# 对话历史
${historyBlock}

# 本轮检索证据
${context || "(无相关证据)"}

# 当前问题
${q}

# 答案`;

  return { systemPrompt, userPrompt };
}

/**
 * 把历史答案压成摘要 —— 只保留前若干字。
 *
 * ⚠️ 历史答案可能有几百字, 全塞进 prompt 会挤占上下文,
 *    而且用户真正需要 LLM 记住的是「上一轮问了什么」, 不是上一轮答了什么。
 */
function summarize(answer: string, maxLen = 300): string {
  const a = (answer || "").replace(/\s+/g, " ").trim();
  if (a.length <= maxLen) return a;
  return a.slice(0, maxLen) + "…";
}
