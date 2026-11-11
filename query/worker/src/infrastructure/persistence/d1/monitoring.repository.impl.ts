/**
 * ⑤ 法规监测 —— D1 仓储实现
 *
 * 上下文: ⑤ 法规监测 Monitoring (支撑域)
 *
 * ⚠️ R1: 这是**唯一**允许直接查 `regulation_releases` /
 *    `monitoring_runs` / `subscriptions` 的地方。
 *
 * ⚠️ R4: 写入只经 `upsertRelease` / `recordRun` / `upsertSubscription`。
 *    **⑤ 不写 ① 的表** —— 新版本入库走 `RegulationReleaseDetected` 事件。
 */

import type { D1Like } from "./regulation.repository.impl";
import { mapRows, str, strOrNull, type DbRow } from "./mappers";
import type {
  ChangeType,
  ImpactAsset,
} from "../../../domain/monitoring/release-detector.service";
import type {
  MonitoringRepository,
  MonitoringRun,
  StoredRelease,
  Subscription,
} from "../../../application/monitoring/monitoring.repository";

export type {
  MonitoringRepository,
  MonitoringRun,
  StoredRelease,
  Subscription,
};

/** D1 实现的监测仓储。 */
export class D1MonitoringRepository implements MonitoringRepository {
  constructor(private readonly db: D1Like) {}

  async listKnownReleases(): Promise<{ releaseKey: string; fingerprint: string }[]> {
    const rows = await this.db
      .prepare(`SELECT release_key, fingerprint FROM regulation_releases`)
      .all();
    return (rows.results as DbRow[]).map((r) => ({
      releaseKey: str(r.release_key) ?? "",
      fingerprint: str(r.fingerprint) ?? "",
    }));
  }

  async listReleases(
    opts: { limit?: number; determinableOnly?: boolean } = {}
  ): Promise<StoredRelease[]> {
    const limit = Math.min(opts.limit ?? 50, 200);
    // ⚠️ 有条件才 bind —— D1 对「SQL 里没有占位符却 bind 了」会报
    //    「Wrong number of parameter bindings」(见 compliance 仓储的同款坑)。
    let sql = `SELECT * FROM regulation_releases`;
    if (opts.determinableOnly) {
      sql += ` WHERE determinable = 1`;
    }
    sql += ` ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT ?1`;
    const rows = await this.db.prepare(sql).bind(limit).all();
    return mapRows(rows.results as DbRow[], toRelease);
  }

  async getRelease(releaseKey: string): Promise<StoredRelease | null> {
    const rows = await this.db
      .prepare(`SELECT * FROM regulation_releases WHERE release_key = ?1`)
      .bind(releaseKey)
      .all();
    const list = mapRows(rows.results as DbRow[], toRelease);
    return list.length > 0 ? list[0] : null;
  }

  async upsertRelease(r: StoredRelease): Promise<void> {
    // ⚠️ **UPSERT 而不是 INSERT OR REPLACE** —— REPLACE 会删掉旧行再插新行,
    //    导致 first_seen_at 丢失。变更历史要靠 first_seen_at 保留。
    const stmt = this.db
      .prepare(
        `INSERT INTO regulation_releases (
           release_key, title, url, published_at, body_excerpt, body_length,
           fingerprint, change_type, matched_keywords, affected_assets,
           determinable, first_seen_at, last_seen_at, updated_at
         ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)
         ON CONFLICT(release_key) DO UPDATE SET
           title = excluded.title,
           url = excluded.url,
           published_at = excluded.published_at,
           body_excerpt = excluded.body_excerpt,
           body_length = excluded.body_length,
           fingerprint = excluded.fingerprint,
           change_type = excluded.change_type,
           matched_keywords = excluded.matched_keywords,
           affected_assets = excluded.affected_assets,
           determinable = excluded.determinable,
           last_seen_at = excluded.last_seen_at,
           updated_at = excluded.updated_at`
      )
      .bind(
        r.releaseKey,
        r.title,
        r.url,
        r.publishedAt,
        r.bodyExcerpt,
        r.bodyLength,
        r.fingerprint,
        r.changeType,
        JSON.stringify(r.matchedKeywords),
        JSON.stringify(r.affectedAssets),
        r.determinable ? 1 : 0,
        r.firstSeenAt,
        r.lastSeenAt,
        r.lastSeenAt
      );
    // ⚠️ 写操作走 `batch()` —— 本项目的 `D1Like` 只声明了
    //    all/first/batch,没有 run()。
    await this.db.batch([stmt]);
  }

