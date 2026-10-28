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

/** 一条检索命中。字段与 Worker 现有 SearchHit 保持一致, 保证行为不变。 */
export interface Evidence {
  article_id: string;
  chapter_id?: string;
  doc_id?: string;
  chapter_title?: string;
  chapter_number?: string;
  article_number?: string;
  title?: string;
  excerpt: string;
  relevance?: number;
}

/**
 * 引用 (Citation) —— 答案里 `[N]` 引用的校验结果。
 *
 * `valid: false` 表示 LLM 编造了不存在的引用(引用号超出证据范围),
 * 前端会把它标红。这是「合规优先」原则的技术落点。
 */
export interface Citation {
  ref: number;
  article_id?: string;
  chapter_id?: string;
  doc_id?: string;
  chapter_number?: string;
  chapter_title?: string;
  article_number?: string;
  title?: string;
  excerpt?: string;
  valid: boolean;
}
