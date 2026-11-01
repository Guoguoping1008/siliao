/**
 * ③ 问答 路由 —— 接口层
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * 路由:
 *   POST   /api/qa              RAG 问答(同步 / SSE 流式)
 *   POST   /api/qa/conversation 多轮问答
 *   DELETE /api/qa/conversation 清空会话
 *
 * ⚠️ **流式的组装在 interfaces 层, 业务编排在 application 层** ——
 *    `qa-stream.service.ts` 产出事件序列, 这里把事件序列变成 SSE 响应。
 */

import { json, errorJson, CORS } from "../http-utils";
import { formatSSE } from "../../acl/llm-stream.acl";
import { streamQa } from "../../../application/inquiry/qa-stream.service";
import type { AppDependencies } from "../../composition-root";
import type { Env } from "../../composition-root";

/**
 * 从请求体里取问题文本。
 *
 * ⚠️ 2026-10-27 加: 字段名写错(q/question/ask)时**静默**返回
 *    「未找到相关规定」—— 看起来像检索没召回, 实际是压根没收到问题。
 *    排查时非常误导。现在明确报 400 并说明正确字段名。
 *    同时接受 question/ask 作为别名, 前端/脚本用哪个都行。
 */
export function extractQuestion(body: {
  q?: string;
  question?: string;
  ask?: string;
}): string {
  return (body.q ?? body.question ?? body.ask ?? "").toString().trim();
}

/** POST /api/qa */
export async function handleQa(
  app: AppDependencies,
  env: Env,
  body: { q?: string; question?: string; ask?: string; stream?: boolean },
  wantStream: boolean
): Promise<Response> {
  const question = extractQuestion(body);
  if (!question) {
    return errorJson(
      "missing_query",
      "缺少查询字段。POST body 请用 {\"q\": \"你的问题\"} (别名: question / ask)"
    );
  }

  if (wantStream) {
    return streamQaResponse(app, env, question);
  }
  return json(await app.inquiry.ask(question));
}

/**
 * SSE 响应 —— 把应用层的事件序列包成 HTTP 响应。
 *
 * ⚠️ 事件在**流开始后**才产生, 但 HTTP 状态码在响应头发出后就改不了了。
 *    所以出错只能再发一个 `error` 事件 —— 这也是流式与非流式的错误处理
 *    必须分开的原因(见 llm-stream.acl.ts 的说明)。
 */
function streamQaResponse(
  app: AppDependencies,
  env: Env,
  question: string
): Response {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const push = (event: string, data: unknown) => {
        controller.enqueue(encoder.encode(formatSSE(event as any, data)));
      };
      await streamQa(question, app.retriever, env, {
        onMeta: (e) => push("meta", e),
        onChunk: (e) => push("chunk", e),
        onDone: (e) => push("done", e),
        onError: (e) => push("error", e),
      });
      controller.close();
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

/** POST /api/qa/conversation */
export async function handleConversation(
  app: AppDependencies,
  req: Request
): Promise<Response> {
  const body = await req.json<{
    sessionId?: string;
    session_id?: string;
    q?: string;
    question?: string;
    ask?: string;
  }>();
  const sessionId = (body.sessionId ?? body.session_id ?? "").toString().trim();
  const question = extractQuestion(body);

  if (!sessionId) {
    return errorJson(
      "missing_session_id",
      "缺少会话 id。POST body 请用 {\"sessionId\": \"...\", \"q\": \"你的问题\"}"
    );
  }
  if (!question) {
    return errorJson(
      "missing_query",
      "缺少查询字段。POST body 请用 {\"sessionId\": \"...\", \"q\": \"你的问题\"}"
    );
  }
  return json(await app.conversation.ask({ sessionId, question }));
}

/** DELETE /api/qa/conversation */
export async function handleClearConversation(
  app: AppDependencies,
  sessionId: string
): Promise<Response> {
  if (!sessionId) {
    return errorJson("missing_session_id", "缺少 sessionId 查询参数");
  }
  await app.conversation.clear(sessionId);
  return json({ ok: true, sessionId });
}
