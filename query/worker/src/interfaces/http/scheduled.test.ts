/**
 * 定时抓取任务单测
 *
 * ⚠️ **不打外部网络** —— 注入假的仓储与用例,验证编排逻辑:
 *   - 并发闸门(上次还在 running 就跳过)
 *   - 影响面可判定才告警(算不出的不算「需要人看」)
 *   - 失败必须抛出(不吞异常,让 Workers 错误日志捕获到)
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { runScheduledMonitoring } from "./scheduled";
import type { Env } from "../composition-root";
import type {
  MonitoringRepository,
  MonitoringRun,
} from "../../application/monitoring/monitoring.repository";
import type { CollectReleasesUseCase } from "../../application/monitoring/monitoring.usecase";

/** 造一个可控的仓储。 */
function makeRepo(over: Partial<MonitoringRepository> = {}): MonitoringRepository {
  const base: MonitoringRepository = {
    listKnownReleases: async () => [],
    listReleases: async () => [],
    getRelease: async () => null,
    upsertRelease: async () => {},
    upsertRun: async () => {},
    listRuns: async () => [],
    listSubscriptions: async () => [],
    upsertSubscription: async () => {},
    deleteSubscription: async () => {},
  };
  return { ...base, ...over };
}

/** 造一个假的用例。 */
function makeCollect(over: Record<string, unknown> = {}): CollectReleasesUseCase {
  return {
    execute: async () => ({
      runId: "run_test",
      found: 0,
      newCount: 0,
      revisedCount: 0,
      bodiesOk: 0,
      bodiesFail: 0,
      impacted: [],
    }),
    ...over,
  } as unknown as CollectReleasesUseCase;
}

const env = { DB: {} } as unknown as Env;
const controller = {
  cron: "0 0 * * *",
  scheduledTime: Date.now(),
  noRetry: () => {},
} as unknown as ScheduledController;

afterEach(() => {
  vi.restoreAllMocks();
});

describe("⑤ 定时任务 · 并发闸门", () => {
  it("上一次抓取仍在 running → 跳过,不发起新抓取", async () => {
    const running: MonitoringRun = {
      runId: "run_running",
      startedAt: "2026-11-11T00:00:00.000Z",
      finishedAt: null,
      status: "running",
      pages: 1,
      found: 0,
      bodiesOk: 0,
      bodiesFail: 0,
      newCount: 0,
      revisedCount: 0,
      error: null,
    };
    const repo = makeRepo({ listRuns: async () => [running] });
    const execute = vi.fn();
    const collect = makeCollect({ execute });

    await runScheduledMonitoring(controller, env, {
      monitoringRepo: repo,
      monitoringCollect: collect,
    });

    expect(execute).not.toHaveBeenCalled();
  });

  it("上一次已结束 → 正常发起抓取", async () => {
    const done: MonitoringRun = {
      runId: "run_done",
      startedAt: "2026-11-11T00:00:00.000Z",
      finishedAt: "2026-11-11T00:00:30.000Z",
      status: "ok",
      pages: 1,
      found: 5,
      bodiesOk: 5,
      bodiesFail: 0,
      newCount: 5,
      revisedCount: 0,
      error: null,
    };
    const repo = makeRepo({ listRuns: async () => [done] });
    const execute = vi.fn(async () => ({
      runId: "run_new",
      found: 5,
      newCount: 5,
      revisedCount: 0,
      bodiesOk: 5,
      bodiesFail: 0,
      impacted: [],
    }));
    const collect = makeCollect({ execute });

    await runScheduledMonitoring(controller, env, {
      monitoringRepo: repo,
      monitoringCollect: collect,
    });

    expect(execute).toHaveBeenCalledTimes(1);
    // 抓取量克制:1 页 5 条正文
    expect(execute).toHaveBeenCalledWith({ pages: 1, maxBodies: 5 });
  });
});

describe("⑤ 定时任务 · 失败必须抛出(不吞异常)", () => {
  it("抓取抛错 → 异常向上传播(让 Workers 错误日志捕获到)", async () => {
    const repo = makeRepo();
    const collect = makeCollect({
      execute: async () => {
        throw new Error("D1 连不上");
      },
    });
    await expect(
      runScheduledMonitoring(controller, env, {
        monitoringRepo: repo,
        monitoringCollect: collect,
      })
    ).rejects.toThrow("D1 连不上");
  });
});

describe("⑤ 定时任务 · 影响面可判定才告警", () => {
  it("影响面为空 → 不打「需要关注」告警", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const repo = makeRepo();
    const collect = makeCollect({
      execute: async () => ({
        runId: "run_new",
        found: 10,
        newCount: 10,
        revisedCount: 0,
        bodiesOk: 5,
        bodiesFail: 0,
        impacted: [],
      }),
    });

    await runScheduledMonitoring(controller, env, {
      monitoringRepo: repo,
      monitoringCollect: collect,
    });

    const needAttention = warn.mock.calls.filter((c) =>
      String(c[0]).includes("需要关注")
    );
    expect(needAttention).toHaveLength(0);
  });

  it("影响面可判定 → 打「需要关注」告警,并带 URL 与受影响资产", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const repo = makeRepo();
    const collect = makeCollect({
      execute: async () => ({
        runId: "run_new",
        found: 10,
        newCount: 1,
        revisedCount: 0,
        bodiesOk: 5,
        bodiesFail: 0,
        impacted: [
          {
            releaseKey: "第1081号",
            title: "中华人民共和国农业农村部公告 第1081号",
            url: "https://www.agri.cn/zx/hxgg/202610/t20261030_8880383.htm",
            publishedAt: "2026-10-30",
            bodyExcerpt: null,
            bodyLength: 645,
            fingerprint: "b78be961",
            changeType: "new" as const,
            matchedKeywords: ["饲料添加剂品种目录"],
            affectedAssets: ["substance_catalog" as const],
            determinable: true,
            firstSeenAt: "2026-11-11T00:00:00.000Z",
            lastSeenAt: "2026-11-11T00:00:00.000Z",
          },
        ],
      }),
    });

    await runScheduledMonitoring(controller, env, {
      monitoringRepo: repo,
      monitoringCollect: collect,
    });

    const needAttention = warn.mock.calls.filter((c) =>
      String(c[0]).includes("需要关注")
    );
    expect(needAttention).toHaveLength(1);
    const msg = String(needAttention[0][0]);
    expect(msg).toContain("第1081号");
    expect(msg).toContain("substance_catalog");
    expect(msg).toContain("https://www.agri.cn/");
  });
});
