/**
 * ③ 问答 · 会话上下文单测
 *
 * 重点: **指代消解**的规则边界。
 * 补错了 → 检索被污染; 补漏了 → 退化成单轮问答(可接受)。
 */

import { describe, it, expect } from "vitest";
import {
  extractEntities,
  findSpeciesTerms,
  findSubstanceTerms,
  mergeEntities,
  recentTurns,
  resolveContext,
  type ExtractedEntities,
} from "./conversation-context.vo";

describe("findSpeciesTerms", () => {
  it("识别单个动物", () => {
    expect(findSpeciesTerms("猪饲料的维生素C上限")).toContain("猪");
  });

  it("多个动物", () => {
    const r = findSpeciesTerms("猪和家禽的限量");
    expect(r).toContain("猪");
    expect(r).toContain("家禽");
  });

  it("⚠️ 长词优先 —— 「肉用鸡」不该被截成「鸡」", () => {
    const r = findSpeciesTerms("肉用鸡和蛋鸡");
    expect(r).toContain("肉用鸡");
    expect(r).toContain("蛋鸡");
    // 「鸡」被更长的词覆盖, 不该单独出现
    expect(r).not.toContain("鸡");
  });

  it("无动物返回空", () => {
    expect(findSpeciesTerms("饲料标签要标注什么")).toEqual([]);
  });
});

describe("findSubstanceTerms", () => {
  it("识别物质名", () => {
    expect(findSubstanceTerms("维生素C的使用上限")).toContain("维生素C");
  });

  it("长词优先 —— 「维生素D3」不该被截成「维生素」", () => {
    const r = findSubstanceTerms("维生素D3的用量");
    expect(r).toContain("维生素D3");
  });

  it("无物质返回空", () => {
    expect(findSubstanceTerms("今天天气怎么样")).toEqual([]);
  });
});

describe("extractEntities", () => {
  it("提取物质 + 动物", () => {
    const e = extractEntities("维生素C在猪饲料中的上限是多少");
    expect(e).toHaveLength(1);
    expect(e[0].substance).toBe("维生素C");
    expect(e[0].species).toBe("猪");
  });

  it("多个物质各成一条", () => {
    const e = extractEntities("维生素C和烟酰胺的使用量");
    expect(e.length).toBeGreaterThanOrEqual(2);
  });

  it("只有动物 → 记一条 substance 为空", () => {
    const e = extractEntities("那鸡呢");
    expect(e).toHaveLength(1);
    expect(e[0].substance).toBe("");
    expect(e[0].species).toBe("鸡");
  });

  it("什么都没有 → 空数组", () => {
    expect(extractEntities("嗯")).toEqual([]);
  });
});

describe("resolveContext —— 指代消解", () => {
  const prev: ExtractedEntities[] = [{ substance: "维生素C", species: "猪" }];

  it("✅ 追问含动物不含物质 → 补上一轮的物质", () => {
    const q = resolveContext(prev, "那鸡呢？");
    expect(q).toContain("维生素C");
    expect(q).toContain("那鸡呢");
  });

  it("✅ 追问什么都没说 → 补上一轮的物质", () => {
    const q = resolveContext(prev, "那上限呢？");
    expect(q).toContain("维生素C");
  });

  it("⚠️ 当前问句已含物质 → 不补(用户换了话题)", () => {
    const q = resolveContext(prev, "烟酰胺的使用量是多少");
    expect(q).toBe("烟酰胺的使用量是多少");
    expect(q).not.toContain("维生素C");
  });

  it("✅ 无历史实体 → 原样返回", () => {
    const q = resolveContext([], "那鸡呢？");
    expect(q).toBe("那鸡呢？");
  });

  it("✅ 空问句 → 空串", () => {
    expect(resolveContext(prev, "")).toBe("");
  });

  it("⚠️ 只补一轮 —— 不累加多轮历史", () => {
    const multi: ExtractedEntities[] = [
      { substance: "维生素C", species: "猪" },
      { substance: "烟酰胺", species: "鸡" },
    ];
    const q = resolveContext(multi, "那上限呢？");
    // 只补**最后一个**有物质名的实体, 不是两个都补
    expect(q).toContain("烟酰胺");
    expect(q).not.toContain("维生素C");
  });

  it("✅ 上一轮只有动物 → 追问时补动物", () => {
    const animalOnly: ExtractedEntities[] = [{ substance: "", species: "猪" }];
    const q = resolveContext(animalOnly, "上限是多少");
    expect(q).toContain("猪");
  });

  it("⚠️ 问句含动物且上一轮无物质 → 不补(补了会错)", () => {
    const animalOnly: ExtractedEntities[] = [{ substance: "", species: "猪" }];
    const q = resolveContext(animalOnly, "那鸡呢？");
    expect(q).toBe("那鸡呢？");
  });
});

describe("mergeEntities", () => {
  it("新实体覆盖同名的旧实体", () => {
    const merged = mergeEntities(
      [{ substance: "维生素C", species: "猪" }],
      [{ substance: "维生素C", species: "鸡" }]
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].species).toBe("鸡");
  });

  it("不同物质累加", () => {
    const merged = mergeEntities(
      [{ substance: "维生素C", species: "猪" }],
      [{ substance: "烟酰胺", species: "鸡" }]
    );
    expect(merged).toHaveLength(2);
  });

  it("空实体被忽略", () => {
    const merged = mergeEntities(
      [{ substance: "维生素C", species: "猪" }],
      [{ substance: "", species: null }]
    );
    expect(merged).toHaveLength(1);
  });
});

describe("recentTurns", () => {
  it("取最近 N 轮", () => {
    const turns = [1, 2, 3, 4, 5].map((i) => ({
      question: `q${i}`,
      answer: `a${i}`,
    }));
    const r = recentTurns({ sessionId: "s", turns, entities: [] }, 3);
    expect(r).toHaveLength(3);
    expect(r[2].question).toBe("q5");
  });

  it("不足 N 轮时全给", () => {
    const r = recentTurns(
      { sessionId: "s", turns: [{ question: "q1", answer: "a1" }], entities: [] },
      3
    );
    expect(r).toHaveLength(1);
  });
});
