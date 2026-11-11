/**
 * ⑤ 法规监测 路由单测
 *
 * 覆盖:
 *   - 错误契约(400 invalid_request / 404 not_found)
 *   - **并发闸门** —— 一次抓取 20-40 秒,不能并发打政府网站
 *   - 只读端点在无数据时返回空数组而不是报错
 */

import { describe, it, expect, vi } from "vitest";
import { route } from "../router";
import type { Env } from "../../composition-root";

/** 造一个够用的 Env(只有监测用到的部分)。 */
function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    DB: {
      prepare: () => ({
        all: async () => ({ results: [] }),
        first: async () => null,
        bind: () => ({ all: async () => ({ results: [] }), first: async () => null }),
      }),
      batch: async () => [],
    },
    ...overrides,
  } as unknown as Env;
}

function req(path: string, method = "GET", body?: unknown): Request {
  return new Request(`http://local.test${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

describe("⑤ 路由 · 只读端点(无数据时返回空,不报错)", () => {
  it("GET /api/monitoring/releases → 空数组", async () => {
    const res = await route(req("/api/monitoring/releases"), makeEnv());
    expect(res.status).toBe(200);
    const body = (await res.json()) as { releases: unknown[]; count: number };
    expect(body.releases).toEqual([]);
    expect(body.count).toBe(0);
  });

  it("GET /api/monitoring/impact → 空 byAsset", async () => {
    const res = await route(req("/api/monitoring/impact"), makeEnv());
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      byAsset: Record<string, unknown>;
      totalImpacted: number;
      unknownCount: number;
    };
    expect(body.byAsset).toEqual({});
    expect(body.totalImpacted).toBe(0);
  });

  it("GET /api/monitoring/runs → 空数组", async () => {
    const res = await route(req("/api/monitoring/runs"), makeEnv());
    expect(res.status).toBe(200);
    expect(((await res.json()) as { runs: unknown[] }).runs).toEqual([]);
  });

  it("GET /api/monitoring/subscriptions → 空数组", async () => {
    const res = await route(req("/api/monitoring/subscriptions"), makeEnv());
    expect(res.status).toBe(200);
    expect(((await res.json()) as { subscriptions: unknown[] }).subscriptions).toEqual([]);
  });
});

describe("⑤ 路由 · 错误契约", () => {
  it("POST /api/monitoring/subscriptions 缺 assetType → 400 invalid_request", async () => {
    const res = await route(
      req("/api/monitoring/subscriptions", "POST", { label: "限量变更" }),
      makeEnv()
    );
    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string; message: string };
    expect(body.error).toBe("invalid_request");
    expect(body.message).toContain("assetType");
  });

  it("POST /api/monitoring/subscriptions 非法 assetType → 400", async () => {
    const res = await route(
      req("/api/monitoring/subscriptions", "POST", { assetType: "随便写", label: "x" }),
      makeEnv()
    );
    expect(res.status).toBe(400);
    expect(((await res.json()) as { error: string }).error).toBe("invalid_request");
  });

  it("POST /api/monitoring/subscriptions 缺 label → 400", async () => {
    const res = await route(
      req("/api/monitoring/subscriptions", "POST", { assetType: "limit_rules" }),
      makeEnv()
    );
    expect(res.status).toBe(400);
    expect(((await res.json()) as { message: string }).message).toContain("label");
  });

  it("DELETE /api/monitoring/subscriptions 缺 id → 400", async () => {
    const res = await route(req("/api/monitoring/subscriptions", "DELETE"), makeEnv());
    expect(res.status).toBe(400);
    expect(((await res.json()) as { message: string }).message).toContain("id");
  });

  it("未知路径 → 404 not_found", async () => {
    const res = await route(req("/api/monitoring/不存在"), makeEnv());
    expect(res.status).toBe(404);
    expect(((await res.json()) as { error: string }).error).toBe("not_found");
  });
});

describe("⑤ 路由 · 并发闸门(不能并发打政府网站)", () => {
  it("上一次抓取还在 running → 400 collect_in_progress,不发起新抓取", async () => {
    // 造一个「最新运行仍在 running」的仓储
    const runningRepo = {
      listRuns: async () => [
        {
          runId: "run_running",
          startedAt: "2026-11-11T00:00:00.000Z",
          finishedAt: null,
          status: "running" as const,
          pages: 1,
          found: 0,
          bodiesOk: 0,
          bodiesFail: 0,
          newCount: 0,
          revisedCount: 0,
          error: null,
        },
      ],
      listReleases: async () => [],
      getRelease: async () => null,
      upsertRelease: async () => {},
      upsertRun: async () => {},
      listSubscriptions: async () => [],
      upsertSubscription: async () => {},
      deleteSubscription: async () => {},
    };

    // 直接测 handler,避免 composition root 重建仓储
    const { handleCollect } = await import("./monitoring.routes");
    const app = { monitoringRepo: runningRepo } as never;
    const res = await handleCollect(app, req("/api/monitoring/collect", "POST", {}));

    expect(res.status).toBe(400);
    const body = (await res.json()) as { error: string; message: string };
    expect(body.error).toBe("collect_in_progress");
    expect(body.message).toContain("run_running");
  });
});
