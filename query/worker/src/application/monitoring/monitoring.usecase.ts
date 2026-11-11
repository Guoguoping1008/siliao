/**
 * ⑤ 法规监测 —— 应用层用例(编排)
 *
 * 上下文: ⑤ 法规监测 Monitoring (支撑域)
 *
 * ## 职责边界
 *
 * 这里是**编排**,不写业务规则:
 * - 业务规则(变更判定、影响面推断)在 `domain/monitoring/release-detector.service.ts`
 * - 外部交互(抓政府网站)在 `interfaces/acl/moa-source.acl.ts`
 * - 持久化在 `infrastructure/persistence/d1/monitoring.repository.impl.ts`
 *
 * ## ⚠️ 两条不变量(ADR-004 / ADR-006)
 *
 * 1. **不自动改数据** —— 只产出影响报告 + 事件,由人工校核决定是否更新规则。
 *    理由:② 合规规则有「未审核不参与判定」的闸门,自动改会绕过它。
 * 2. **爬虫失败必须告警而非静默** —— 失败会写 `monitoring_runs` 且抛出去。
 */

import {
  classifyChange,
  fingerprint,
  inferImpactScope,
  releaseKeyOf,
  type Release,
} from "../../domain/monitoring/release-detector.service";
import type {
  MonitoringRepository,
  StoredRelease,
  MonitoringRun,
} from "./monitoring.repository";

/** 抓取源(由 ACL 层注入,本层不直接 fetch)。 */
export interface ReleaseSource {
  fetchReleases(pages: number, maxItems: number): Promise<Release[]>;
}

/** 事件派发器(由 composition root 注入)。 */
export type EventDispatcher = (event: {
  name: string;
  occurredAt: string;
  payload: unknown;
}) => void | Promise<void>;

/** 抓取参数。 */
export interface CollectOptions {
  /** 抓几页 */
  pages?: number;
  /** 最多抓多少条正文(0 = 只要列表) */
  maxBodies?: number;
  /** 正文最长保留字数 */
  excerptLimit?: number;
}

/** 抓取结果。 */
export interface CollectResult {
  runId: string;
  found: number;
  newCount: number;
  revisedCount: number;
  bodiesOk: number;
  bodiesFail: number;
  /** 本次新发现或被修订、且影响面可判定的发布 */
  impacted: StoredRelease[];
}

/** 监测用例。 */
export class CollectReleasesUseCase {
  constructor(
    private readonly repo: MonitoringRepository,
    private readonly source: ReleaseSource,
    private readonly dispatch?: EventDispatcher
  ) {}

