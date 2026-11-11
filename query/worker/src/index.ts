/**
 * Cloudflare Workers 主入口
 *
 * ⚠️ **本文件只做一件事: 把 Request 交给路由层。**
 *
 * ADR-004 M3 的目标: index.ts 只剩「入口 + 路由挂载」。
 * 历史上的三层演进:
 *   · M1(2026-10-28)  1059 行 → 291 行  抽出领域层与应用层
 *   · M3(2026-10-31)  291 行 → ~40 行   抽出路由层与 SSE 组装
 *
 * 业务逻辑现在都在:
 *
 *   domain/          领域层(纯 TS, 零依赖, 零 I/O)
 *     inquiry/         ③ 问答   —— 引用校验 · 会话上下文(指代消解)
 *     compliance/      ② 合规规则 —— 聚合根 · 判定器 · 命名匹配
 *     regulation/      ① 法规库 —— 检索查询逻辑 + 文档聚合
 *     shared/          公共内核 —— 领域事件
 *
 *   application/     应用层(编排)
 *     inquiry/         ③ 问答   —— prompt 组装 · 问答流程 · 流式编排
 *     compliance/      ② 合规规则 —— 校验 Use Case
 *
 *   interfaces/      接口层
 *     http/            路由分发 + 各上下文路由 + HTTP 工具
 *     acl/             防腐层 —— LLM(同步/流式) / bge / 法规正文
 *     composition-root.ts 组装根(手写, Workers 无 DI 容器)
 *
 *   infrastructure/  基础设施层
 *     persistence/d1/  D1 仓储实现(**全部 SQL 在这里**)
 *     persistence/retrieval/ 混合检索适配器
 */

import { route } from "./interfaces/http/router";
import { runScheduledMonitoring } from "./interfaces/http/scheduled";
import type { Env } from "./interfaces/composition-root";

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    return route(req, env);
  },

  /**
   * Cron 定时任务 —— ⑤ 法规监测的自动抓取。
   *
   * ⚠️ **失败必须告警而非静默** —— `runScheduledMonitoring` 内部会把失败
   *    写进 `monitoring_runs` 并 console.error。这里不吞异常:让 Workers 的
   *    错误日志捕获到,便于外部监控按 error 级告警。
   */
  async scheduled(
    controller: ScheduledController,
    env: Env,
    ctx: ExecutionContext
  ): Promise<void> {
    ctx.waitUntil(runScheduledMonitoring(controller, env));
  },
};
