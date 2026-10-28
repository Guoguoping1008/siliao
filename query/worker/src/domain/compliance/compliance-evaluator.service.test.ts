/**
 * ② 合规规则 —— 领域服务单测
 *
 * 重点测**业务规则**, 不是实现细节:
 *   1. 无规则命中 → 必须 not_covered(**绝不** compliant)
 *   2. 禁用规则优先于限量
 *   3. 单位不可比时按未覆盖处理
 *   4. 取最严规则
 *   5. 未审核规则不参与判定
 *
 * ⚠️ 第 1 条的测试用**故意构造的未覆盖物质** —— 这个分支极容易在
 * 后续重构中被"优化"掉。见功能设计文档 §4.6。
 */

import { describe, it, expect } from "vitest";
import {
  evaluateUsage,
  ruleMatches,
  unitComparable,
} from "./compliance-evaluator.service";
import {
  ComplianceRuleSet,
  type ComplianceRule,
  type UsageDeclaration,
} from "./compliance-rule-set.aggregate";

// ─────────────── 测试夹具 ───────────────

function rule(over: Partial<ComplianceRule> = {}): ComplianceRule {
  return {
    ruleId: "r_test_1",
    ruleType: "limit",
    substance: "L-抗坏血酸(维生素C)",
    substanceAlias: null,
    species: "猪",
    stage: null,
    minValue: 150,
    maxValue: 300,
    unit: "mg/kg",
    conditionText: null,
    sourceArticleId: "02制度文件_04_（四）使用管理_46_饲料添加剂安全使用规范__p001_s02",
    sourceDocId: "02制度文件_04_（四）使用管理_46_饲料添加剂安全使用规范",
    sourceExcerpt: "适用动物 猪150～300mg/kg",
    ruleSetVersion: "v2026.10",
    extractionMethod: "auto",
    reviewStatus: "reviewed",
    ...over,
  };
}

function usage(over: Partial<UsageDeclaration> = {}): UsageDeclaration {
  return {
    substance: "L-抗坏血酸(维生素C)",
    species: "猪",
    stage: null,
    value: 200,
    unit: "mg/kg",
    ...over,
  };
}

const VC_PIG = rule();

// ─────────────── 判定 ───────────────

describe("evaluateUsage · 不变量 1 · 未覆盖必须显式", () => {
  it("规则库为空 → not_covered(绝不 compliant)", () => {
    const set = new ComplianceRuleSet("v1", []);
    const v = evaluateUsage(usage(), set);
    expect(v.status).toBe("not_covered");
    expect(v.status).not.toBe("compliant");
    expect(v.ruleHits).toEqual([]);
    expect(v.coverageGap).toBeDefined();
  });

  it("物质不在规则库 → not_covered", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    // ⚠️ 故意构造一个库里没有的物质
    const v = evaluateUsage(usage({ substance: "某种完全未收录的物质XYZ" }), set);
    expect(v.status).toBe("not_covered");
    expect(v.coverageGap?.reason).toContain("未覆盖");
  });

  it("物质匹配但动物不匹配 → not_covered", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    const v = evaluateUsage(usage({ species: "貂" }), set);
    expect(v.status).toBe("not_covered");
  });

  it("单位不可比(IU/kg vs mg/kg) → not_covered 而非 compliant", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    const v = evaluateUsage(usage({ unit: "IU/kg" }), set);
    expect(v.status).toBe("not_covered");
    expect(v.coverageGap?.reason).toContain("单位");
  });

  it("未覆盖时附带检索证据", () => {
    const set = new ComplianceRuleSet("v1", []);
    const v = evaluateUsage(usage(), set, [
      { articleId: "a1", excerpt: "相关条款原文" },
    ]);
    expect(v.coverageGap?.relatedArticles).toHaveLength(1);
    expect(v.coverageGap?.relatedArticles[0].excerpt).toBe("相关条款原文");
  });

  it("未覆盖时不给 suggestion(不误导用户)", () => {
    const set = new ComplianceRuleSet("v1", []);
    const v = evaluateUsage(usage(), set);
    expect(v.suggestion).toBeUndefined();
  });
});

describe("evaluateUsage · 禁用规则优先", () => {
  it("禁用规则命中 → prohibited", () => {
    const set = new ComplianceRuleSet("v1", [
      VC_PIG,
      rule({
        ruleId: "r_prohibit_1",
        ruleType: "prohibition",
        minValue: null,
        maxValue: null,
        unit: null,
      }),
    ]);
    const v = evaluateUsage(usage(), set);
    expect(v.status).toBe("prohibited");
    expect(v.ruleHits).toHaveLength(1);
  });

  it("禁用优先于超限(禁用是硬红线)", () => {
    const set = new ComplianceRuleSet("v1", [
      VC_PIG,
      rule({ ruleId: "r_prohibit_1", ruleType: "prohibition", minValue: null, maxValue: null, unit: null }),
    ]);
    const v = evaluateUsage(usage({ value: 9999 }), set);
    expect(v.status).toBe("prohibited");
  });
});

