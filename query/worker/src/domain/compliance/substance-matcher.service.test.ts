/**
 * ② 合规规则 —— 物质名匹配单测
 *
 * 重点: **不做模糊匹配** —— 「维生素C」不能模糊匹配到「抗坏血酸钙」。
 */

import { describe, it, expect } from "vitest";
import {
  matchSubstance,
  extractBracketAlias,
  normalizeName,
} from "./substance-matcher.service";
import type { SubstanceCatalogEntry } from "./substance-catalog.vo";

function entry(over: Partial<SubstanceCatalogEntry> = {}): SubstanceCatalogEntry {
  return {
    substanceId: "s1",
    nameCn: "L-抗坏血酸(维生素C)",
    nameEn: "L-Ascorbic acid (Vitamin C)",
    substanceAlias: null,
    formula: "C6 H8 O6",
    source: "化学制备或发酵生产",
    spec: "-",
    category: "添加剂",
    scopeText: "养殖动物",
    sourceArticleId: "a1",
    sourceDocId: "d1",
    ruleSetVersion: "v2026.10",
    reviewStatus: "reviewed",
    ...over,
  };
}

const CATALOG: SubstanceCatalogEntry[] = [
  entry({ substanceId: "s1", nameCn: "L-抗坏血酸(维生素C)", nameEn: "L-Ascorbic acid (Vitamin C)" }),
  entry({ substanceId: "s2", nameCn: "L-抗坏血酸钙", nameEn: "Calcium L-α-ascorbate" }),
  entry({ substanceId: "s3", nameCn: "烟酰胺", nameEn: "Niacinamide" }),
  entry({
    substanceId: "s4",
    nameCn: "维生素B2",
    nameEn: "Riboflavin",
    substanceAlias: "核黄素",
  }),
];

describe("extractBracketAlias", () => {
  it("提取半角括号", () => {
    expect(extractBracketAlias("L-抗坏血酸(维生素C)")).toBe("维生素C");
  });

  it("提取全角括号", () => {
    expect(extractBracketAlias("25-羟基胆钙化醇（25-羟基维生素D3）")).toBe("25-羟基维生素D3");
  });

  it("无括号返回 null", () => {
    expect(extractBracketAlias("烟酰胺")).toBeNull();
  });
});

describe("matchSubstance", () => {
  it("精确匹配", () => {
    const m = matchSubstance("烟酰胺", CATALOG);
    expect(m?.entry.substanceId).toBe("s3");
    expect(m?.method).toBe("exact");
  });

  it("括号别名匹配(维生素C → L-抗坏血酸(维生素C))", () => {
    const m = matchSubstance("维生素C", CATALOG);
    expect(m?.entry.substanceId).toBe("s1");
    expect(m?.method).toBe("alias");
  });

  it("英文名匹配", () => {
    const m = matchSubstance("Niacinamide", CATALOG);
    expect(m?.entry.substanceId).toBe("s3");
    expect(m?.method).toBe("alias");
  });

  it("英文名大小写不敏感", () => {
    const m = matchSubstance("niacinamide", CATALOG);
    expect(m?.entry.substanceId).toBe("s3");
  });

  it("别名表匹配(核黄素 → 维生素B2)", () => {
    const m = matchSubstance("核黄素", CATALOG);
    expect(m?.entry.substanceId).toBe("s4");
  });

  it("未收录物质 → null(调用方判 not_covered)", () => {
    expect(matchSubstance("某种不存在的物质", CATALOG)).toBeNull();
  });

  it("空输入 → null", () => {
    expect(matchSubstance("", CATALOG)).toBeNull();
  });

  it("⚠️ 不做模糊匹配: 维生素C 不会匹配到 抗坏血酸钙", () => {
    const m = matchSubstance("维生素C", CATALOG);
    expect(m?.entry.substanceId).not.toBe("s2");
    expect(m?.entry.nameCn).toContain("抗坏血酸(维生素C)");
  });

  it("⚠️ 抗坏血酸钙 有自己的条目, 不会被维生素C 抢走", () => {
    const m = matchSubstance("L-抗坏血酸钙", CATALOG);
    expect(m?.entry.substanceId).toBe("s2");
    expect(m?.method).toBe("exact");
  });

  it("精确匹配优先于括号别名", () => {
    // 假设目录里同时有一个精确叫「维生素C」的条目
    const cat = [...CATALOG, entry({ substanceId: "s5", nameCn: "维生素C" })];
    const m = matchSubstance("维生素C", cat);
    expect(m?.entry.substanceId).toBe("s5");
    expect(m?.method).toBe("exact");
  });

  it("空目录 → null", () => {
    expect(matchSubstance("维生素C", [])).toBeNull();
  });
});

describe("normalizeName —— 形态归一(不做语义推理)", () => {
  it("全角括号 → 半角", () => {
    expect(normalizeName("L-抗坏血酸（维生素C）")).toBe("L-抗坏血酸(维生素C)");
  });

  it("去尾随脚注星号", () => {
    expect(normalizeName("L-抗坏血酸*")).toBe("L-抗坏血酸");
  });

  it("去脚注上标", () => {
    expect(normalizeName("犬⁴")).toBe("犬");
  });

  it("去首尾空格", () => {
    expect(normalizeName("  烟酰胺  ")).toBe("烟酰胺");
  });

  it("⚠️ 不改大小写", () => {
    expect(normalizeName("Niacinamide")).toBe("Niacinamide");
  });

  it("⚠️ 不删词 —— 只做形态归一", () => {
    expect(normalizeName("L-抗坏血酸钙")).not.toBe("L-抗坏血酸");
  });
});

describe("matchSubstance —— 全角/半角括号跨表匹配", () => {
  it("半角输入匹配全角目录条目", () => {
    const cat = [entry({ substanceId: "s9", nameCn: "L-抗坏血酸（维生素C）" })];
    const m = matchSubstance("L-抗坏血酸(维生素C)", cat);
    expect(m?.entry.substanceId).toBe("s9");
    expect(m?.method).toBe("exact");
  });

  it("全角输入匹配半角目录条目", () => {
    const cat = [entry({ substanceId: "s9", nameCn: "L-抗坏血酸(维生素C)" })];
    const m = matchSubstance("L-抗坏血酸（维生素C）", cat);
    expect(m?.entry.substanceId).toBe("s9");
  });

  it("尾随脚注星号不影响匹配", () => {
    const cat = [entry({ substanceId: "s9", nameCn: "L-抗坏血酸" })];
    expect(matchSubstance("L-抗坏血酸*", cat)?.entry.substanceId).toBe("s9");
  });

  it("⚠️ 归一不放松语义 —— 抗坏血酸钙 仍不会被维生素C 抢走", () => {
    const cat = [
      entry({ substanceId: "s1", nameCn: "L-抗坏血酸(维生素C)" }),
      entry({ substanceId: "s2", nameCn: "L-抗坏血酸钙" }),
    ];
    const m = matchSubstance("维生素C", cat);
    expect(m?.entry.substanceId).toBe("s1");
    expect(m?.entry.nameCn).not.toContain("钙");
  });
});
