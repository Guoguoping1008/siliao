/**
 * Cloudflare Workers 主入口 —— 路由层
 *
 * ⚠️ 本文件在 ADR-004 (M1 阶段) 后**只负责路由分发**。
 *    业务逻辑已按 DDD 限界上下文拆到:
 *
 *      domain/          领域层(纯 TS, 零依赖, 零 I/O)
 *        inquiry/         ③ 问答   —— 引用校验(核心业务规则)
 *        regulation/      ① 法规库 —— 检索查询逻辑 + 文档聚合
 *        shared/          公共内核 —— 领域事件
 *      application/     应用层(编排)
 *        inquiry/         ③ 问答   —— prompt 组装 + 问答流程
 *      interfaces/      接口层
 *        acl/             防腐层 —— LLM / bge / 法规正文
 *        composition-root.ts 组装根
 *      infrastructure/  基础设施层
 *        persistence/d1/  D1 仓储实现
 *        persistence/retrieval/ 混合检索适配器
 *
 * 路由表:
 *   GET  /api/search?q=...                检索条文 (FTS5 + bge hybrid)
 *   GET  /api/chapter/:doc_id/:ch_id      返回整章 Markdown
 *   GET  /api/article/:art_id             返回单条 Markdown + 章节上下文
 *   GET  /api/entity/:name                实体卡 + 关联条文
 *   GET  /api/documents                   文档列表
 *   GET  /api/documents/:doc_id/chapters  文档下的章节
 *   GET  /api/catalog                     目录树
 *   POST /api/qa                          RAG 问答(同步 / SSE 流式)
 */

import { createApp, type Env } from "./interfaces/composition-root";
import { llmConfig, fetchWithRetry } from "./interfaces/acl/llm.acl";
import { validateCitations } from "./domain/inquiry/citation-validator.service";
import { validateComplianceBody } from "./domain/compliance/compliance-request.vo";
import type { Evidence } from "./domain/inquiry/evidence.vo";
import { buildRagPrompt } from "./application/inquiry/prompt-builder";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(req.url);
    const path = url.pathname;
    // ⚠️ url.pathname **不做 percent-decode** —— 中文 article_id 会带着
    //    %E5%B0%81... 的编码形式进来。路由捕获到的参数必须 decodeURIComponent,
    //    否则查 D1 一条都查不到(症状: 所有条文/章节详情都 not_found)。
    //    decodeURIComponent 对已解码的普通 ASCII id 也是安全的(无 % 就原样返回)。

    const app = createApp(env);

    try {
      if (path === "/api/search" || path === "/api/search/") {
        const result = await app.retriever.search({
          q: url.searchParams.get("q") ?? "",
          docId: url.searchParams.get("doc_id") || undefined,
          chapterId: url.searchParams.get("chapter_id") || undefined,
          debug: url.searchParams.get("debug") === "1",
        });
        return json(result, env);
      }
      if (path === "/api/documents") return json({ documents: await app.regulations.listDocuments() }, env);
      if (path === "/api/catalog") return json(await app.regulations.getCatalog(), env);

      const mDocChs = path.match(/^\/api\/documents\/([^/]+)\/chapters$/);
      // ⚠️ 必须 decode —— url.pathname 不做 percent-decode,
      //    中文 doc_id 会带 %E5%81... 进 D1, 查不到任何章节。
      if (mDocChs) {
        return json({ chapters: await app.regulations.listChapters(decodeURIComponent(mDocChs[1])) }, env);
      }
      const mChap = path.match(/^\/api\/chapter\/([^/]+)\/([^/]+)$/);
      if (mChap) {
        return json(
          await app.regulations.getChapter(decodeURIComponent(mChap[1]), decodeURIComponent(mChap[2])),
          env
        );
      }
      const mArt = path.match(/^\/api\/article\/([^/]+)$/);
      if (mArt) return json(await app.regulations.getArticle(decodeURIComponent(mArt[1])), env);

      const mEnt = path.match(/^\/api\/entity\/(.+)$/);
      if (mEnt) {
        return json(await getEntity(decodeURIComponent(mEnt[1]), env), env);
      }
      if (path === "/api/qa" && req.method === "POST") {
        const body = await req.json<{ q: string; stream?: boolean; question?: string }>();
        // ⚠️ 2026-10-27 加: 字段名写错(q/question/ask)时**静默**返回
        //    "未找到相关规定" —— 看起来像检索没召回, 实际是压根没收到问题。
        //    排查时非常误导。现在明确报 400 并说明正确字段名。
        //    同时接受 question/ask 作为别名, 前端/脚本用哪个都行。
        const rawQ = (body.q ?? body.question ?? (body as any).ask ?? "").toString().trim();
        if (!rawQ) {
          return json(
            {
              error: "missing_query",
              message: "缺少查询字段。POST body 请用 {\"q\": \"你的问题\"} (别名: question / ask)",
            },
            env,
            400
          );
        }
        const wantStream = body.stream || url.searchParams.get("stream") === "true";
        if (wantStream) {
          return ragQAStream(rawQ, env);
        }
        return json(await app.inquiry.ask(rawQ), env);
      }
      if (path === "/api/qa/conversation" && req.method === "POST") {
        // ── C1.5 多轮会话 ──
        // ⚠️ 与 /api/qa 分开而不是加参数 —— 单轮接口的语义是
        //    「无状态的一次问答」, 多轮带会话状态, 混在一起会让
        //    调用方搞不清什么时候有上下文。
        const body = await req.json<{
          sessionId?: string;
          session_id?: string;
          q?: string;
          question?: string;
          ask?: string;
        }>();
        const sessionId = (body.sessionId ?? body.session_id ?? "").toString().trim();
        const rawQ = (body.q ?? body.question ?? body.ask ?? "").toString().trim();
        if (!sessionId) {
          return json(
            {
              error: "missing_session_id",
              message:
                "缺少会话 id。POST body 请用 {\"sessionId\": \"...\", \"q\": \"你的问题\"}",
            },
            env,
            400
          );
        }
        if (!rawQ) {
          return json(
            {
              error: "missing_query",
              message:
                "缺少查询字段。POST body 请用 {\"sessionId\": \"...\", \"q\": \"你的问题\"}",
            },
            env,
            400
          );
        }
        return json(await app.conversation.ask({ sessionId, question: rawQ }), env);
      }
      if (path === "/api/qa/conversation" && req.method === "DELETE") {
        const sessionId = url.searchParams.get("sessionId") ?? "";
        if (!sessionId) {
          return json(
            { error: "missing_session_id", message: "缺少 sessionId 查询参数" },
            env,
            400
          );
        }
        await app.conversation.clear(sessionId);
        return json({ ok: true, sessionId }, env);
      }
      if (path === "/api/compliance/usage" && req.method === "POST") {
        const body = await req.json<{
          substance?: string;
          species?: string;
          stage?: string | null;
          value?: number;
          unit?: string;
        }>();
        // ⚠️ 入参校验 —— 用量判定是**确定性**的, 参数错必须明确报错,
        //    不能像 LLM 抽取那样静默给个错结论。
        const err = validateComplianceBody(body);
        if (err) {
          return json({ error: "invalid_request", message: err }, env, 400);
        }
        return json(
          await app.complianceCheck.check({
            substance: body.substance!.trim(),
            species: body.species!.trim(),
            stage: body.stage ?? null,
            value: body.value!,
            unit: body.unit!.trim(),
          }),
          env
        );
      }
      return json({ error: "not_found", path }, env, 404);
    } catch (e) {
      return json({ error: "internal", message: (e as Error).message }, env, 500);
    }
  },
};

