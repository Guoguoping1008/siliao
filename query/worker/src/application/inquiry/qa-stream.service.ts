/**
 * 流式问答 —— 应用层
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ## 为什么 SSE 组装在应用层而不是 interfaces 层
 *
 * ⚠️ 之前 `ragQAStream` 整个塞在 `index.ts` 里 —— 那是**位置错误**:
 *   它包含「检索 → 拼 prompt → 调 LLM → 校验引用」这套**业务编排**,
 *   只是碰巧输出了 SSE 格式。
 *
 * ADR-004 的分层是按**职责**分的, 不是按输出格式分的:
 *   · 「怎么把答案流式吐出去」= 传输层关注点 → interfaces/http
 *   · 「检索什么、怎么拼 prompt、怎么校验引用」= 业务编排 → application
 *
 * 本文件负责业务编排, 产出的是**事件序列**;
 * interfaces/http/sse.ts 负责把事件序列变成 HTTP 响应。
 *
 * ⚠️ 纯度保证 (ADR-004 R2): 应用层不出现 fetch() —— LLM 调用走 ACL。
 */

import { buildRagPrompt } from "./prompt-builder";
import { validateCitations } from "../../domain/inquiry/citation-validator.service";
import type { Evidence } from "../../domain/inquiry/evidence.vo";
import {
  chatCompletionStream,
  consumeSSE,
  type SseEventName,
} from "../../interfaces/acl/llm-stream.acl";
import { llmConfig, type LlmEnv } from "../../interfaces/acl/llm.acl";

/** 检索端口(与单轮问答共用)。 */
export interface EvidenceRetriever {
  search(params: { q: string }): Promise<{ hits: Evidence[]; query: string }>;
}

/** 流式问答的事件回调。 */
export interface QaStreamHandlers {
  /** 检索到的证据(开头发)。 */
  onMeta?: (e: { question: string; retrieval: Evidence[] }) => void;
  /** 增量 token。 */
  onChunk?: (e: { delta: string }) => void;
  /** 结束 + 校验后的引用。 */
  onDone?: (e: { citations: ReturnType<typeof validateCitations> }) => void;
  /** 出错。 */
  onError?: (e: { message: string; status?: number }) => void;
}

/**
 * 流式问答 —— 产出事件序列。
 *
 * @param handlers 事件回调
 * @returns 事件名序列(供调用方决定响应格式; 单测可断言顺序)
 */
export async function streamQa(
  question: string,
  retriever: EvidenceRetriever,
  llmEnv: LlmEnv,
  handlers: QaStreamHandlers
): Promise<SseEventName[]> {
  const emitted: SseEventName[] = [];
  const emit = (name: SseEventName, data: unknown) => {
    emitted.push(name);
    switch (name) {
      case "meta":
        handlers.onMeta?.(data as { question: string; retrieval: Evidence[] });
        break;
      case "chunk":
        handlers.onChunk?.(data as { delta: string });
        break;
      case "done":
        handlers.onDone?.(data as { citations: ReturnType<typeof validateCitations> });
        break;
      case "error":
        handlers.onError?.(data as { message: string; status?: number });
        break;
    }
  };

  try {
    // 1. 检索
    const { hits } = await retriever.search({ q: question });
    emit("meta", { question, retrieval: hits.slice(0, 8) });

    // 2. 拼 prompt + 调 LLM(流式)
    const { systemPrompt, userPrompt } = buildRagPrompt(question, hits);
    const llm = llmConfig(llmEnv);
    const resp = await chatCompletionStream(
      llm,
      [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      { temperature: 0.2, max_tokens: 1000 }
    );

    if (!resp.ok || !resp.body) {
      emit("error", { status: resp.status, message: await resp.text() });
      return emitted;
    }

    // 3. 逐帧转 delta
    const fullAnswer = await consumeSSE(resp, (delta) => {
      emit("chunk", { delta });
    });

    // 4. 校验引用,推送 done
    emit("done", { citations: validateCitations(fullAnswer, hits) });
  } catch (e) {
    emit("error", { message: (e as Error).message });
  }

  return emitted;
}
