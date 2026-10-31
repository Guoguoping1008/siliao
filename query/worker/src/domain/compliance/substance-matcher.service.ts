/**
 * 物质名匹配 —— 领域服务
 *
 * 上下文: ② 合规规则 Compliance
 *
 * ## 为什么需要它
 *
 * 用户输入「维生素C」, 规则库里的名字是「L-抗坏血酸(维生素C)」。
 * 匹配不上就会判成 not_covered —— 但实际上库里有这条规则。
 *
 * ## 三级匹配(依次降级)
 *
 *   1. 精确匹配   name_cn 完全相等
 *   2. 括号别名   从「L-抗坏血酸(维生素C)」的括号里提取「维生素C」
 *   3. 别名表     substance_alias(英文名/化学名)
 *
 * ## ⚠️ **不做模糊匹配**
 *
 * 向量相似度匹配出来的「维生素C ≈ 抗坏血酸钙」在合规判定里是**危险**的 ——
 * 抗坏血酸钙和抗坏血酸的限量完全不同(前者是「养殖动物 80.5%」的质量指标)。
 *
 * **宁可说「未覆盖, 需人工确认」, 不可猜。**
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 纯函数, 零 I/O。
 */

import type { SubstanceCatalogEntry } from "./substance-catalog.vo";

/** 匹配方式。 */
export type MatchMethod = "exact" | "alias";

/** 匹配结果。 */
export interface SubstanceMatch {
  entry: SubstanceCatalogEntry;
  method: MatchMethod;
}

/** 从「L-抗坏血酸(维生素C)」这类名字里提取括号别名。 */
export function extractBracketAlias(name: string): string | null {
  const m = name.match(/[（(]([^）)]+)[）)]/);
  return m ? m[1].trim() : null;
}

/**
 * 名字归一 —— 只做**安全的形态归一**, 不做语义推理。
 *
 * ⚠️ 为什么需要: 语料里同一物质有多种写法:
 *   目录      「L-抗坏血酸（维生素C）」(全角括号)
 *   规则库    「L-抗坏血酸(维生素C)」(半角括号)
 *   目录      「L-抗坏血酸*」        (脚注星号)
 *   英文名    「Menadione … bisulfite (MPB)」(带缩写)
 *   OCR       「Nicotinicacid」      (词间空格被吃掉)
 *
 * 归一只做: 全角→半角括号、去首尾空格、去脚注上标与尾随星号。
 * **不改大小写、不删词、不做相似度** —— 那些是「猜」, 在合规判定里危险。
 */
export function normalizeName(s: string): string {
  return (s || "")
    .replace(/（/g, "(")
    .replace(/）/g, ")")
    .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹⁺]+/g, "")
    .replace(/\s*\*+\s*$/g, "")
    .trim();
}

/** 大小写不敏感的比较。 */
function eqIgnoreCase(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase();
}

/** 归一后 + 大小写不敏感的比较。 */
function eqNormalized(a: string, b: string): boolean {
  return eqIgnoreCase(normalizeName(a), normalizeName(b));
}

/**
 * 匹配物质。
 *
 * @param input    用户输入的物质名
 * @param catalog  物质目录
 *
 * @returns 匹配结果; 匹配不上返回 null(调用方据此判 not_covered)
 */
export function matchSubstance(
  input: string,
  catalog: SubstanceCatalogEntry[]
): SubstanceMatch | null {
  const q = normalizeName(input || "");
  if (!q) return null;

  // ── 1. 精确匹配(归一后) ──
  for (const e of catalog) {
    if (normalizeName(e.nameCn) === q) return { entry: e, method: "exact" };
  }

  // ── 2. 括号别名 ──
  for (const e of catalog) {
    const alias = extractBracketAlias(e.nameCn);
    if (alias && eqNormalized(alias, q)) {
      return { entry: e, method: "alias" };
    }
  }

  // ── 3. 别名表(英文名/化学名) ──
  for (const e of catalog) {
    if (e.nameEn && eqNormalized(e.nameEn, q)) {
      return { entry: e, method: "alias" };
    }
    if (e.substanceAlias && eqNormalized(e.substanceAlias, q)) {
      return { entry: e, method: "alias" };
    }
  }

  return null;
}
