/**
 * C1 · 真实数据集成校验 —— 用**实际抽取产物**跑完整判定链路
 *
 * ## 为什么要有这个测试
 *
 * 单元测试用的是手写 fixture, 全是「理想形态」。但真实数据里:
 *   · 物质名有 OCR 掉的英文名(已被 enrich_bilingual_names.py 转成中文)
 *   · 中文名有全角/半角括号差异
 *   · 目录与安全使用规范对同一物质中文写法不同
 *     (目录「二甲基嘧啶醇亚硫酸甲萘醌」vs 规则「二甲基嘧啶醇亚硫酸氢钠甲萘醌」)
 *   · 上下限可能是单值(150~150)
 *   · 有些物质在目录里但**没有**限量规则
 *
 * 这些形态组合起来, 单元测试覆盖不到。**灌库前必须用真数据跑一遍**,
 * 否则灌完库才发现「明明库里有规则却判 not_covered」, 就太晚了。
 *
 * ## 跑的是**生产链路**
 *
 * `ComplianceCheckService.check()` —— 也就是 API `/api/compliance/usage`
 * 实际走的那条路: 物质名解析 → 与规则库对齐 → 领域判定 → 组装响应。
 *
 * ## 数据来源
 *
 * `build/export/compliance_rules.json` + `build/export/substance_catalog.json`
 * —— CI 里由 ingest_minimax.py → extract_compliance_rules.py →
 * enrich_bilingual_names.py 三步生成。
 *
 * ⚠️ 若这两个文件不存在, 本测试**跳过**(不失败)——
 *    纯逻辑单测不该依赖构建产物。
 */

import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { ComplianceRuleSet } from "./compliance-rule-set.aggregate";
import type { ComplianceRule } from "./compliance-rule-set.aggregate";
import { ComplianceCheckService } from "../../application/compliance/compliance-check.usecase";
import type { SubstanceCatalogEntry } from "./substance-catalog.vo";

// worker/src/domain/compliance → 往上 5 层才是仓库根
//   compliance → domain → src → worker → query → <repo>
const REPO = join(__dirname, "..", "..", "..", "..", "..");
const RULES_PATH = join(REPO, "build", "export", "compliance_rules.json");
const CATALOG_PATH = join(REPO, "build", "export", "substance_catalog.json");

const hasData = existsSync(RULES_PATH) && existsSync(CATALOG_PATH);

interface RawRule {
  rule_type: string;
  substance: string;
  substance_alias?: string;
  species: string;
  stage: string;
  min_value: number | null;
  max_value: number | null;
  unit: string;
  source_article_id: string;
  source_doc_id: string;
  source_excerpt: string;
  review_status: string;
}

interface RawCatalog {
  name_cn: string;
  name_en?: string;
  substance_alias?: string;
  category?: string;
  scope_text?: string;
  source_article_id: string;
  source_doc_id: string;
  review_status: string;
}

/** 把抽取产物转成领域层的值对象形态。 */
function toRule(r: RawRule, i: number): ComplianceRule {
  return {
    ruleId: `r_${String(i + 1).padStart(3, "0")}`,
    ruleType: r.rule_type as ComplianceRule["ruleType"],
    substance: r.substance,
    substanceAlias: r.substance_alias ?? null,
    species: r.species,
    stage: r.stage || null,
    minValue: r.min_value,
    maxValue: r.max_value,
    unit: r.unit,
    conditionText: null,
    sourceArticleId: r.source_article_id,
    sourceDocId: r.source_doc_id,
    sourceExcerpt: r.source_excerpt,
    ruleSetVersion: "v2026.10",
    extractionMethod: "auto",
    reviewStatus: "reviewed", // 集成测试假设「已校核」
  };
}

function toCatalog(c: RawCatalog, i: number): SubstanceCatalogEntry {
  return {
    substanceId: `s_${String(i + 1).padStart(4, "0")}`,
    nameCn: c.name_cn,
    nameEn: c.name_en || null,
    substanceAlias: c.substance_alias || null,
    formula: null,
    source: null,
    spec: null,
    category: c.category || null,
    scopeText: c.scope_text || null,
    sourceArticleId: c.source_article_id,
    sourceDocId: c.source_doc_id,
    ruleSetVersion: "v2026.10",
    reviewStatus: "reviewed",
  };
}

