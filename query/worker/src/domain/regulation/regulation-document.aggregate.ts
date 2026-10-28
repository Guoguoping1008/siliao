/**
 * 法规文档聚合 —— 领域层聚合根
 *
 * 上下文: ① 法规知识库 Regulation (核心域, 只读)
 *
 * ## 聚合边界
 *
 * `RegulationDocument` 是聚合根, 内部是 Document → Chapter → Article
 * 的严格层级。边界内的一致性规则:
 *   - 一个 Article 必属一个 Chapter
 *   - 一个 Chapter 必属一个 Document
 *
 * ## 只读约束
 *
 * 这个聚合**只读**。法规正文是事实, 不是可编辑对象。
 * 写入只能由 ⑤ 法规监测 的领域事件 `RegulationReleaseDetected` 触发,
 * 由 infrastructure 层的仓储执行 `ingestRelease()`。
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

/** 法规文档(条例/办法/公告/标准)。 */
export interface RegulationDocument {
  doc_id: string;
  title: string;
  doc_number?: string | null;
  issuer?: string | null;
  issue_date?: string | null;
  effective_date?: string | null;
  /** true = 目录页/封面, 不是法规正文, 不进 FTS 索引 */
  is_toc?: number;
  sort_order?: number;
}

/** 章/节。条文归属的载体。 */
export interface RegulationChapter {
  chapter_id: string;
  doc_id: string;
  /** 「第一章」 */
  number: string;
  title: string;
  article_count?: number;
  sort_order: number;
}

/** 条文 —— 最小引用单元。 */
export interface RegulationArticle {
  article_id: string;
  chapter_id: string;
  doc_id: string;
  /** 「第一条」 */
  number: string;
  title?: string | null;
  /** 正文 markdown */
  body?: string | null;
  /** 本章内的条文顺序。⚠️ 不能靠 article_id 排序 —— 它按字典序排, 会打乱原文顺序。 */
  sort_order: number;
}

/** 文档列表条目(带聚合统计)。 */
export interface RegulationDocumentSummary extends RegulationDocument {
  chapter_count: number;
  article_count: number;
}

/**
 * 校验聚合内部一致性。
 *
 * 领域不变量: 条文必须能通过 chapter_id 找到它的章, 章必须能通过
 * doc_id 找到它的文档。数据导入出错时这里能第一时间发现,
 * 而不是等到前端 404。
 *
 * @returns 违规描述列表, 空数组表示一致
 */
export function validateAggregation(
  document: RegulationDocument,
  chapters: RegulationChapter[],
  articles: RegulationArticle[]
): string[] {
  const errors: string[] = [];
  const chapterIds = new Set(chapters.map((c) => c.chapter_id));

  for (const c of chapters) {
    if (c.doc_id !== document.doc_id) {
      errors.push(`章节 ${c.chapter_id} 的 doc_id=${c.doc_id} 与聚合根 ${document.doc_id} 不一致`);
    }
  }
  for (const a of articles) {
    if (!chapterIds.has(a.chapter_id)) {
      errors.push(`条文 ${a.article_id} 的 chapter_id=${a.chapter_id} 在聚合内不存在`);
    }
    if (a.doc_id !== document.doc_id) {
      errors.push(`条文 ${a.article_id} 的 doc_id=${a.doc_id} 与聚合根 ${document.doc_id} 不一致`);
    }
  }
  return errors;
}

/**
 * 按原文顺序排序条文。
 *
 * ⚠️ 必须用 `sort_order`, 不能用 `article_id` 字典序 ——
 * 实测 95/529 个章节的条文顺序与原文不一致。
 */
export function sortArticlesByOrder(articles: RegulationArticle[]): RegulationArticle[] {
  return [...articles].sort((a, b) => a.sort_order - b.sort_order);
}
