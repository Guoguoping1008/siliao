/**
 * 合规仓储 · D1 绑定契约测试
 *
 * ## 为什么需要这份测试
 *
 * 2026-11-02 生产实测发现:`listRules()` 无版本时,SQL 里**没有 `?1` 占位符**,
 * 但代码照样 `.bind("")` → D1 报
 *
 *   `D1_ERROR: Wrong number of parameter bindings for SQL query.`
 *
 * ⚠️ **这个 bug 一直存在,只是从没被触发过** —— 建表之前先撞上
 * 「no such table: compliance_rules」,错误被更早的一层挡住了。
 * 建表 + 灌库做完,才第一次真正跑到这段代码。
 *
 * **教训**:「更早的失败」会掩盖「后面的失败」。上游依赖缺失时,
 * 下游的代码路径等于**从未被执行过** —— 补上依赖后必须重测。
 *
 * ## 契约
 *
 * **`.bind()` 的参数个数必须等于 SQL 里 `?N` 占位符的最大序号。**
 * 少 bind、多 bind、占位符编号不连续 —— 全部是运行时错误。
 */

import { describe, it, expect } from "vitest";
import { D1ComplianceRepository } from "./compliance.repository.impl";

/**
 * 模拟 D1 的绑定校验 —— 与真实 D1 行为一致:
 * 绑定的参数个数必须等于 SQL 中 `?N` 的最大序号。
 */
function mockDb(rows: Record<string, unknown>[] = []) {
  return {
    prepare(sql: string) {
      const stmt = {
        sql,
        bound: [] as unknown[],
        bind(...vals: unknown[]) {
          stmt.bound = vals;
          return stmt;
        },
        async all() {
          // —— 真实 D1 的校验 ——
          const maxN = Math.max(
            0,
            ...Array.from(sql.matchAll(/\?(\d+)/g)).map((m) => Number(m[1]))
          );
          if (stmt.bound.length !== maxN) {
            throw new Error(
              `Wrong number of parameter bindings for SQL query. ` +
                `bound=${stmt.bound.length}, placeholders=${maxN}`
            );
          }
          return { results: rows };
        },
        async first() {
          return rows[0] ?? null;
        },
      };
      return stmt;
    },
    async batch() {
      return [];
    },
  };
}

describe("D1ComplianceRepository · 绑定契约", () => {
  it("listRules() 无版本 → 不 bind(SQL 里没有占位符)", async () => {
    const repo = new D1ComplianceRepository(mockDb([]) as never);
    // 修前这里会抛「Wrong number of parameter bindings」
    await expect(repo.listRules()).resolves.toEqual([]);
  });

  it("listRules(版本) → bind 恰好 1 个", async () => {
    const repo = new D1ComplianceRepository(mockDb([]) as never);
    await expect(repo.listRules("v2026.10")).resolves.toEqual([]);
  });

  it("listReviewedRules() → 不 bind", async () => {
    const repo = new D1ComplianceRepository(mockDb([]) as never);
    await expect(repo.listReviewedRules()).resolves.toEqual([]);
  });

  it("listCatalog() → 不 bind", async () => {
    const repo = new D1ComplianceRepository(mockDb([]) as never);
    await expect(repo.listCatalog()).resolves.toEqual([]);
    await expect(repo.listCatalog(false)).resolves.toEqual([]);
  });

  it("listRuleSets() → 不 bind", async () => {
    const repo = new D1ComplianceRepository(mockDb([]) as never);
    await expect(repo.listRuleSets()).resolves.toEqual([]);
  });
});
