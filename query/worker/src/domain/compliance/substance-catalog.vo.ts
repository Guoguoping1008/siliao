/**
 * 物质目录 —— 领域层值对象
 *
 * 上下文: ② 合规规则 Compliance
 *
 * 《饲料添加剂品种目录》是「某物质是否在目录内」的**权威清单**。
 * 抽成结构化表后, 一次 SQL 精确匹配即可回答 —— 不需要知识图谱
 * (图谱解决多跳关系推理, 这是单跳集合查询)。
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

/** 审核状态。 */
export type CatalogReviewStatus = "pending" | "reviewed" | "rejected";

/** 物质目录条目。 */
export interface SubstanceCatalogEntry {
  substanceId: string;
  /** 通用名称(中文)。 */
  nameCn: string;
  /** 英文名称。 */
  nameEn: string | null;
  /** 额外别名(如「核黄素」→ 维生素B2)。 */
  substanceAlias: string | null;
  /** 化学式或描述。 */
  formula: string | null;
  /** 来源。 */
  source: string | null;
  /** 含量规格。 */
  spec: string | null;
  /** 类别: 添加剂 | 原料 | 载体 */
  category: string | null;
  /** 适用范围原文。 */
  scopeText: string | null;

  /** ── 溯源(不变量 2: 必填) ── */
  sourceArticleId: string;
  sourceDocId: string;

  ruleSetVersion: string;
  reviewStatus: CatalogReviewStatus;
}
