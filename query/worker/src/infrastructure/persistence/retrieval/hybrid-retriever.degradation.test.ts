/**
 * bge 降级可观测性测试 —— 2026-11-09 新增。
 *
 * 背景:2026-11-08 13:17 bge 主机重启 → Docker 没自启 → 容器没起来 →
 * 生产静默退化成纯 FTS5 近 20 小时,期间**零告警**。
 * 本测试锁死「降级必须看得见」这条不变量。
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { HybridRetriever } from "./hybrid-retriever.adapter";

const ROW = (row: { article_id: string }) => ({ article_id: row.article_id, rank: 1 });

function fakeDb(rows: { article_id: string }[] = [{ article_id: "a1" }]) {
  return {
    prepare: (q: string) => ({
      bind: () => ({
        all: async () => ({ results: rows.map(ROW) }),
        first: async () => null,
        run: async () => ({ success: true }),
      }),
      all: async () => ({ results: rows.map(ROW) }),
      first: async () => null,
      run: async () => ({ success: true }),
    }),
    batch: async () => [],
  } as never;
}

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("HybridRetriever · bge 降级可观测性", () => {
  it("bge 正常 → degraded 为 false", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ hits: [{ article_id: "b1", score: 0.9 }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    ) as never;

    const r = new HybridRetriever(fakeDb(), { BGE_SERVER_URL: "https://bge.test" });
    const out = await r.search({ q: "维生素C" });

    expect(out.degraded).toBe(false);
  });

  it("bge 挂掉 → degraded 为 true(不是静默降级)", async () => {
    globalThis.fetch = vi.fn(async () => new Response("bad gateway", { status: 502 })) as never;

    const r = new HybridRetriever(fakeDb(), { BGE_SERVER_URL: "https://bge.test" });
    const out = await r.search({ q: "维生素C" });

    expect(out.degraded).toBe(true);
    // 降级时仍要有 FTS5 的结果 —— 不能因为 bge 挂了就整个检索失败
    expect(out.hits.length).toBeGreaterThan(0);
  });

  it("bge 连续失败达阈值 → 打 console.error(供外部监控按 error 级抓取)", async () => {
    globalThis.fetch = vi.fn(async () => new Response("bad gateway", { status: 502 })) as never;
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const r = new HybridRetriever(fakeDb(), { BGE_SERVER_URL: "https://bge.test" });
    // 连续 3 次
    await r.search({ q: "维生素C" });
    await r.search({ q: "维生素C" });
    await r.search({ q: "维生素C" });

    expect(errSpy).toHaveBeenCalled();
    const msg = String(errSpy.mock.calls[0]?.[0] ?? "");
    expect(msg).toContain("DEGRADED");
  });

  it("bge 恢复 → 计数清零,不再报错", async () => {
    let fail = true;
    globalThis.fetch = vi.fn(async () => {
      if (fail) return new Response("bad gateway", { status: 502 });
      return new Response(JSON.stringify({ hits: [{ article_id: "b1", score: 0.9 }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as never;
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const r = new HybridRetriever(fakeDb(), { BGE_SERVER_URL: "https://bge.test" });
    await r.search({ q: "维生素C" });
    await r.search({ q: "维生素C" });
    await r.search({ q: "维生素C" });
    expect(errSpy).toHaveBeenCalled();

    fail = false;
    const ok = await r.search({ q: "维生素C" });
    expect(ok.degraded).toBe(false);

    // 恢复后再失败一次 → 计数从 1 开始,不该立刻再打 error
    errSpy.mockClear();
    fail = true;
    await r.search({ q: "维生素C" });
    expect(errSpy).not.toHaveBeenCalled();
  });

  it("未配置 BGE_SERVER_URL → degraded 为 false(没配不算降级)", async () => {
    const r = new HybridRetriever(fakeDb(), { BGE_SERVER_URL: "" });
    const out = await r.search({ q: "维生素C" });
    expect(out.degraded).toBe(false);
  });
});