describe.skipIf(!hasData)("C1 · 真实抽取数据集成校验", () => {
  let rules: ComplianceRule[];
  let catalog: SubstanceCatalogEntry[];
  let rawRules: RawRule[];
  let service: ComplianceCheckService;

  beforeAll(() => {
    const rd = JSON.parse(readFileSync(RULES_PATH, "utf-8"));
    const cd = JSON.parse(readFileSync(CATALOG_PATH, "utf-8"));
    rawRules = rd.rules;
    rules = rawRules.map(toRule);
    catalog = cd.substances.map(toCatalog);

    const ruleSet = new ComplianceRuleSet("v2026.10", rules);
    service = new ComplianceCheckService(
      {
        async listRules() {
          return ruleSet;
        },
        async listCatalog() {
          return catalog;
        },
      },
      {
        async search() {
          return { hits: [] };
        },
      }
    );
  });

  // ─────────────────────────── 数据质量 ───────────────────────────

  it("抽取产物非空", () => {
    expect(rules.length).toBeGreaterThan(0);
    expect(catalog.length).toBeGreaterThan(0);
  });

  it("⚠️ 不变量 2: 每条规则都有溯源(source_article_id 非空)", () => {
    expect(rules.filter((r) => !r.sourceArticleId)).toHaveLength(0);
  });

  it("⚠️ 不变量 2: 每条目录条目都有溯源", () => {
    expect(catalog.filter((c) => !c.sourceArticleId)).toHaveLength(0);
  });

  it("物质名不是 OCR 掉的纯拉丁名(已被双语补全转成中文)", () => {
    const latinOnly = rules.filter(
      (r) => r.substance && /^[A-Za-z()\s]+$/.test(r.substance)
    );
    expect(latinOnly.map((r) => r.substance)).toEqual([]);
  });

  it("目录里没有纯适用范围被当成物质名(畜禽/猪、家禽 之类)", () => {
    const bad = catalog.filter((c) =>
      /^(养殖动物|畜禽|反刍动物|宠物|家禽|犬|猫|鸡|猪|牛|羊)$/.test(c.nameCn)
    );
    expect(bad.map((c) => c.nameCn)).toEqual([]);
  });

  it("目录里没有新产品审定条目(不该混进品种目录)", () => {
    const bad = catalog.filter((c) =>
      /申请单位|批准文号/.test(c.nameCn + (c.scopeText ?? ""))
    );
    expect(bad).toHaveLength(0);
  });

  it("每条规则的物质都能在目录里找到(直接命中或经英文名关联)", () => {
    const names = new Set(catalog.map((c) => c.nameCn));
    const byEn = new Map<string, string>();
    for (const c of catalog) {
      if (!c.nameEn) continue;
      const k = c.nameEn.replace(/\s*\([A-Za-z]{1,6}\)\s*$/, "").toLowerCase();
      byEn.set(k, c.nameCn);
    }
    const orphan = rules.filter((r) => {
      if (names.has(r.substance ?? "")) return false;
      const alias = (r.substanceAlias ?? "")
        .replace(/\s*\([A-Za-z]{1,6}\)\s*$/, "")
        .toLowerCase();
      return !(alias && byEn.has(alias));
    });
    expect(orphan.map((r) => r.substance)).toEqual([]);
  });

  // ─────────────────────────── 判定链路 ───────────────────────────

  it("判定: 维生素C + 猪 + 200mg/kg → 合规 + 带原文依据", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "mg/kg",
    });
    // 目录里是「L-抗坏血酸(维生素C)」, 括号别名应命中
    expect(r.status).toBe("compliant");
    expect(r.matchedSubstance).toContain("抗坏血酸");
    expect(r.ruleHits.length).toBeGreaterThan(0);
    expect(r.ruleHits[0].sourceExcerpt).toBeTruthy();
    expect(r.ruleHits[0].sourceArticleId).toContain("安全使用规范");
  });

  it("判定: 维生素C + 猪 + 500mg/kg → 超限 + 给出建议上限 300", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 500,
      unit: "mg/kg",
    });
    expect(r.status).toBe("exceeded");
    expect(r.suggestion?.maxAllowed).toBe(300);
  });

  it("判定: 维生素C + 猪 + 100mg/kg → 低于下限 → 超限", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 100,
      unit: "mg/kg",
    });
    expect(r.status).toBe("exceeded");
  });

  it("判定: 未收录物质 → not_covered(绝不返回 compliant)", async () => {
    const r = await service.check({
      substance: "某种不存在的添加剂",
      species: "猪",
      value: 100,
      unit: "mg/kg",
    });
    expect(r.status).toBe("not_covered");
    expect(r.status).not.toBe("compliant");
    expect(r.coverageGap).toBeTruthy();
  });

  it("判定: 物质在目录里但该动物无规则 → not_covered", async () => {
    const r = await service.check({
      substance: "二氧化硅",
      species: "猪",
      value: 100,
      unit: "mg/kg",
    });
    expect(r.status).toBe("not_covered");
  });

  it("判定: 英文名也能命中(Niacinamide → 烟酰胺)", async () => {
    const r = await service.check({
      substance: "Niacinamide",
      species: "猪",
      value: 40,
      unit: "mg/kg",
    });
    // 烟酰胺 猪 30~60 mg/kg → 40 合规
    expect(r.status).toBe("compliant");
  });

  it("判定: 目录名与规则名写法不同时, 靠英文名对齐仍能命中", async () => {
    const r = await service.check({
      substance: "二甲基嘧啶醇亚硫酸甲萘醌",
      species: "猪",
      value: 10,
      unit: "mg/kg",
    });
    expect(r.status).toBe("compliant");
  });

  it("⚠️ 抗坏血酸钙 不会被「维生素C」抢走(限量不同, 猜了就是错)", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "mg/kg",
    });
    const hitSubstances = r.ruleHits.map((h) =>
      rules.find((x) => x.ruleId === h.ruleId)?.substance
    );
    expect(hitSubstances).not.toContain("L-抗坏血酸钙");
  });

  it("⚠️ 单位不同不比对(mg/kg vs IU/kg → not_covered, 不猜)", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "IU/kg",
    });
    expect(r.status).toBe("not_covered");
  });

  it("响应带免责标注与规则集版本(结论可回溯)", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "mg/kg",
    });
    expect(r.notice).toContain("不构成监管结论");
    expect(r.ruleSetVersion).toBe("v2026.10");
  });

  it("未审核规则不参与判定(review_status 闸门)", async () => {
    const pending = rules.map((r) => ({ ...r, reviewStatus: "pending" as const }));
    const ruleSet = new ComplianceRuleSet("v2026.10", pending);
    const svc = new ComplianceCheckService(
      {
        async listRules() {
          return ruleSet;
        },
        async listCatalog() {
          return catalog;
        },
      },
      { async search() { return { hits: [] }; } }
    );
    const r = await svc.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "mg/kg",
    });
    expect(r.status).toBe("not_covered");
  });

  it("每条命中规则都带原文出处(不变量 2 在判定层也成立)", async () => {
    const r = await service.check({
      substance: "维生素C",
      species: "猪",
      value: 200,
      unit: "mg/kg",
    });
    for (const h of r.ruleHits) {
      expect(h.sourceArticleId).toBeTruthy();
      expect(h.sourceExcerpt).toBeTruthy();
    }
  });

  it("每种有规则的物质, 抽 1 条都能命中(全量覆盖检查)", async () => {
    const bySub = new Map<string, RawRule>();
    for (const r of rawRules) {
      if (!bySub.has(r.substance)) bySub.set(r.substance, r);
    }
    const failures: string[] = [];
    for (const [sub, r] of bySub) {
      const res = await service.check({
        substance: sub,
        species: r.species,
        value: r.min_value ?? 0,
        unit: r.unit,
      });
      if (res.status === "not_covered") failures.push(`${sub} / ${r.species}`);
    }
    expect(failures).toEqual([]);
  });
});
