/**
 * 合规判定器 —— 领域服务
 *
 * 上下文: ② 合规规则 Compliance (核心域)
 *
 * ## 为什么是**领域服务**
 *
 * 「一个用量是否合规」是**业务判断**, 不是工具函数 —— 它的结论决定了一份
 * 配方能不能投产。它必须满足方案文档的「合规优先」原则:
 *
 *   1. 无规则命中 → **必须**返回 not_covered, **禁止**返回 compliant
 *   2. 每条判定都要带 source_article_id, 结论可溯源到条款原文
 *
 * ## 纯度保证 (ADR-004 R3/R5)
 *
 * 纯函数, 零 I/O, 零框架依赖。可完整单测。
 */

import type {
  ComplianceRule,
  ComplianceRuleSet,
  ComplianceVerdict,
  RelatedArticle,
  RuleHit,
  UsageDeclaration,
} from "./compliance-rule-set.aggregate";

/** 把内部规则转成对外的命中记录。 */
function toHit(r: ComplianceRule): RuleHit {
  return {
    ruleId: r.ruleId,
    sourceArticleId: r.sourceArticleId,
    sourceDocId: r.sourceDocId,
    sourceExcerpt: r.sourceExcerpt,
    limit: { min: r.minValue, max: r.maxValue, unit: r.unit },
  };
}

/**
 * 规则是否适用于本次用法。
 *
 * 匹配维度:
 *   - 物质: 精确相等(调用方已把用户输入解析成标准名)
 *   - 动物: 精确相等; 规则无动物限定则视为适用
 *   - 阶段: 规则有阶段且与请求阶段不同 → 不适用
 *     (规则无阶段 → 视为适用该动物的所有阶段)
 */
export function ruleMatches(r: ComplianceRule, usage: UsageDeclaration): boolean {
  if (r.ruleType !== "limit" && r.ruleType !== "prohibition") return false;
  if (r.substance !== usage.substance) return false;

  if (r.species && r.species !== usage.species) return false;

  if (r.stage && usage.stage && r.stage !== usage.stage) return false;

  return true;
}

/**
 * 单位是否可比。
 *
 * ⚠️ 单位不同**不能直接比大小** —— 200mg/kg 与 200IU/kg 毫无可比性。
 * 不匹配时按「未覆盖」处理(而不是判成合规)。
 */
export function unitComparable(ruleUnit: string | null, usageUnit: string): boolean {
  if (!ruleUnit) return false;
  return ruleUnit === usageUnit;
}

/**
 * 判定用量是否合规。
 *
 * @param usage        用户声明的用量
 * @param ruleSet      规则集(只用其中 **已审核** 的规则)
 * @param related      未覆盖时附带的检索证据(可为空)
 *
 * @returns 判定结果。**无规则命中时 status 必为 "not_covered"**。
 */
export function evaluateUsage(
  usage: UsageDeclaration,
  ruleSet: ComplianceRuleSet,
  related: RelatedArticle[] = []
): ComplianceVerdict {
  const reviewed = ruleSet.reviewed;

  // ── 1. 禁用规则优先 —— 禁用是硬红线, 无条件拒绝 ──
  const prohibition = reviewed.find(
    (r) => r.ruleType === "prohibition" && ruleMatches(r, usage)
  );
  if (prohibition) {
    return { status: "prohibited", ruleHits: [toHit(prohibition)] };
  }

  // ── 2. 限量规则(单位必须可比) ──
  const candidates = reviewed.filter(
    (r) => r.ruleType === "limit" && ruleMatches(r, usage)
  );
  const limits = candidates.filter((r) => unitComparable(r.unit, usage.unit));

  // ── 3. ⚠️ 不变量 1: 无命中 → 必须返回 not_covered, **禁止**返回 compliant ──
  //
  //    这里的分支**必须被单测锁死** —— 它极容易在后续重构中被"优化"成
  //    「没规则就认为合规」。见功能设计文档 §4.6。
  if (limits.length === 0) {
    return {
      status: "not_covered",
      ruleHits: [],
      coverageGap: {
        reason: candidates.length > 0
          ? "规则库有该物质的限量, 但单位与所填单位不一致, 需人工确认"
          : "规则库未覆盖该物质/动物组合, 需人工确认",
        relatedArticles: related,
      },
    };
  }

  // ── 4. 比对 —— 取所有命中规则中**最严**的一条 ──
  const strictest = limits.reduce((a, b) => {
    const av = a.maxValue ?? Number.POSITIVE_INFINITY;
    const bv = b.maxValue ?? Number.POSITIVE_INFINITY;
    return bv < av ? b : a;
  });

  const max = strictest.maxValue;
  const min = strictest.minValue;

  if (max !== null && max !== undefined && usage.value > max) {
    const over = usage.value - max;
    return {
      status: "exceeded",
      ruleHits: limits.map(toHit),
      suggestion: {
        maxAllowed: max,
        unit: strictest.unit ?? usage.unit,
        message: `超出上限 ${over} ${strictest.unit ?? usage.unit}`,
      },
    };
  }

  if (min !== null && min !== undefined && usage.value < min) {
    const under = min - usage.value;
    return {
      status: "exceeded",
      ruleHits: limits.map(toHit),
      suggestion: {
        maxAllowed: max ?? usage.value,
        unit: strictest.unit ?? usage.unit,
        message: `低于下限 ${under} ${strictest.unit ?? usage.unit}`,
      },
    };
  }

  // ── 5. 合规 ──
  return { status: "compliant", ruleHits: limits.map(toHit) };
}
