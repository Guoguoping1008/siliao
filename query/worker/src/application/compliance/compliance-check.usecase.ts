/**
 * 合规校验 Use Case —— 应用层
 *
 * 上下文: ② 合规规则 Compliance
 *
 * 编排: 解析物质名 → 取规则集 → 领域服务判定 → 未覆盖时补检索证据
 *
 * ⚠️ 本层**不做业务判断** —— 判定逻辑全在 domain/compliance 里。
 * 这里只负责「取数据、喂给领域服务、把结果组装成响应」。
 */

import {
  evaluateUsage,
} from "../../domain/compliance/compliance-evaluator.service";
import { matchSubstance } from "../../domain/compliance/substance-matcher.service";
import {
  ComplianceRuleSet,
  type ComplianceVerdict,
  type RelatedArticle,
  type UsageDeclaration,
} from "../../domain/compliance/compliance-rule-set.aggregate";
import type { SubstanceCatalogEntry } from "../../domain/compliance/substance-catalog.vo";

/** 规则仓储端口(由 infrastructure 实现)。 */
export interface ComplianceRuleSource {
  listRules(ruleSetVersion?: string): Promise<ComplianceRuleSet>;
  listCatalog(reviewedOnly?: boolean): Promise<SubstanceCatalogEntry[]>;
}

/** 检索端口(未覆盖时补「可能相关的条款」)。 */
export interface RelatedArticleSource {
  search(params: { q: string }): Promise<{ hits: RelatedArticle[] }>;
}

/** 校验请求。 */
export interface ComplianceCheckRequest {
  substance: string;
  species: string;
  stage?: string | null;
  value: number;
  unit: string;
}

/** 校验响应。 */
export interface ComplianceCheckResponse {
  status: ComplianceVerdict["status"];
  /** 用户输入的物质名(原样回显)。 */
  substance: string;
  /** 匹配到的标准物质名(匹配不上则为 null)。 */
  matchedSubstance: string | null;
  /** 匹配方式。 */
  matchMethod: string | null;
  usage: { species: string; stage: string | null; value: number; unit: string };
  ruleHits: ComplianceVerdict["ruleHits"];
  suggestion: NonNullable<ComplianceVerdict["suggestion"]> | null;
  coverageGap: NonNullable<ComplianceVerdict["coverageGap"]> | null;
  /** 规则集版本 —— 结论可回溯。 */
  ruleSetVersion: string;
  /** 对外输出的免责标注。 */
  notice: string;
}

const NOTICE = "本结果为辅助意见，不构成监管结论";

/** 合规校验服务。 */
export class ComplianceCheckService {
  constructor(
    private readonly rules: ComplianceRuleSource,
    private readonly related: RelatedArticleSource
  ) {}

  /**
   * 校验一个用量是否合规。
   *
   * @returns 判定响应。**status 为 "not_covered" 时必定带 coverageGap。**
   */
  async check(req: ComplianceCheckRequest): Promise<ComplianceCheckResponse> {
    const usage: UsageDeclaration = {
      substance: req.substance,
      species: req.species,
      stage: req.stage ?? null,
      value: req.value,
      unit: req.unit,
    };

    // 1. 解析物质名(三级匹配, 不做模糊)
    const catalog = await this.rules.listCatalog(true);
    const match = matchSubstance(req.substance, catalog);
    const standardName = match?.entry.nameCn ?? null;

    // 2. 取规则集
    const ruleSet = await this.rules.listRules();

    // 3. 用标准名判定(没匹配上就用原名, 必然 not_covered)
    const effective: UsageDeclaration = {
      ...usage,
      substance: standardName ?? req.substance,
    };
    const verdict = evaluateUsage(effective, ruleSet);

    // 4. 未覆盖 → 补检索证据, 让用户能转人工
    let coverageGap = verdict.coverageGap ?? null;
    if (verdict.status === "not_covered") {
      const hits = await this.related.search({
        q: `${req.substance} ${req.species} 使用量 限量`,
      });
      coverageGap = {
        reason: coverageGap?.reason ?? "规则库未覆盖该物质/动物组合, 需人工确认",
        relatedArticles: hits.hits.slice(0, 5),
      };
    }

    return {
      status: verdict.status,
      substance: req.substance,
      matchedSubstance: standardName,
      matchMethod: match?.method ?? null,
      usage: {
        species: req.species,
        stage: req.stage ?? null,
        value: req.value,
        unit: req.unit,
      },
      ruleHits: verdict.ruleHits,
      suggestion: verdict.suggestion ?? null,
      coverageGap,
      ruleSetVersion: ruleSet.ruleSetVersion,
      notice: NOTICE,
    };
  }
}
