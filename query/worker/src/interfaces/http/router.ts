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
 *
 * ## ⚠️ 路由顺序
 *
 * **静态路径必须排在正则路由前面** —— 否则 `/api/documents/:doc_id/chapters`
 * 会被 `/api/documents` 之类的规则先吃掉。
 * 下面的顺序是**刻意的**, 改动前先想清楚。
 */

import { json, errorJson, CORS } from "./http-utils";
import { handleSearch, handleEntity } from "./routes/retrieval.routes";
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

  try {
    // ── ① 法规知识库 ──
    if (path === "/api/documents") {
      return handleDocuments(app);
    }
    if (path === "/api/catalog") {
      return handleCatalog(app);
    }

    const mDocChs = path.match(/^\/api\/documents\/([^/]+)\/chapters$/);
    if (mDocChs) {
      return handleChapters(app, mDocChs[1]);
    }
    const mChap = path.match(/^\/api\/chapter\/([^/]+)\/([^/]+)$/);
    if (mChap) {
      return handleChapter(app, mChap[1], mChap[2]);
    }
    const mArt = path.match(/^\/api\/article\/([^/]+)$/);
    if (mArt) {
      return handleArticle(app, mArt[1]);
    }

    // ── 检索 + ④ 图谱 ──
    if (path === "/api/search" || path === "/api/search/") {
      return handleSearch(app, url.searchParams);
    }
    const mEnt = path.match(/^\/api\/entity\/(.+)$/);
    if (mEnt) {
      return handleEntity(app, mEnt[1]);
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
      return handleQa(app, env, body, wantStream);
    }
    if (path === "/api/qa/conversation" && method === "POST") {
      return handleConversation(app, req);
    }
    if (path === "/api/qa/conversation" && method === "DELETE") {
      return handleClearConversation(app, url.searchParams.get("sessionId") ?? "");
    }

    // ── ② 合规规则 ──
    if (path === "/api/compliance/usage" && method === "POST") {
      return handleComplianceUsage(app, req);
    }

    return json({ error: "not_found", path }, 404);
  } catch (e) {
    return errorJson("internal", (e as Error).message, 500);
  }
}
