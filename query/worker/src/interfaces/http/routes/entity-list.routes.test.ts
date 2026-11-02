/**
 * ④ 图谱 —— 实体列表端点 `/api/entities`
 *
 * ## 为什么需要这份测试
 *
 * 2026-11-03 实测:图谱灌完 481 个实体后,前端**没有任何入口**能列出它们 ——
 * 顶栏「实体」硬编码跳 `/entity/农业农村部`,而那个实体**根本不存在**
 * (生产实测 `entities` 表 name='农业农村部' 命中 0 条)。
 * 于是加了 `/api/entities` 列表端点 + 前端列表页。
 *
 * ## 契约
 *
 * 1. **`/api/entities` 必须排在 `/api/entity/:name` 之后** ——
 *    否则 "entities" 会被当成实体名去查,永远 404。
 * 2. **limit 必须封顶 200** —— 否则一个不带 limit 的请求能把 481 行全拉走。
 * 3. **参数非法要归一化,不能 500** —— `limit=abc` → 50,`limit=-1` → 1。
 * 4. **D1 抛错要变成 500 JSON** —— 不能逃逸成 unhandled rejection
 *    (Cloudflare 1101)。
 */

import { describe, it, expect } from "vitest";
import { route } from "../router";
import type { Env } from "../../composition-root";

/** 可编程的 D1 桩。 */
function stubDb(opts: {
  rows?: Record<string, unknown>[];
  fail?: string;
}) {
  return {
    prepare(sql: string) {
      const stmt = {
        bind() { return stmt; },
        async all() {
          if (opts.fail) throw new Error(opts.fail);
          return { results: opts.rows ?? [] };
        },
        async first() {
          if (opts.fail) throw new Error(opts.fail);
          return opts.rows?.[0] ?? null;
        },
        async run() { return { success: true }; },
      };
      return stmt;
    },
    async batch() { return []; },
  };
}

function envWith(db: unknown): Env {
  return { DB: db as never };
}

async function call(path: string, env: Env) {
  const req = new Request(`https://example.test${path}`);
  const res = await route(req, env);
  return { status: res.status, text: await res.text() };
}

const ENTITY_ROW = {
  entity_id: "sub_abc123",
  name: "L-抗坏血酸(维生素C)",
  type: "SUBSTANCE",
  description: "养殖动物",
  doc_id: "doc1",
};

describe("GET /api/entities", () => {
  it("返回实体列表 + count", async () => {
    const res = await call("/api/entities", envWith(stubDb({ rows: [ENTITY_ROW] })));
    expect(res.status).toBe(200);
    const body = JSON.parse(res.text);
    expect(body.entities).toHaveLength(1);
    expect(body.entities[0].name).toBe("L-抗坏血酸(维生素C)");
    expect(body.count).toBe(1);
  });

  it("⚠️ `/api/entities` 不能被 `/api/entity/:name` 抢走", async () => {
    // 如果路由顺序错了,这里会走到 findEntityByName("entities") → entity_not_found
    const res = await call("/api/entities", envWith(stubDb({ rows: [ENTITY_ROW] })));
    const body = JSON.parse(res.text);
    expect(body.error).toBeUndefined();
    expect(body.entities).toBeDefined();
  });

  it("limit 非法 → 归一化成 50,不 500", async () => {
    for (const q of ["limit=abc", "limit=-5", "limit=0", "limit=999999"]) {
      const res = await call(`/api/entities?${q}`, envWith(stubDb({ rows: [] })));
      expect(res.status).toBe(200);
      const body = JSON.parse(res.text);
      expect(body.limit).toBeGreaterThan(0);
      expect(body.limit).toBeLessThanOrEqual(200);
    }
  });

  it("limit 上限是 200", async () => {
    const res = await call("/api/entities?limit=999999", envWith(stubDb({ rows: [] })));
    expect(JSON.parse(res.text).limit).toBe(200);
  });

  it("offset 非法 → 归一化成 0", async () => {
    const res = await call("/api/entities?offset=-3", envWith(stubDb({ rows: [] })));
    expect(JSON.parse(res.text).offset).toBe(0);
  });

  it("D1 抛错 → 500 JSON(不是 unhandled rejection)", async () => {
    const res = await call(
      "/api/entities",
      envWith(stubDb({ fail: "D1_ERROR: no such table: entities" }))
    );
    expect(res.status).toBe(500);
    expect(res.text).toContain("no such table: entities");
  });

  it("实体行 description 为 null → 归一化成空串,不能是 undefined", async () => {
    const res = await call(
      "/api/entities",
      envWith(stubDb({ rows: [{ ...ENTITY_ROW, description: null }] }))
    );
    const body = JSON.parse(res.text);
    expect(body.entities[0].description).toBe("");
    expect(body.entities[0].description).not.toBeUndefined();
  });
});
