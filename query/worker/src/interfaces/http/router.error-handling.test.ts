/**
 * 路由层错误处理回归测试
 *
 * ## 为什么需要这份测试
 *
 * 2026-11-02 实测生产: `POST /api/compliance/usage` 与 `POST /api/qa/conversation`
 * 返回 **Cloudflare 1101(Worker threw exception)** —— 不是我们自己的 500 JSON。
 *
 * 根因是 `router.ts` 的 try/catch **捕获不到 async handler 抛出的错误**:
 *
 * ```ts
 * try {
 *   return handleComplianceUsage(app, req);   // ← 返回 Promise, 没有 await
 * } catch (e) {
 *   return errorJson("internal", ...);        // ← 永远走不到
 * }
 * ```
 *
 * `return promise` 时 try 块**已经正常返回**, catch 不会执行;
 * 错误变成 **unhandled rejection** → Workers 报 1101。
 *
 * ⚠️ 重构前(`index.ts` 单文件)是 `return json(await app.complianceCheck.check(...))` ——
 * **await 在 try 块内**, 所以错误能被捕获并返回 500 JSON。
 * M3 抽路由层时, `await` 留在了 handler 内部, try/catch 失去了作用。
 *
 * ## 契约
 *
 * 任何 handler 内部抛出的错误, 都必须变成 **500 + `{error,message}` JSON**,
 * 绝不能让它逃逸成 unhandled rejection。
 */

import { describe, it, expect } from "vitest";
import { route } from "./router";
import type { Env } from "../composition-root";

/** 造一个 D1 绑定: 任何查询都抛「表不存在」。 */
function dbThatFails(msg: string) {
  return {
    prepare() {
      const stmt = {
        bind() { return stmt; },
        async all() { throw new Error(msg); },
        async first() { throw new Error(msg); },
        async run() { throw new Error(msg); },
      };
      return stmt;
    },
    async batch() { throw new Error(msg); },
  };
}

function envWithFailingDb(msg: string): Env {
  return { DB: dbThatFails(msg) as never };
}

async function callRoute(
  env: Env,
  path: string,
  method = "GET",
  body?: unknown
): Promise<{ status: number; contentType: string; text: string }> {
  const req = new Request(`https://example.test${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const res = await route(req, env);
  return {
    status: res.status,
    contentType: res.headers.get("Content-Type") ?? "",
    text: await res.text(),
  };
}

describe("路由层 · 错误处理(不变量)", () => {
  it("GET /api/documents: D1 抛错 → 返回 500 JSON, 不是 unhandled rejection", async () => {
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: documents"),
      "/api/documents"
    );
    expect(res.status).toBe(500);
    expect(res.contentType).toContain("application/json");
    expect(res.text).toContain("no such table: documents");
  });

  it("GET /api/search: D1 全线失败 → 200 + 空命中(检索层**故意**降级)", async () => {
    // ⚠️ 这里与其它端点**故意不同** —— 检索层有多路降级
    //    (FTS5 → phrase → bigram → bge), 每一路各自 catch 住自己的错误,
    //    D1 全挂时返回**空命中**而不是 500。
    //    这是设计意图: 检索不可用 ≠ 整个服务不可用。
    //    (见 hybrid-retriever.adapter.ts 的 catch 分支)
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: articles"),
      "/api/search?q=维生素C"
    );
    expect(res.status).toBe(200);
    expect(res.contentType).toContain("application/json");
    expect(JSON.parse(res.text).hits).toEqual([]);
  });

  it("GET /api/entity/:name: D1 抛错 → 返回 500 JSON", async () => {
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: entities"),
      "/api/entity/%E5%86%9C%E4%B8%9A%E5%86%9C%E6%9D%91%E9%83%A8"
    );
    expect(res.status).toBe(500);
    expect(res.text).toContain("no such table: entities");
  });

  it("POST /api/compliance/usage: D1 抛错 → 返回 500 JSON(生产 1101 的场景)", async () => {
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: compliance_rules"),
      "/api/compliance/usage",
      "POST",
      { substance: "维生素C", species: "猪", value: 200, unit: "mg/kg" }
    );
    expect(res.status).toBe(500);
    expect(res.contentType).toContain("application/json");
    expect(res.text).toContain("no such table: compliance_rules");
  });

  it("POST /api/qa/conversation: D1 抛错 → 返回 500 JSON", async () => {
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: qa_sessions"),
      "/api/qa/conversation",
      "POST",
      { sessionId: "s1", q: "维生素C" }
    );
    expect(res.status).toBe(500);
    expect(res.text).toContain("no such table: qa_sessions");
  });

  it("DELETE /api/qa/conversation: D1 抛错 → 返回 500 JSON", async () => {
    const res = await callRoute(
      envWithFailingDb("D1_ERROR: no such table: qa_sessions"),
      "/api/qa/conversation?sessionId=s1",
      "DELETE"
    );
    expect(res.status).toBe(500);
    expect(res.text).toContain("no such table: qa_sessions");
  });

  it("未匹配路由仍返回 404 JSON(不被错误处理改动影响)", async () => {
    const res = await callRoute(envWithFailingDb("never"), "/api/nope");
    expect(res.status).toBe(404);
    expect(res.text).toContain("not_found");
  });
});