function json(data: unknown, env: Env, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

// ---------- ④ 知识图谱: 实体详情 ----------

async function getEntity(name: string, env: Env) {
  const app = createApp(env);
  const ent = await app.graph.findEntityByName(name);
  if (!ent) return { error: "entity_not_found" };
  const articles = await app.graph.listEntityArticles(ent.entity_id);
  return { entity: ent, articles };
}

// ---------- ③ 问答: 流式 ----------

/**
 * Streaming RAG 问答: SSE 推送, 事件类型:
 *   - `event: meta\ndata: { question, retrieval }`  (开头发检索证据)
 *   - `event: chunk\ndata: {"delta": "..."}`         (增量 token)
 *   - `event: done\ndata: { citations }`            (结束 + 校验后引用)
 *
 * 出错事件:
 *   - `event: error\ndata: { message }`
 */
function ragQAStream(q: string, env: Env): Response {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        // 1. 检索
        const app = createApp(env);
        const { hits } = await app.retriever.search({ q });
        controller.enqueue(encoder.encode(formatSSE("meta", {
          question: q,
          retrieval: hits.slice(0, 8),
        })));

        // 2. LLM streaming
        const { systemPrompt, userPrompt } = buildRagPrompt(q, hits);
        const llm = llmConfig(env);
        const resp = await fetch(`${llm.base}/chat/completions`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${llm.key}`,
          },
          body: JSON.stringify({
            model: llm.model,
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: userPrompt },
            ],
            temperature: 0.2,
            max_tokens: 1000,
            stream: true,
          }),
        });

        if (!resp.ok || !resp.body) {
          controller.enqueue(encoder.encode(formatSSE("error", {
            status: resp.status,
            body: await resp.text(),
          })));
          controller.close();
          return;
        }

        // 3. 透传上游 SSE,提取 delta
        let fullAnswer = "";
        // OpenAI/MiniMax SSE:每行 `data: { "choices": [{ "delta": { "content": "..." }}] }`
        const emitDelta = (line: string) => {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) return;
          const payload = trimmed.slice(5).trim();
          if (!payload || payload === "[DONE]") return;
          try {
            const obj = JSON.parse(payload);
            const delta = obj.choices?.[0]?.delta?.content;
            if (delta) {
              fullAnswer += delta;
              controller.enqueue(encoder.encode(formatSSE("chunk", { delta })));
            }
          } catch {
            // ignore malformed line
          }
        };
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            // 收尾: flush decoder + 解析残留
            buf += decoder.decode();
            for (const line of buf.split("\n")) {
              emitDelta(line);
            }
            break;
          }
          buf += decoder.decode(value, { stream: true });
          // ⚠️ **不能每轮把 buf 清空** —— TCP 分片跟 SSE 帧边界不对齐,
          //    一个帧可能跨多个 read, 一个 read 也可能含多帧。
          //    旧代码 `buf = ""` 会丢掉所有没读完整的行, 表现为
          //    「只收到 1 个 chunk, 答案被截断」(MiniMax 的帧比 DeepSeek 大, 必现)。
          //    正确做法: 只消费**完整的行**(以 \n 结尾), 余下的留在 buf 里等下一轮。
          let nlIdx: number;
          while ((nlIdx = buf.indexOf("\n")) !== -1) {
            const line = buf.slice(0, nlIdx);
            buf = buf.slice(nlIdx + 1);
            emitDelta(line);
          }
        }

        // 4. 校验引用,推送 done
        const citations = validateCitations(fullAnswer, hits as Evidence[]);
        controller.enqueue(encoder.encode(formatSSE("done", { citations })));
        controller.close();
      } catch (e) {
        controller.enqueue(encoder.encode(formatSSE("error", {
          message: (e as Error).message,
        })));
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      ...CORS,
    },
  });
}

function formatSSE(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

// 保留导出, 供测试引用(避免 tree-shaking 报未使用)
export { fetchWithRetry };
