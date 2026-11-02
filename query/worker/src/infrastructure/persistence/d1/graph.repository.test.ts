/**
 * 图谱仓储 · 响应契约测试
 *
 * ## 为什么需要这份测试
 *
 * 2026-11-02 实测:灌了 `entity_articles` 之后,生产 `/entity/:name` 页面
 * **整页崩成错误边界**。两个真 bug:
 *
 * 1. **`doc_id` 没返回** —— 前端 `EntityGraph` 用它拼
 *    `/doc/${a.doc_id}/chapter/${a.chapter_id}`,缺了就跳 `/doc/undefined`。
 * 2. **`number` 是 undefined** —— 前端直接 `a.number.replace(/第|条/g, "")`,
 *    遇 undefined 抛 TypeError,整个实体页白屏。
 *
 * ⚠️ **这两个 bug 一直存在,只是从没被触发过** —— `entity_articles` 是空表,
 * `articles` 数组永远是空的,渲染分支根本没执行过。
 * 这跟「listRules 多 bind 参数」是同一类问题:
 * **上游数据缺失 → 下游代码路径等于从未被执行。**
 *
 * ## 契约
 *
 * - `doc_id` 必须返回(前端拼链接要用)
 * - `number` 必须是 **string**(可以是空串,不能是 undefined)
 */

import { describe, it, expect } from "vitest";
import { D1GraphRepository } from "./graph.repository.impl";

/** 模拟 D1:返回指定的行,并**原样保留 null/undefined**。 */
function mockDb(rows: Record<string, unknown>[]) {
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

describe("D1GraphRepository · 响应契约", () => {
  it("listEntityArticles → 必须返回 doc_id(前端拼链接要用)", async () => {
    const repo = new D1GraphRepository(
      mockDb([
        {
          article_id: "doc1__a039",
          number: "第三十八条",
          title: "第三十八条",
          chapter_id: "doc1@@第四章",
          chapter_number: "第四章",
          chapter_title: "法律责任",
          doc_id: "doc1",
        },
      ]) as never
    );
    const refs = await repo.listEntityArticles("e1");
    expect(refs).toHaveLength(1);
    expect(refs[0].doc_id).toBe("doc1");
  });

  it("listEntityArticles → number 为 null 时必须是空串,不能是 undefined", async () => {
    // ⚠️ 非「第X条」型条文(如申报指南的「（二）混合型饲料添加剂生产许可申请书」)
    //    number 在库里就是空/null —— 前端 `a.number.replace()` 遇 undefined 会崩
    const repo = new D1GraphRepository(
      mockDb([
        {
          article_id: "doc2__a018",
          number: null,
          title: "（二）混合型饲料添加剂生产许可申请书",
          chapter_id: "doc2@@第二章",
          chapter_number: "第二章",
          chapter_title: "申报要求",
          doc_id: "doc2",
        },
      ]) as never
    );
    const refs = await repo.listEntityArticles("e1");
    expect(refs).toHaveLength(1);
    const first = refs[0]!;
    expect(first.number).toBe("");
    expect(first.number).not.toBeUndefined();
    // 前端会这么用 —— 不能抛
    expect(() => first.number.replace(/第|条/g, "")).not.toThrow();
  });

  it("listEntityArticles → 每条都必须带 number 字段(键存在)", async () => {
    const repo = new D1GraphRepository(
      mockDb([
        { article_id: "a1", number: null, title: "t", chapter_id: "c1", doc_id: "d1" },
        { article_id: "a2", number: "第一条", title: "t", chapter_id: "c1", doc_id: "d1" },
      ]) as never
    );
    const refs = await repo.listEntityArticles("e1");
    for (const r of refs) {
      expect("number" in r).toBe(true);
      expect(typeof r.number).toBe("string");
    }
  });

  it("findEntityByName → 查不到返回 null", async () => {
    const repo = new D1GraphRepository(mockDb([]) as never);
    await expect(repo.findEntityByName("不存在")).resolves.toBeNull();
  });
});
