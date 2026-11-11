/**
 * ⑤ 法规监测 —— 仓储接口(依赖倒置)
 *
 * 上下文: ⑤ 法规监测 Monitoring (支撑域)
 *
 * ## 为什么接口在 application 层
 *
 * ADR-004 的分层规则:**application 不得 import infrastructure**。
 * 所以仓储接口不能放在 `infrastructure/persistence/d1/`(那样 application
 * 一 import 就违规),必须放在 application 层 —— 由 composition root
 * 把 D1 实现注入进来。
 *
 * 这与现有 ② 合规规则的做法不同(那边仓储接口在 infrastructure 里,
 * application 用 `ComplianceRuleSource` 这个**窄接口**解耦)。
 * 两种做法都符合依赖倒置,这里选「接口直接在 application 层」——
 * ⑤ 的仓储接口就是 application 用例需要的全部能力,不需要再包一层。
 */

import type {
  ChangeType,
  ImpactAsset,
} from "../../domain/monitoring/release-detector.service";

/** 仓储里的发布记录。 */
export interface StoredRelease {
  releaseKey: string;
  title: string;
  url: string;
  publishedAt: string | null;
  bodyExcerpt: string | null;
  bodyLength: number;
  fingerprint: string | null;
  changeType: ChangeType;
  matchedKeywords: string[];
  affectedAssets: ImpactAsset[];
  determinable: boolean;
  firstSeenAt: string;
  lastSeenAt: string;
}

/** 一次抓取运行。 */
export interface MonitoringRun {
  runId: string;
  startedAt: string;
  finishedAt: string | null;
  status: "running" | "ok" | "failed";
  pages: number;
  found: number;
  bodiesOk: number;
  bodiesFail: number;
  newCount: number;
  revisedCount: number;
  error: string | null;
}

/** 订阅。 */
export interface Subscription {
  subscriptionId: string;
  assetType: ImpactAsset;
  label: string;
  createdAt: string;
  lastNotifiedAt: string | null;
  active: boolean;
}

/** ⑤ 监测仓储接口。 */
export interface MonitoringRepository {
  /** 列出已知发布(用于判重)。 */
  listKnownReleases(): Promise<{ releaseKey: string; fingerprint: string }[]>;
  /** 列出发布,按发布时间倒序。 */
  listReleases(opts?: { limit?: number; determinableOnly?: boolean }): Promise<StoredRelease[]>;
  /** 取单个发布。 */
  getRelease(releaseKey: string): Promise<StoredRelease | null>;
  /** 写入/更新发布。 */
  upsertRelease(r: StoredRelease): Promise<void>;
  /** 记一次运行。 */
  upsertRun(r: MonitoringRun): Promise<void>;
  /** 取最近 N 次运行。 */
  listRuns(limit?: number): Promise<MonitoringRun[]>;
  /** 订阅 CRUD。 */
  listSubscriptions(activeOnly?: boolean): Promise<Subscription[]>;
  upsertSubscription(s: Subscription): Promise<void>;
  deleteSubscription(id: string): Promise<void>;
}
