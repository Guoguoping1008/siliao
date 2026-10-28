/**
 * 领域事件 —— shared kernel
 *
 * 所有上下文的公共内核。ADR-004 第 7 节定义的事件契约。
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 *    事件派发由 infrastructure 层用 Workers `ctx.waitUntil()` 实现。
 */

/** 事件类型名。 */
export type DomainEventName =
  | "RegulationReleaseDetected"   // ⑤ → ① 新法规发布被探测到
  | "RegulationVersionIngested"   // ① → ② 新版本已入库, 需重算规则
  | "RulesRecalculated"           // ② → ⑤ 规则已重算, 需推送影响面
  | "EntityRelationsExtracted";   // ④ → ③ 实体关系已抽取, 可增强检索

/** 领域事件信封。 */
export interface DomainEvent<T = unknown> {
  name: DomainEventName;
  /** 事件发生时间(ISO 8601) */
  occurredAt: string;
  /** 事件负载 */
  payload: T;
}

/** ⑤ 监测 → ① 知识库 */
export interface RegulationReleaseDetectedPayload {
  /** 新版本文档 id */
  docId: string;
  /** 差异摘要 */
  diffSummary: string;
}

/** ① 知识库 → ② 合规规则 */
export interface RegulationVersionIngestedPayload {
  /** 需要重算规则的条文 id 列表 */
  articleIds: string[];
}

/** ② 合规规则 → ⑤ 监测 */
export interface RulesRecalculatedPayload {
  /** 受影响的物质/品类集合 */
  affectedSubstances: string[];
  affectedCategories: string[];
}

/** ④ 图谱 → ③ 问答 */
export interface EntityRelationsExtractedPayload {
  entityIds: string[];
}

/**
 * 构造领域事件。
 *
 * `occurredAt` 由调用方传入而非内部 `new Date()` —— 这样领域层保持纯函数,
 * 事件时间可被测试固定。
 */
export function createEvent<T>(
  name: DomainEventName,
  payload: T,
  occurredAt: string
): DomainEvent<T> {
  return { name, occurredAt, payload };
}
