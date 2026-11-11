/**
 * 路由分发 —— 接口层
 *
 * 上下文: 贯穿所有上下文(纯传输层关注点)
 *
 * ## 路由表
 *
 *   GET    /api/search?q=...                检索条文 (FTS5 + bge hybrid)
 *   GET    /api/documents                   文档列表
 *   GET    /api/documents/:doc_id/chapters  文档下的章节
 *   GET    /api/catalog                     目录树
 *   GET    /api/chapter/:doc_id/:ch_id      整章 Markdown
 *   GET    /api/article/:art_id             单条 Markdown + 章节上下文
 *   GET    /api/entity/:name                实体卡 + 关联条文
 *   POST   /api/qa                          RAG 问答(同步 / SSE 流式)
 *   POST   /api/qa/conversation             多轮问答
 *   DELETE /api/qa/conversation             清空会话
 *   POST   /api/compliance/usage            用量合规判定
 *   GET    /api/monitoring/releases         ⑤ 已抓到的法规发布
 *   GET    /api/monitoring/impact           ⑤ 影响面报告
 *   GET    /api/monitoring/runs             ⑤ 抓取运行记录
 *   POST   /api/monitoring/collect          ⑤ 手动触发抓取
 *   GET    /api/monitoring/subscriptions    ⑤ 订阅列表
 *   POST   /api/monitoring/subscriptions    ⑤ 新增订阅
 *   DELETE /api/monitoring/subscriptions    ⑤ 删订阅
 *
 * ## ⚠️ 路由顺序
 *
 * **静态路径必须排在正则路由前面** —— 否则 `/api/documents/:doc_id/chapters`
 * 会被 `/api/documents` 之类的规则先吃掉。
 * 下面的顺序是**刻意的**, 改动前先想清楚。
 */

import { json, errorJson, CORS } from "./http-utils";
import { handleSearch, handleEntity, handleEntityList } from "./routes/retrieval.routes";
import {
  handleDocuments,
  handleCatalog,
  handleChapters,
  handleChapter,
  handleArticle,
} from "./routes/regulation.routes";
import {
  handleQa,
  handleConversation,
  handleClearConversation,
} from "./routes/inquiry.routes";
import { handleComplianceUsage } from "./routes/compliance.routes";
import {
  handleListReleases,
  handleImpactReport,
  handleListRuns,
  handleCollect,
  handleListSubscriptions,
  handleCreateSubscription,
  handleDeleteSubscription,
} from "./routes/monitoring.routes";
import { createApp, type Env } from "../composition-root";

/**
 * 分发请求。
 *
 * @returns 路由响应; 未匹配返回 404
 */
export async function route(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname;
  const method = req.method;

  if (method === "OPTIONS") {
    return new Response(null, { headers: CORS });
  }

  const app = createApp(env);

  // ⚠️ **每个 handler 调用都必须 `await`** ——
  //    `return promise` 时 try 块已经正常返回, 下面的 catch **捕获不到** handler
  //    内部抛出的错误。错误会变成 unhandled rejection → Workers 报 **1101**
  //    (Worker threw exception), 而不是我们自己的 500 JSON。
  //
  //    重构前(index.ts 单文件)是 `return json(await app.xxx(...))` —— await 在
  //    try 块内, 所以能捕获。M3 抽路由层时 await 留在了 handler 内部,
  //    try/catch 就失去了作用。**这是 2026-11-02 生产 1101 的根因。**
  //
  //    回归测试: `src/interfaces/http/router.error-handling.test.ts`
  try {
    // ── ① 法规知识库 ──
    if (path === "/api/documents") {
      return await handleDocuments(app);
    }
    if (path === "/api/catalog") {
      return await handleCatalog(app);
    }

    const mDocChs = path.match(/^\/api\/documents\/([^/]+)\/chapters$/);
    if (mDocChs) {
      return await handleChapters(app, mDocChs[1]);
    }
    const mChap = path.match(/^\/api\/chapter\/([^/]+)\/([^/]+)$/);
    if (mChap) {
      return await handleChapter(app, mChap[1], mChap[2]);
    }
    const mArt = path.match(/^\/api\/article\/([^/]+)$/);
    if (mArt) {
      return await handleArticle(app, mArt[1]);
    }

    // ── 检索 + ④ 图谱 ──
    if (path === "/api/search" || path === "/api/search/") {
      return await handleSearch(app, url.searchParams);
    }
    const mEnt = path.match(/^\/api\/entity\/(.+)$/);
    if (mEnt) {
      return await handleEntity(app, mEnt[1]);
    }
    // ── 实体列表 ──
    // ⚠️ 顺序必须在 `/api/entity/:name` **之后** —— 否则 "entities" 会被
    //    当成实体名去查。
    if (path === "/api/entities" || path === "/api/entities/") {
      return await handleEntityList(app, url.searchParams);
    }

    // ── ③ 问答 ──
    if (path === "/api/qa" && method === "POST") {
      // ⚠️ `stream` 可以在 **body** 或 **query string** 里 ——
      //    前端两种都用过(早期在 body 里, 后来 SSE 走 query)。
      //    body 必须**只读一次** —— 读完就没了, 路由层不能为了看一个
      //    标志位把 body 消费掉。所以在这里 parse 一次, 把 body 传给 handler。
      const body = await req.json<{
        q?: string;
        question?: string;
        ask?: string;
        stream?: boolean;
      }>();
      const wantStream =
        body.stream === true || url.searchParams.get("stream") === "true";
      return await handleQa(app, env, body, wantStream);
    }
    if (path === "/api/qa/conversation" && method === "POST") {
      return await handleConversation(app, req);
    }
    if (path === "/api/qa/conversation" && method === "DELETE") {
      return await handleClearConversation(app, url.searchParams.get("sessionId") ?? "");
    }

    // ── ② 合规规则 ──
    if (path === "/api/compliance/usage" && method === "POST") {
      return await handleComplianceUsage(app, req);
    }

    // ── ⑤ 法规监测 ──
    // ⚠️ 顺序:subscriptions 的静态路径必须在 `/api/monitoring/:something` 之类
    //    之前,否则会被当成动态段吃掉。
    if (path === "/api/monitoring/releases" && method === "GET") {
      return await handleListReleases(app, req);
    }
    if (path === "/api/monitoring/impact" && method === "GET") {
      return await handleImpactReport(app, req);
    }
    if (path === "/api/monitoring/runs" && method === "GET") {
      return await handleListRuns(app, req);
    }
    if (path === "/api/monitoring/collect" && method === "POST") {
      return await handleCollect(app, req);
    }
    if (path === "/api/monitoring/subscriptions" && method === "GET") {
      return await handleListSubscriptions(app, req);
    }
    if (path === "/api/monitoring/subscriptions" && method === "POST") {
      return await handleCreateSubscription(app, req);
    }
    if (path === "/api/monitoring/subscriptions" && method === "DELETE") {
      return await handleDeleteSubscription(app, req);
    }

    return json({ error: "not_found", path }, 404);
  } catch (e) {
    return errorJson("internal", (e as Error).message, 500);
  }
}