  async upsertRun(r: MonitoringRun): Promise<void> {
    const stmt = this.db
      .prepare(
        `INSERT INTO monitoring_runs (
           run_id, started_at, finished_at, status, pages, found,
           bodies_ok, bodies_fail, new_count, revised_count, error
         ) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)
         ON CONFLICT(run_id) DO UPDATE SET
           finished_at = excluded.finished_at,
           status = excluded.status,
           pages = excluded.pages,
           found = excluded.found,
           bodies_ok = excluded.bodies_ok,
           bodies_fail = excluded.bodies_fail,
           new_count = excluded.new_count,
           revised_count = excluded.revised_count,
           error = excluded.error`
      )
      .bind(
        r.runId,
        r.startedAt,
        r.finishedAt,
        r.status,
        r.pages,
        r.found,
        r.bodiesOk,
        r.bodiesFail,
        r.newCount,
        r.revisedCount,
        r.error
      );
    await this.db.batch([stmt]);
  }

  async listRuns(limit = 20): Promise<MonitoringRun[]> {
    const rows = await this.db
      .prepare(`SELECT * FROM monitoring_runs ORDER BY started_at DESC LIMIT ?1`)
      .bind(Math.min(limit, 100))
      .all();
    return mapRows(rows.results as DbRow[], toRun);
  }

  async listSubscriptions(activeOnly = true): Promise<Subscription[]> {
    const sql = activeOnly
      ? `SELECT * FROM subscriptions WHERE active = 1 ORDER BY created_at DESC`
      : `SELECT * FROM subscriptions ORDER BY created_at DESC`;
    const rows = await this.db.prepare(sql).all();
    return mapRows(rows.results as DbRow[], toSubscription);
  }

  async upsertSubscription(s: Subscription): Promise<void> {
    const stmt = this.db
      .prepare(
        `INSERT INTO subscriptions (
           subscription_id, asset_type, label, created_at, last_notified_at, active
         ) VALUES (?1,?2,?3,?4,?5,?6)
         ON CONFLICT(subscription_id) DO UPDATE SET
           asset_type = excluded.asset_type,
           label = excluded.label,
           last_notified_at = excluded.last_notified_at,
           active = excluded.active`
      )
      .bind(
        s.subscriptionId,
        s.assetType,
        s.label,
        s.createdAt,
        s.lastNotifiedAt,
        s.active ? 1 : 0
      );
    await this.db.batch([stmt]);
  }

  async deleteSubscription(id: string): Promise<void> {
    await this.db.batch([
      this.db
        .prepare(`DELETE FROM subscriptions WHERE subscription_id = ?1`)
        .bind(id),
    ]);
  }
}

/* ---------- 行映射 ---------- */

function toRelease(r: DbRow): StoredRelease {
  return {
    releaseKey: str(r.release_key) ?? "",
    title: str(r.title) ?? "",
    url: str(r.url) ?? "",
    publishedAt: strOrNull(r.published_at),
    bodyExcerpt: strOrNull(r.body_excerpt),
    bodyLength: Number(r.body_length ?? 0),
    fingerprint: strOrNull(r.fingerprint),
    changeType: (str(r.change_type) || "new") as ChangeType,
    matchedKeywords: parseJsonArray(r.matched_keywords),
    affectedAssets: parseJsonArray(r.affected_assets) as ImpactAsset[],
    determinable: Number(r.determinable ?? 0) === 1,
    firstSeenAt: str(r.first_seen_at) ?? "",
    lastSeenAt: str(r.last_seen_at) ?? "",
  };
}

function toRun(r: DbRow): MonitoringRun {
  return {
    runId: str(r.run_id) ?? "",
    startedAt: str(r.started_at) ?? "",
    finishedAt: strOrNull(r.finished_at),
    status: (str(r.status) || "running") as MonitoringRun["status"],
    pages: Number(r.pages ?? 0),
    found: Number(r.found ?? 0),
    bodiesOk: Number(r.bodies_ok ?? 0),
    bodiesFail: Number(r.bodies_fail ?? 0),
    newCount: Number(r.new_count ?? 0),
    revisedCount: Number(r.revised_count ?? 0),
    error: strOrNull(r.error),
  };
}

function toSubscription(r: DbRow): Subscription {
  return {
    subscriptionId: str(r.subscription_id) ?? "",
    assetType: (str(r.asset_type) ?? "") as ImpactAsset,
    label: str(r.label) ?? "",
    createdAt: str(r.created_at) ?? "",
    lastNotifiedAt: strOrNull(r.last_notified_at),
    active: Number(r.active ?? 1) === 1,
  };
}

/** 解析 JSON 数组字段,坏了就返回空数组(不抛 —— 一个坏字段不该毁掉整批数据)。 */
function parseJsonArray(v: unknown): string[] {
  if (typeof v !== "string" || !v) return [];
  try {
    const parsed = JSON.parse(v);
    return Array.isArray(parsed) ? parsed.map((x) => String(x)) : [];
  } catch {
    return [];
  }
}
