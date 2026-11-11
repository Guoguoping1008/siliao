/**
 * ⑤ 法规监测 路由 —— 接口层
 *
 * 上下文: ⑤ 法规监测 Monitoring (支撑域)
 *
 * 路由:
 *   GET    /api/monitoring/releases        已抓到的发布列表
 *   GET    /api/monitoring/impact          影响面报告(按资产分组)
 *   GET    /api/monitoring/runs            抓取运行记录(看爬虫是否健康)
 *   POST   /api/monitoring/collect         手动触发一次抓取
 *   GET    /api/monitoring/subscriptions   订阅列表
 *   POST   /api/monitoring/subscriptions   新增订阅
 *   DELETE /api/monitoring/subscriptions   删订阅
 *
 * ⚠️ **`/collect` 会打外部政府网站** —— 所以要限流保护:
 *    一次抓取约 20-40 秒(正文串行抓),并发打会压垮对方站点。
 *    这里限制「同时最多一个抓取在跑」,用 D1 的运行记录做闸门。
 */

import { json, errorJson } from "../http-utils";
import type { AppDependencies } from "../../composition-root";
import type { ImpactAsset } from "../../../domain/monitoring/release-detector.service";

/** GET /api/monitoring/releases */
export async function handleListReleases(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") ?? 50);
  const determinableOnly = url.searchParams.get("determinableOnly") === "1";
  const releases = await app.monitoringRepo.listReleases({ limit, determinableOnly });
  return json({ releases, count: releases.length });
}

/** GET /api/monitoring/impact */
export async function handleImpactReport(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") ?? 50);
  const report = await app.monitoringImpact.execute(limit);
  return json(report);
}

/** GET /api/monitoring/runs */
export async function handleListRuns(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const url = new URL(req.url);
  const limit = Number(url.searchParams.get("limit") ?? 20);
  const runs = await app.monitoringRepo.listRuns(limit);
  return json({ runs, count: runs.length });
}

/** POST /api/monitoring/collect */
export async function handleCollect(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const body = await req
    .json<{ pages?: number; maxBodies?: number }>()
    .catch(() => ({}) as { pages?: number; maxBodies?: number });

  // ⚠️ **并发闸门** —— 一次抓取 20-40 秒,不能并发打政府网站。
  //    最新一次运行还在 running 就拒绝。
  const runs = await app.monitoringRepo.listRuns(1);
  const latest = runs[0];
  if (latest && latest.status === "running") {
    return errorJson(
      "collect_in_progress",
      `上一次抓取还在运行(run=${latest.runId}, 开始于 ${latest.startedAt})。请稍后再试。`
    );
  }

  const result = await app.monitoringCollect.execute({
    pages: Math.min(Math.max(body.pages ?? 1, 1), 5),
    maxBodies: Math.min(Math.max(body.maxBodies ?? 20, 0), 50),
  });
  return json(result);
}

/** GET /api/monitoring/subscriptions */
export async function handleListSubscriptions(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const subs = await app.monitoringRepo.listSubscriptions(true);
  return json({ subscriptions: subs, count: subs.length });
}

/** POST /api/monitoring/subscriptions */
export async function handleCreateSubscription(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const body = await req.json<{ assetType?: string; label?: string }>();
  const assetType = (body.assetType ?? "").trim();
  const label = (body.label ?? "").trim();

  const VALID: ImpactAsset[] = [
    "limit_rules",
    "substance_catalog",
    "prohibition_rules",
    "label_rules",
    "species_scope",
  ];
  if (!VALID.includes(assetType as ImpactAsset)) {
    return errorJson(
      "invalid_request",
      `assetType 必须是以下之一: ${VALID.join(", ")}`
    );
  }
  if (!label) {
    return errorJson("invalid_request", "缺少 label(订阅名)");
  }

  const now = new Date().toISOString();
  const id = `sub_${assetType}_${label}`.replace(/\s+/g, "_");
  await app.monitoringRepo.upsertSubscription({
    subscriptionId: id,
    assetType: assetType as ImpactAsset,
    label,
    createdAt: now,
    lastNotifiedAt: null,
    active: true,
  });
  return json({ ok: true, subscriptionId: id });
}

/** DELETE /api/monitoring/subscriptions?id=xxx */
export async function handleDeleteSubscription(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const url = new URL(req.url);
  const id = url.searchParams.get("id") ?? "";
  if (!id) {
    return errorJson("invalid_request", "缺少 id 查询参数");
  }
  await app.monitoringRepo.deleteSubscription(id);
  return json({ ok: true, subscriptionId: id });
}
