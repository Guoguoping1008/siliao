/**
 * ② 合规规则 —— D1 仓储实现
 *
 * 上下文: ② 合规规则 Compliance (核心域)
 *
 * ⚠️ R1: 这是**唯一**允许直接查 `compliance_rules` / `substance_catalog` /
 *    `rule_sets` 的地方。其他上下文要读规则, 必须经这里。
 *
 * ⚠️ R4: 写入只允许经 `upsertRules` / `setReviewStatus`, 且都带
 *    `rule_set_version` —— 保证「结论可回溯到当时那版规则」。
 */

import type {
  ComplianceRule,
  ReviewStatus,
  RuleType,
} from "../../../domain/compliance/compliance-rule-set.aggregate";
import type { SubstanceCatalogEntry } from "../../../domain/compliance/substance-catalog.vo";
import type { D1Like } from "./regulation.repository.impl";
import { mapRows, str, type DbRow } from "./mappers";

/** 仓储接口。 */
export interface ComplianceRepository {
  /** 取某版本的规则集(全部状态, 领域层自己过滤 reviewed)。 */
  listRules(ruleSetVersion?: string): Promise<ComplianceRule[]>;
  /** 取已审核的规则。 */
  listReviewedRules(): Promise<ComplianceRule[]>;
  /** 取物质目录。 */
  listCatalog(reviewedOnly?: boolean): Promise<SubstanceCatalogEntry[]>;
  /** 取规则集版本列表。 */
  listRuleSets(): Promise<{ version: string; note: string | undefined; rulesCount: number }[]>;
}

/** D1 实现的合规规则仓储。 */
export class D1ComplianceRepository implements ComplianceRepository {
  constructor(private readonly db: D1Like) {}

  async listRules(ruleSetVersion?: string): Promise<ComplianceRule[]> {
    const sql = ruleSetVersion
      ? `SELECT * FROM compliance_rules WHERE rule_set_version = ?1`
      : `SELECT * FROM compliance_rules`;
    const rows = await this.db.prepare(sql)
      .bind(ruleSetVersion ?? "")
      .all();
    return mapRows(rows.results as DbRow[], toRule);
  }

  async listReviewedRules(): Promise<ComplianceRule[]> {
    const rows = await this.db.prepare(
      `SELECT * FROM compliance_rules WHERE review_status = 'reviewed'`
    ).all();
    return mapRows(rows.results as DbRow[], toRule);
  }

  async listCatalog(reviewedOnly = true): Promise<SubstanceCatalogEntry[]> {
    const sql = reviewedOnly
      ? `SELECT * FROM substance_catalog WHERE review_status = 'reviewed'`
      : `SELECT * FROM substance_catalog`;
    const rows = await this.db.prepare(sql).all();
    return mapRows(rows.results as DbRow[], toCatalogEntry);
  }

  async listRuleSets() {
    const rows = await this.db.prepare(
      `SELECT version, note, rules_count FROM rule_sets ORDER BY version DESC`
    ).all();
    return mapRows(rows.results as DbRow[], (r) => ({
      version: String(r.version),
      note: str(r.note),
      rulesCount: Number(r.rules_count ?? 0),
    }));
  }
}

/** D1 行 → 领域规则。 */
function toRule(r: DbRow): ComplianceRule {
  return {
    ruleId: String(r.rule_id),
    ruleType: String(r.rule_type) as RuleType,
    substance: str(r.substance) ?? null,
    substanceAlias: str(r.substance_alias) ?? null,
    species: str(r.species) ?? null,
    stage: str(r.stage) ?? null,
    minValue: r.min_value === null || r.min_value === undefined ? null : Number(r.min_value),
    maxValue: r.max_value === null || r.max_value === undefined ? null : Number(r.max_value),
    unit: str(r.unit) ?? null,
    conditionText: str(r.condition_text) ?? null,
    sourceArticleId: String(r.source_article_id),
    sourceDocId: String(r.source_doc_id),
    sourceExcerpt: str(r.source_excerpt) ?? null,
    ruleSetVersion: String(r.rule_set_version),
    extractionMethod: (str(r.extraction_method) ?? "auto") as "auto" | "manual",
    reviewStatus: (str(r.review_status) ?? "pending") as ReviewStatus,
  };
}

/** D1 行 → 物质目录条目。 */
function toCatalogEntry(r: DbRow): SubstanceCatalogEntry {
  return {
    substanceId: String(r.substance_id),
    nameCn: String(r.name_cn),
    nameEn: str(r.name_en) ?? null,
    substanceAlias: str(r.substance_alias) ?? null,
    formula: str(r.formula) ?? null,
    source: str(r.source) ?? null,
    spec: str(r.spec) ?? null,
    category: str(r.category) ?? null,
    scopeText: str(r.scope_text) ?? null,
    sourceArticleId: String(r.source_article_id),
    sourceDocId: String(r.source_doc_id),
    ruleSetVersion: String(r.rule_set_version),
    reviewStatus: (str(r.review_status) ?? "pending") as SubstanceCatalogEntry["reviewStatus"],
  };
}