  async execute(opts: CollectOptions = {}): Promise<CollectResult> {
    const pages = opts.pages ?? 1;
    const maxBodies = opts.maxBodies ?? 20;
    const excerptLimit = opts.excerptLimit ?? 2000;

    const startedAt = new Date().toISOString();
    const runId = `run_${startedAt.replace(/[-:.TZ]/g, "").slice(0, 14)}`;

    const run: MonitoringRun = {
      runId,
      startedAt,
      finishedAt: null,
      status: "running",
      pages,
      found: 0,
      bodiesOk: 0,
      bodiesFail: 0,
      newCount: 0,
      revisedCount: 0,
      error: null,
    };
    await this.repo.upsertRun(run);

    let releases: Release[];
    try {
      releases = await this.source.fetchReleases(pages, maxBodies);
    } catch (e) {
      // ⚠️ **爬虫失败必须告警而非静默** —— 记录 + 抛出去。
      const msg = e instanceof Error ? e.message : String(e);
      await this.repo.upsertRun({
        ...run,
        finishedAt: new Date().toISOString(),
        status: "failed",
        error: msg,
      });
      console.error(`[monitoring] 抓取失败 run=${runId}: ${msg}`);
      throw e;
    }

    run.found = releases.length;
    const known = await this.repo.listKnownReleases();
    const knownMap = new Map(known.map((k) => [k.releaseKey, k.fingerprint]));

    const impacted: StoredRelease[] = [];
    let newCount = 0;
    let revisedCount = 0;

    for (const rel of releases) {
      const key = releaseKeyOf(rel);
      const body = rel.body ?? "";
      const scope = inferImpactScope({ ...rel, releaseKey: key });
      const fp = fingerprint(body);
      const changeType = classifyChange(
        { ...rel, releaseKey: key },
        known.map((k) => ({ releaseKey: k.releaseKey, fingerprint: k.fingerprint }))
      );

      if (body.length > 0) run.bodiesOk++;
      else run.bodiesFail++;

      if (changeType === "new") newCount++;
      if (changeType === "revised") revisedCount++;

      const prev = knownMap.get(key);
      const stored: StoredRelease = {
        releaseKey: key,
        title: rel.title,
        url: rel.url,
        publishedAt: rel.publishedAt,
        bodyExcerpt: body ? body.slice(0, excerptLimit) : null,
        bodyLength: body.length,
        fingerprint: fp || null,
        changeType,
        matchedKeywords: scope.matchedKeywords,
        affectedAssets: scope.affectedAssets,
        determinable: scope.determinable,
        firstSeenAt: prev ? (await this.repo.getRelease(key))?.firstSeenAt ?? startedAt : startedAt,
        lastSeenAt: new Date().toISOString(),
      };
      await this.repo.upsertRelease(stored);

      // ⚠️ **只有影响面可判定的才进 impacted** —— ADR-004 不变量:
      //    算不出影响面的发布**不推送给用户**。
      if (scope.determinable && (changeType === "new" || changeType === "revised")) {
        impacted.push(stored);
      }
    }

    const finishedAt = new Date().toISOString();
    await this.repo.upsertRun({
      ...run,
      finishedAt,
      status: "ok",
      newCount,
      revisedCount,
    });

    // ⚠️ **只对「影响面可判定」的发布发事件** —— 事件消费者据此决定是否要人介入。
    for (const r of impacted) {
      if (!this.dispatch) continue;
      await this.dispatch({
        name: "RegulationReleaseDetected",
        occurredAt: finishedAt,
        payload: {
          releaseKey: r.releaseKey,
          title: r.title,
          url: r.url,
          publishedAt: r.publishedAt,
          changeType: r.changeType,
          affectedAssets: r.affectedAssets,
          matchedKeywords: r.matchedKeywords,
        },
      });
    }

    if (newCount > 0 || revisedCount > 0) {
      console.log(
        `[monitoring] run=${runId} found=${run.found} new=${newCount} revised=${revisedCount} ` +
          `impacted=${impacted.length}`
      );
    }

    return {
      runId,
      found: run.found,
      newCount,
      revisedCount,
      bodiesOk: run.bodiesOk,
      bodiesFail: run.bodiesFail,
      impacted,
    };
  }
}

/**
 * 影响面报告 —— 汇总「哪些发布影响了哪些资产」。
 *
 * ⚠️ 只统计 `determinable=1` 的发布 —— 算不出影响面的不参与汇总
 *    (否则报告里会混进一堆「不知道影响什么」,降低信噪比)。
 */
export interface ImpactReport {
  /** 按资产分组 */
  byAsset: Record<string, StoredRelease[]>;
  /** 需要人看的发布总数 */
  totalImpacted: number;
  /** 影响面未知的发布数(不推送,但可查) */
  unknownCount: number;
}

export class BuildImpactReportUseCase {
  constructor(private readonly repo: MonitoringRepository) {}

  async execute(limit = 50): Promise<ImpactReport> {
    const all = await this.repo.listReleases({ limit: Math.min(limit, 200) });
    const byAsset: Record<string, StoredRelease[]> = {};
    let totalImpacted = 0;
    let unknownCount = 0;

    for (const r of all) {
      if (!r.determinable) {
        unknownCount++;
        continue;
      }
      totalImpacted++;
      for (const a of r.affectedAssets) {
        (byAsset[a] ??= []).push(r);
      }
    }

    return { byAsset, totalImpacted, unknownCount };
  }
}
