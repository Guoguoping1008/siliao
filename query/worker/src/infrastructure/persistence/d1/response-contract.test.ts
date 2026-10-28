/**
 * 响应契约回归测试
 *
 * ## 为什么需要这份测试
 *
 * ADR-004 M1 重构后, 拿生产 API 响应做前后比对, 抓到了两个**所有本地测试
 * 都漏掉**的回归:
 *
 *   1. `chapter_number` 从 `""` 变成 `null` —— 映射层用了 `String(x)`,
 *      把 D1 的 null 变成了字符串 "null"
 *   2. `is_toc` 字段凭空多出来 —— 映射层多映射了一列
 *
 * 两者都**逃过了**: 类型系统不报错、单测不失败、eval 门禁照样绿
 * (eval 是 Python 复刻, e2e 走 mock 模式, 都不碰真实 Worker 的映射层)。
 *
 * **只有拿生产响应的实际 JSON 做基线比对才抓到。**
 *
 * 这份测试把「响应字段集合」锁死 —— 以后再动映射层, 字段增删会立即变红。
 */

import { describe, it, expect } from "vitest";
import { strOrNull, str, int, mapRows, type DbRow } from "../d1/mappers";
import { D1RegulationRepository } from "../d1/regulation.repository.impl";

/** 模拟 D1 的 prepare/bind。 */
function mockDb(rows: DbRow[]) {
  return {
    prepare() {
      const stmt = {
        bind() { return stmt; },
        async all() { return { results: rows }; },
        async first() { return rows[0] ?? null; },
      };
      return stmt;
    },
    async batch() { return []; },
  };
}

describe("D1 响应契约 · /api/documents", () => {
  const row: DbRow = {
    doc_id: "d1",
    title: "饲料和饲料添加剂管理条例",
    doc_number: "国务院令2011年第609号",
    issuer: "01法规",
    effective_date: null,
    chapter_count: 6,
    article_count: 52,
  };

  it("返回字段集合与原实现完全一致(不多不少)", async () => {
    const repo = new D1RegulationRepository(mockDb([row]) as never);
    const docs = await repo.listDocuments();
    // ⚠️ 原实现的 SELECT 只有这几列 —— is_toc **不在其中**
    expect(Object.keys(docs[0]).sort()).toEqual([
      "article_count",
      "chapter_count",
      "doc_id",
      "doc_number",
      "effective_date",
      "issuer",
      "title",
    ]);
  });

  it("null 字段保持 null(不被转成 'null' 字符串)", async () => {
    const repo = new D1RegulationRepository(mockDb([row]) as never);
    const docs = await repo.listDocuments();
    expect(docs[0].effective_date).toBeNull();
    expect(docs[0].effective_date).not.toBe("null");
  });

  it("JSON 序列化后 null 仍是 null", async () => {
    const repo = new D1RegulationRepository(mockDb([row]) as never);
    const docs = await repo.listDocuments();
    const parsed = JSON.parse(JSON.stringify(docs));
    expect(parsed[0].effective_date).toBeNull();
  });

  it("计数是数字不是字符串", async () => {
    const repo = new D1RegulationRepository(mockDb([row]) as never);
    const docs = await repo.listDocuments();
    expect(typeof docs[0].article_count).toBe("number");
    expect(docs[0].article_count).toBe(52);
  });
});

describe("映射辅助函数", () => {
  it("strOrNull: null → null", () => {
    expect(strOrNull(null)).toBeNull();
  });

  it("strOrNull: undefined → null", () => {
    expect(strOrNull(undefined)).toBeNull();
  });

  it("strOrNull: 字符串 → 原样", () => {
    expect(strOrNull("abc")).toBe("abc");
  });

  it("strOrNull: 数字 → 字符串", () => {
    expect(strOrNull(123)).toBe("123");
  });

  it("str: null → undefined(键会消失)", () => {
    expect(str(null)).toBeUndefined();
  });

  it("int: null → fallback", () => {
    expect(int(null, 7)).toBe(7);
  });

  it("int: 数字字符串 → 数字", () => {
    expect(int("42")).toBe(42);
  });

  it("mapRows: undefined → 空数组", () => {
    expect(mapRows(undefined, (r) => r)).toEqual([]);
  });

  it("mapRows: 逐行映射", () => {
    expect(mapRows([{ a: 1 }, { a: 2 }], (r) => r.a)).toEqual([1, 2]);
  });
});
