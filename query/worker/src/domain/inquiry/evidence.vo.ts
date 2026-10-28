/**
 * 检索证据 (Evidence) —— 领域层值对象
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ⚠️ 领域层铁律 (ADR-004 R3/R5):
 *   - 纯 TS, 零框架依赖, 零 I/O
 *   - 不 import Workers / D1 类型
 *   - 不出现 fetch()
 */

/**
 * 一条检索命中。
 *
 * ⚠️ 字段类型允许 `null` —— D1 的 LEFT JOIN 会给缺失的 chapter 返回 null,
 *    且原实现是**直接透传原值**(空串保持空串、null 保持 null)。
 *    这里若改成 `String(x)` 就会把 null 变成字符串 "null", 是回归。
 */
export interface Evidence {
  article_id: string;
  chapter_id?: string | null;
  doc_id?: string | null;
  chapter_title?: string | null;
  chapter_number?: string | null;
  article_number?: string | null;
  title?: string | null;
  excerpt: string;
  relevance?: number;
}

/**
 * 引用 (Citation) —— 答案里 `[N]` 引用的校验结果。
 *
 * `valid: false` 表示 LLM 编造了不存在的引用(引用号超出证据范围),
 * 前端会把它标红。这是「合规优先」原则的技术落点。
 *
 * ⚠️ 元数据允许 null —— 与 Evidence 一致, **直接透传原值**,
 *    不做 String() 转换(null 变 "null" 是回归)。
 */
export interface Citation {
  ref: number;
  article_id?: string;
  chapter_id?: string | null;
  doc_id?: string | null;
  chapter_number?: string | null;
  chapter_title?: string | null;
  article_number?: string | null;
  title?: string | null;
  excerpt?: string;
  valid: boolean;
}
