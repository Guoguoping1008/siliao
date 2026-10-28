/**
 * 合规规则 —— 领域层聚合根与值对象
 *
 * 上下文: ② 合规规则 Compliance (核心域, 只读)
 *
 * ## 聚合边界
 *
 * `ComplianceRuleSet` 是聚合根, 内部是 `LimitRule` / `ProhibitionRule` /
 * `ConditionRule` / `CombinationRule` 四种规则类型。
 *
 * ## 不变量(两条, 不可协商)
 *
 * **不变量 1 · 规则未覆盖必须返回 not_covered, 绝不能返回 compliant**
 *   依据:「合规优先」+ 风险表「规则覆盖不全造成漏检」
 *
 * **不变量 2 · 每条规则必须绑定 source_article_id**
 *   依据:「涉及监管结论的输出必须可溯源(条款号+原文)」
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

/** 规则类型。 */
export type RuleType =
  | "limit"          // 限量规则 —— 物质×动物×上限
  | "prohibition"    // 禁用规则 —— 硬红线, 无条件拒绝
  | "condition"      // 使用条件规则 —— 附带约束
  | "combination";   // 组合约束 —— 针对**组合**而非单体(格式 5)

/** 审核状态 —— 未审核的规则**不参与判定**。 */
export type ReviewStatus = "pending" | "reviewed" | "rejected";

/** 抽取方式。 */
export type ExtractionMethod = "auto" | "manual";

/** 领域服务返回的判定状态。 */
export type VerdictStatus =
  | "compliant"      // 合规
  | "exceeded"       // 超限(或低于下限)
  | "prohibited"     // 禁用
  | "not_covered";   // ⚠️ 规则未覆盖 —— 必须显式出现

/** 合规规则(值对象)。 */
export interface ComplianceRule {
  ruleId: string;
  ruleType: RuleType;

  /** 物质通用名(中文)。组合规则时为 null。 */
  substance: string | null;
  /** 英文名/化学名, 用于别名匹配。 */
  substanceAlias: string | null;

  /** 动物种类。 */
  species: string | null;
  /** 阶段(鱼苗/育肥猪…)。 */
  stage: string | null;

  /** 下限。 */
  minValue: number | null;
  /** 上限。 */
  maxValue: number | null;
  /** 单位: mg/kg | g/kg | IU/kg | % */
  unit: string | null;

  /** 原文条件描述。 */
  conditionText: string | null;

  /** ── 溯源(不变量 2: 必填) ── */
  sourceArticleId: string;
  sourceDocId: string;
  /** 原文摘录 —— 前端直接展示, 用户可自行核对。 */
  sourceExcerpt: string | null;

  /** 规则集版本 —— 结论可回溯到「当时用的是哪版规则」。 */
  ruleSetVersion: string;

  extractionMethod: ExtractionMethod;
  reviewStatus: ReviewStatus;
}

/**
 * 规则集(聚合根)。
 *
 * 只读核心域 —— 规则的写入由抽取脚本 + 人工审核流程完成,
 * 业务判定只读。
 */
export class ComplianceRuleSet {
  constructor(
    private readonly version: string,
    private readonly rules: ComplianceRule[]
  ) {}

  get ruleSetVersion(): string {
    return this.version;
  }

  /** 全部规则(含未审核)。 */
  get all(): readonly ComplianceRule[] {
    return this.rules;
  }

  /**
   * **已审核**的规则 —— 判定时只用这些。
   *
   * ⚠️ 未审核的规则**不参与判定** —— 这是防止「自动抽取抽错了直接给用户
   * 错误结论」的关键闸门。见功能设计文档 §4.9。
   */
  get reviewed(): ComplianceRule[] {
    return this.rules.filter((r) => r.reviewStatus === "reviewed");
  }

  /** 按物质名查已审核规则。 */
  findBySubstance(substance: string): ComplianceRule[] {
    return this.reviewed.filter((r) => r.substance === substance);
  }

  /** 按 id 查。 */
  findById(ruleId: string): ComplianceRule | undefined {
    return this.rules.find((r) => r.ruleId === ruleId);
  }
}

/** 用法声明(值对象) —— 用户输入。 */
export interface UsageDeclaration {
  /** 物质名(用户输入, 可能是简称「维生素C」)。 */
  substance: string;
  /** 动物种类。 */
  species: string;
  /** 阶段(可选)。 */
  stage?: string | null;
  /** 用量数值。 */
  value: number;
  /** 单位: mg/kg | g/kg | IU/kg | % */
  unit: string;
}

/** 命中的规则 + 溯源信息。 */
export interface RuleHit {
  ruleId: string;
  sourceArticleId: string;
  sourceDocId: string;
  sourceExcerpt: string | null;
  limit: {
    min: number | null;
    max: number | null;
    unit: string | null;
  };
}

/** 检索到的相关条文(未覆盖时给用户人工参考)。 */
export interface RelatedArticle {
  articleId: string;
  chapterTitle?: string;
  articleNumber?: string;
  excerpt: string;
}

/** 合规判定结果。 */
export interface ComplianceVerdict {
  status: VerdictStatus;
  /** 命中的规则(带原文出处)。 */
  ruleHits: RuleHit[];
  /** 超限时的调整建议。 */
  suggestion?: {
    maxAllowed: number;
    unit: string;
    message: string;
  };
  /** 未覆盖时的覆盖缺口说明。 */
  coverageGap?: {
    reason: string;
    relatedArticles: RelatedArticle[];
  };
}
