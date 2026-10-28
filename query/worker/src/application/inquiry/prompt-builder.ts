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
 */
export function buildRagPrompt(
  q: string,
  hits: { chapter_number?: string; chapter_title?: string; article_number?: string; excerpt: string }[]
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
