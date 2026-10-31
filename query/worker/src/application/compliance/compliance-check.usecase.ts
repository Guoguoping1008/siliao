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
  type ComplianceRule,
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

/** 英文名归一 —— 剥掉末尾缩写, 小写。 */
function enKey(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/\s*\([A-Za-z]{1,6}\)\s*$/, "").trim().toLowerCase();
}

/**
 * 把「目录里的标准名」对齐到「规则库里用的名字」。
 *
 * ## 为什么需要这一步
 *
 * 目录与《安全使用规范》对同一物质的中文写法可能略有出入:
 *   目录      「二甲基嘧啶醇亚硫酸甲萘醌」
 *   规则库    「二甲基嘧啶醇亚硫酸氢钠甲萘醌」
 *
 * 而 `ruleMatches` 是**精确比较** `r.substance === usage.substance`。
 * 若直接把目录名喂进去, 规则永远匹配不上 → 明明库里有规则却判 not_covered。
 *
 * ## 对齐依据: **英文名**(唯一键)
 *
 * 两边都填了 `name_en` / `substance_alias`, 英文名是同一个物质的可靠标识。
 * 只有英文名能对上、且**候选唯一**时才采用 —— 不猜。
 *
 * ⚠️ 若对不上, 保留目录名 → 判定走 not_covered(安全侧)。
 */
function alignSubstanceName(
  catalogName: string,
  match: { entry: SubstanceCatalogEntry } | null,
  rules: ComplianceRule[]
): string {
  if (!match) return catalogName;
  const target = enKey(match.entry.nameEn);
  if (!target) return catalogName;

  // 规则里有完全同名的 → 直接用
  if (rules.some((r) => r.substance === catalogName)) return catalogName;

  // 否则找「英文名相同」且**候选唯一**的规则物质名
  const alias = enKey(match.entry.substanceAlias);
  const candidates = new Set<string>();
  for (const r of rules) {
    const rAlias = enKey(r.substanceAlias);
    if (!rAlias) continue;
    if (rAlias === target || (alias && rAlias === alias)) {
      if (r.substance) candidates.add(r.substance);
    }
  }
  if (candidates.size === 1) {
    return [...candidates][0];
  }
  return catalogName;
}

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
    //    ⚠️ 标准名要先与规则库对齐 —— 目录与安全使用规范的中文写法可能不同,
    //       而 ruleMatches 是精确比较, 不对齐就永远匹配不上。
    const effective: UsageDeclaration = {
      ...usage,
      substance:
        standardName !== null
          ? alignSubstanceName(standardName, match, [...ruleSet.all])
          : req.substance,
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
