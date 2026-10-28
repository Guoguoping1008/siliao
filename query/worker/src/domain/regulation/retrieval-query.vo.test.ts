/**
 * ① 法规知识库 —— 检索查询逻辑单测
 *
 * 测的是**领域规则**: gram 切分策略、FTS5 表达式构造、RRF 融合权重。
 * 这些全是纯函数, 不用起 D1 或 bge 服务 —— 这正是 ADR-004 M1 的价值。
 */

import { describe, it, expect } from "vitest";
import {
  CJK_2CHAR_RE,
  STOP_BIGRAMS,
  escapeFts,
  fuseRankedRows,
  gramExpr,
  queryTermGrams,
  RRF_K,
  TITLE_BOOST,
  BGE_WEIGHT,
  FTS_WEIGHT,
} from "./retrieval-query.vo";

describe("queryTermGrams", () => {
  it("中文切成重叠 bigram", () => {
    expect(queryTermGrams("新兽药注册办法")).toEqual([
      "新兽", "兽药", "药注", "注册", "册办", "办法",
    ]);
  });

  it("去掉停用 bigram", () => {
    const grams = queryTermGrams("需要什么材料");
    expect(grams).not.toContain("需要");
    expect(grams).not.toContain("什么");
  });

  it("英文数字保留整词", () => {
    expect(queryTermGrams("GB 10648 标签")).toContain("GB");
    expect(queryTermGrams("GB 10648 标签")).toContain("10648");
  });

  it("单个汉字保留", () => {
    expect(queryTermGrams("鱼")).toEqual(["鱼"]);
  });

  it("去重保序(重复 bigram 只留一个)", () => {
    // "饲料饲料" 的重叠 bigram 是 饲料/料饲/饲料 → 去重后 饲料/料饲
    expect(queryTermGrams("饲料饲料")).toEqual(["饲料", "料饲"]);
  });

  it("空串返回空数组", () => {
    expect(queryTermGrams("")).toEqual([]);
  });

  it("纯符号返回空数组", () => {
    expect(queryTermGrams("!!!@@@")).toEqual([]);
  });

  it("单个拉丁字母被丢弃(英文词要求 ≥2 字符)", () => {
    // 原始实现: `if (w.length >= 2) push(w)` —— 单个 "C" 不进检索词
    expect(queryTermGrams("维生素C添加量")).not.toContain("C");
  });

  it("中英混合: 拉丁词 ≥2 字符保留, 中文切 bigram", () => {
    const grams = queryTermGrams("维生素GB添加量");
    expect(grams).toContain("GB");
    expect(grams).toContain("维生");
    expect(grams).toContain("添加");
  });
});

describe("gramExpr", () => {
  it("2 字 gram 补后缀成多个 phrase 并用 OR 连接", () => {
    const expr = gramExpr("饲料");
    expect(expr).toContain('"饲料 "');
    expect(expr).toContain('"饲料的"');
    expect(expr).toContain(" OR ");
  });

  it("3 字及以上直接加引号", () => {
    expect(gramExpr("添加剂")).toBe('"添加剂"');
  });

  it("每个 phrase 都带引号(FTS5 语法要求)", () => {
    const expr = gramExpr("饲料");
    for (const part of expr.split(" OR ")) {
      expect(part.startsWith('"')).toBe(true);
      expect(part.endsWith('"')).toBe(true);
    }
  });
});

describe("escapeFts", () => {
  it("纯中文 2 字补后缀", () => {
    expect(escapeFts("总则")).toContain('"总则 "');
  });

  it("3 字以上原样返回", () => {
    expect(escapeFts("添加剂")).toBe("添加剂");
  });

  it("截断到 64 字符", () => {
    expect(escapeFts("x".repeat(200)).length).toBeLessThanOrEqual(64);
  });

  it("去控制字符", () => {
    expect(escapeFts("a\u0000b")).not.toContain("\u0000");
  });

  it("空串返回空串", () => {
    expect(escapeFts("")).toBe("");
  });

  it("纯空白返回空串", () => {
    expect(escapeFts("   ")).toBe("");
  });

  it("CJK_2CHAR_RE 只匹配纯中文两字", () => {
    expect(CJK_2CHAR_RE.test("总则")).toBe(true);
    expect(CJK_2CHAR_RE.test("添 加")).toBe(false);
    expect(CJK_2CHAR_RE.test("添加剂")).toBe(false);
    expect(CJK_2CHAR_RE.test("AB")).toBe(false);
  });
});

describe("fuseRankedRows", () => {
  it("两路都命中同一文档 → 分数相加", () => {
    const out = fuseRankedRows(
      [{ article_id: "a", rank: 1 }],
      [{ article_id: "a", rank: 1, score: 0.9 }],
      20
    );
    expect(out).toHaveLength(1);
    expect(out[0].fused_score).toBeCloseTo(2 / (RRF_K + 1), 10);
  });

  it("只有 FTS 命中的文档排在只有 bge 命中的前面(等权重下 rank 决定)", () => {
    const out = fuseRankedRows(
      [{ article_id: "fts", rank: 1 }],
      [{ article_id: "bge", rank: 1, score: 0.5 }],
      20
    );
    expect(out[0].article_id).toBe("fts");
  });

  it("两路权重相等 —— 这是扫参结论, 不能改", () => {
    expect(FTS_WEIGHT).toBe(1.0);
    expect(BGE_WEIGHT).toBe(1.0);
  });

  it("保留 ftsRank / bgeRank 调试字段", () => {
    const out = fuseRankedRows(
      [{ article_id: "a", rank: 3 }],
      [{ article_id: "a", rank: 7, score: 0.8 }],
      20
    );
    expect(out[0].ftsRank).toBe(3);
    expect(out[0].bgeRank).toBe(7);
    expect(out[0].bgeScore).toBe(0.8);
  });

  it("只被 FTS 命中时 bgeRank 为 0", () => {
    const out = fuseRankedRows([{ article_id: "a", rank: 1 }], [], 20);
    expect(out[0].bgeRank).toBe(0);
    expect(out[0].bgeScore).toBe(0);
  });

  it("结果按融合分降序", () => {
    const out = fuseRankedRows(
      [{ article_id: "a", rank: 1 }, { article_id: "b", rank: 10 }],
      [],
      20
    );
    expect(out[0].article_id).toBe("a");
  });

  it("截断到 topN", () => {
    const rows = Array.from({ length: 50 }, (_, i) => ({ article_id: `a${i}`, rank: i + 1 }));
    expect(fuseRankedRows(rows, [], 20)).toHaveLength(20);
  });

  it("空输入返回空数组", () => {
    expect(fuseRankedRows([], [], 20)).toEqual([]);
  });

  it("并集无重复", () => {
    const out = fuseRankedRows(
      [{ article_id: "a", rank: 1 }],
      [{ article_id: "a", rank: 2 }, { article_id: "b", rank: 1 }],
      20
    );
    expect(new Set(out.map((r) => r.article_id)).size).toBe(out.length);
  });
});

describe("常量", () => {
  it("RRF_K = 60 (原论文推荐值)", () => {
    expect(RRF_K).toBe(60);
  });

  it("TITLE_BOOST = 3.0 (标题命中是强信号)", () => {
    expect(TITLE_BOOST).toBe(3.0);
  });

  it("STOP_BIGRAMS 非空", () => {
    expect(STOP_BIGRAMS.size).toBeGreaterThan(0);
  });
});