describe("evaluateUsage · 限量判定", () => {
  it("区间内 → compliant, 带溯源", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    const v = evaluateUsage(usage({ value: 200 }), set);
    expect(v.status).toBe("compliant");
    expect(v.ruleHits).toHaveLength(1);
    expect(v.ruleHits[0].sourceArticleId).toContain("安全使用规范");
    expect(v.ruleHits[0].sourceExcerpt).toContain("150～300");
  });

  it("超上限 → exceeded + 超出量", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    const v = evaluateUsage(usage({ value: 500 }), set);
    expect(v.status).toBe("exceeded");
    expect(v.suggestion?.maxAllowed).toBe(300);
    expect(v.suggestion?.message).toContain("200");
  });

  it("低于下限 → exceeded", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    const v = evaluateUsage(usage({ value: 10 }), set);
    expect(v.status).toBe("exceeded");
    expect(v.suggestion?.message).toContain("低于下限");
  });

  it("恰好等于上限 → compliant", () => {
    const set = new ComplianceRuleSet("v1", [VC_PIG]);
    expect(evaluateUsage(usage({ value: 300 }), set).status).toBe("compliant");
  });

  it("取最严的规则(多条命中时)", () => {
    const set = new ComplianceRuleSet("v1", [
      rule({ ruleId: "r_loose", maxValue: 1000 }),
      rule({ ruleId: "r_strict", maxValue: 200 }),
    ]);
    const v = evaluateUsage(usage({ value: 500 }), set);
    expect(v.status).toBe("exceeded");
    expect(v.suggestion?.maxAllowed).toBe(200);
    expect(v.ruleHits).toHaveLength(2);
  });
});

describe("evaluateUsage · 审核闸门", () => {
  it("pending 状态的规则不参与判定 → not_covered", () => {
    const set = new ComplianceRuleSet("v1", [rule({ reviewStatus: "pending" })]);
    const v = evaluateUsage(usage(), set);
    expect(v.status).toBe("not_covered");
  });

  it("rejected 状态的规则不参与判定", () => {
    const set = new ComplianceRuleSet("v1", [rule({ reviewStatus: "rejected" })]);
    expect(evaluateUsage(usage(), set).status).toBe("not_covered");
  });

  it("reviewed 才生效", () => {
    const set = new ComplianceRuleSet("v1", [rule({ reviewStatus: "reviewed" })]);
    expect(evaluateUsage(usage(), set).status).toBe("compliant");
  });
});

describe("ruleMatches", () => {
  it("物质+动物都匹配", () => {
    expect(ruleMatches(VC_PIG, usage())).toBe(true);
  });

  it("动物不匹配", () => {
    expect(ruleMatches(VC_PIG, usage({ species: "鸡" }))).toBe(false);
  });

  it("规则无动物限定 → 适用", () => {
    const r = rule({ species: null });
    expect(ruleMatches(r, usage({ species: "鸡" }))).toBe(true);
  });

  it("规则有阶段且请求阶段不同 → 不适用", () => {
    const r = rule({ stage: "育肥猪" });
    expect(ruleMatches(r, usage({ stage: "仔猪" }))).toBe(false);
  });

  it("规则有阶段但请求无阶段 → 适用(保守放宽)", () => {
    const r = rule({ stage: "育肥猪" });
    expect(ruleMatches(r, usage({ stage: null }))).toBe(true);
  });

  it("组合约束类型不参与单体判定", () => {
    const r = rule({ ruleType: "combination" });
    expect(ruleMatches(r, usage())).toBe(false);
  });
});

describe("unitComparable", () => {
  it("相同单位可比", () => {
    expect(unitComparable("mg/kg", "mg/kg")).toBe(true);
  });

  it("不同单位不可比", () => {
    expect(unitComparable("IU/kg", "mg/kg")).toBe(false);
  });

  it("规则无单位不可比", () => {
    expect(unitComparable(null, "mg/kg")).toBe(false);
  });
});

describe("ComplianceRuleSet", () => {
  it("reviewed 只返回已审核的", () => {
    const set = new ComplianceRuleSet("v1", [
      rule({ ruleId: "a", reviewStatus: "reviewed" }),
      rule({ ruleId: "b", reviewStatus: "pending" }),
      rule({ ruleId: "c", reviewStatus: "rejected" }),
    ]);
    expect(set.reviewed).toHaveLength(1);
    expect(set.reviewed[0].ruleId).toBe("a");
  });

  it("all 返回全部", () => {
    const set = new ComplianceRuleSet("v1", [
      rule({ ruleId: "a", reviewStatus: "reviewed" }),
      rule({ ruleId: "b", reviewStatus: "pending" }),
    ]);
    expect(set.all).toHaveLength(2);
  });

  it("findBySubstance 只在已审核里找", () => {
    const set = new ComplianceRuleSet("v1", [
      rule({ ruleId: "a", reviewStatus: "reviewed" }),
      rule({ ruleId: "b", reviewStatus: "pending" }),
    ]);
    expect(set.findBySubstance("L-抗坏血酸(维生素C)")).toHaveLength(1);
  });

  it("findById 能在全部里找", () => {
    const set = new ComplianceRuleSet("v1", [rule({ ruleId: "x", reviewStatus: "pending" })]);
    expect(set.findById("x")?.ruleId).toBe("x");
  });

  it("ruleSetVersion 可读", () => {
    expect(new ComplianceRuleSet("v2026.10", []).ruleSetVersion).toBe("v2026.10");
  });
});
