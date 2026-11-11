/**
 * Cron 定时任务 —— ⑤ 法规监测的自动抓取
 *
 * 上下文: ⑤ 法规监测 Monitoring
 *
 * ## 为什么要有这个
 *
 * 手动 `POST /api/monitoring/collect` 只能算「能抓」,不算「监测」。
 * **监测的定义是:不盯着也会发生。**
 *
 * ## 失败必须告警而非静默
 *
 * 爬虫挂掉时如果只是安静地什么都不做,业务侧会以为「今天没新法规」,
 * 而实际是「爬虫坏了」。所以:
 *   ① 失败写进 `monitoring_runs`(status='failed' + error 详情)
 *   ② console.error 打出来(外部监控按 error 级抓取)
 *   ③ **不吞异常** —— 让 Workers 错误日志也捕获到
 *
 * ## 抓多少
 *
 * Cron 里的抓取量要克制:
 *   - 列表 1 页(10 条公告,427ms)
 *   - 正文只抓前 5 条(串行,约 25 秒)
 *
 * 理由:① 政府网站不该被高频压;② Workers 有 15 分钟执行上限但不该占满;
 * ③ 正文抓取是整条链路里最慢的部分,而**列表页才是发现「有没有新公告」的关键** ——
 *    新公告一定出现在列表首页。所以「列表全量 + 正文抽样」是正确的分工。
 */

import { createApp, type Env } from "../composition-root";
import type { MonitoringRepository } from "../../application/monitoring/monitoring.repository";
import type { CollectReleasesUseCase } from "../../application/monitoring/monitoring.usecase";

/** Cron 触发时的抓取配置。 */
const CRON_PAGES = 1;
const CRON_MAX_BODIES = 5;

/**
 * 执行一次定时抓取。
 *
 * @param controller Cron 控制器(Cloudflare 注入)
 * @param env Worker 环境
 * @param deps 依赖注入(可选)—— **测试用**。生产走 `createApp(env)` 自造。
 *             ⚠️ 没有这个口子的话,并发闸门与「影响面才告警」这两条逻辑
 *             就无法单测(定时任务里 createApp 会自己 new 仓储)。
 */
export async function runScheduledMonitoring(
  controller: ScheduledController,
  env: Env,
  deps?: { monitoringRepo?: MonitoringRepository; monitoringCollect?: CollectReleasesUseCase }
): Promise<void> {
  const cron = controller?.cron ?? "(manual)";
  // ⚠️ 注入时两个依赖必须一起给 —— 只给 repo 不给 collect 会让下面的
  //    `collect.execute` 拿到 undefined。测试里两个都会给。
  if (deps?.monitoringRepo && deps?.monitoringCollect) {
    return runCollect(
      cron,
      deps.monitoringRepo,
      deps.monitoringCollect
    );
  }
  const app = createApp(env);
  return runCollect(cron, app.monitoringRepo, app.monitoringCollect);
}

/** 真正的抓取编排(抽出来是为了让上面两个分支共用同一段逻辑)。 */
async function runCollect(
  cron: string,
  repo: MonitoringRepository,
  collect: CollectReleasesUseCase
): Promise<void> {
  try {
    // ⚠️ **并发闸门** —— 如果上一次 Cron 还在跑(Worker 被复用),
    //    不要重复抓。手动 collect 端点也做同样的检查。
    const runs = await repo.listRuns(1);
    const latest = runs[0];
    if (latest && latest.status === "running") {
      console.warn(
        `[monitoring] cron=${cron} 上一次抓取仍在运行(run=${latest.runId}),跳过本次`
      );
      return;
    }

    const result = await collect.execute({
      pages: CRON_PAGES,
      maxBodies: CRON_MAX_BODIES,
    });

    console.log(
      `[monitoring] cron=${cron} found=${result.found} new=${result.newCount} ` +
        `revised=${result.revisedCount} impacted=${result.impacted.length}`
    );

    // ⚠️ **影响面可判定才告警** —— 算不出影响面的不算「需要人看」。
    //    这是 ADR-004 写死的不变量。
    if (result.impacted.length > 0) {
      for (const r of result.impacted) {
        console.warn(
          `[monitoring] ⚠️ 需要关注:${r.releaseKey} ${r.title} ` +
            `影响 ${r.affectedAssets.join(", ")} — ${r.url}`
        );
      }
    }
  } catch (e) {
    // ⚠️ **不吞异常** —— 让 Workers 错误日志捕获到,外部监控才能告警。
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[monitoring] cron=${cron} 定时抓取失败:${msg}`);
    throw e;
  }
}
