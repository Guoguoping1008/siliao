/**
 * LLM 流式调用 —— 防腐层 (ACL)
 *
 * 上下文: ③ 问答 Inquiry 的外部依赖
 *
 * ## 为什么单独一个文件
 *
 * `llm.acl.ts` 里的 `chatCompletion` 是**非流式**的 —— 一次性拿到完整答案。
 * 流式要用另一种方式: 拿到 Response 后逐块读 body, 解析 SSE 帧。
 *
 * ⚠️ **两个 ACL 分开的理由不是「文件好看」, 是「错误处理路径不同」**:
 *   · 非流式: 出错 → HTTP 状态码 + body 一次性返回
 *   · 流式:   出错 → 可能已经发过 `meta` 事件了, 只能再发一个 `error` 事件
 *             (HTTP 状态码在响应头发出后就改不了了)
 *
 * ## ⚠️ SSE 帧边界 —— 这里踩过坑
 *
 * TCP 分片跟 SSE 帧边界**不对齐**: 一个帧可能跨多个 read, 一个 read 也可能含多帧。
 * 旧代码每轮把 buffer 清空 → 丢掉所有没读完整的行 →
 * 表现为「只收到 1 个 chunk, 答案被截断」(MiniMax 的帧比 DeepSeek 大, 必现)。
 *
 * 正确做法: 只消费**完整的行**(以 \n 结尾), 余下的留在 buffer 等下一轮。
 */

import type { ChatMessage, LlmConfig } from "./llm.acl";
import { DEFAULT_MAX_TOKENS } from "./llm.acl";

/** SSE 帧类型。 */
export type SseEventName = "meta" | "chunk" | "done" | "error";

/** SSE 帧。 */
export interface SseEvent {
  event: SseEventName;
  data: unknown;
}

/** 把事件序列化成 SSE 文本。 */
export function formatSSE(event: SseEventName, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * 从一段 SSE 文本里抽取增量内容。
 *
 * OpenAI/MiniMax 兼容格式:
 *   `data: { "choices": [{ "delta": { "content": "..." }}] }`
 *
 * @returns 抽出的增量; 不是数据行或格式不对返回 null
 */
export function parseSSEDelta(line: string): string | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("data:")) return null;
  const payload = trimmed.slice(5).trim();
  if (!payload || payload === "[DONE]") return null;
  try {
    const obj = JSON.parse(payload);
    const delta = obj.choices?.[0]?.delta?.content;
    return typeof delta === "string" && delta ? delta : null;
  } catch {
    // malformed 行 —— 跳过, 不中断整条流
    return null;
  }
}

/**
 * 发起流式 chat completion。
 *
 * @returns 上游 Response —— 调用方负责逐块读 body
 */
export function chatCompletionStream(
  cfg: LlmConfig,
  messages: ChatMessage[],
  options: { temperature?: number; max_tokens?: number } = {}
): Promise<Response> {
  return fetch(`${cfg.base}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${cfg.key}`,
    },
    body: JSON.stringify({
      model: cfg.model,
      messages,
      temperature: options.temperature ?? 0.2,
      max_tokens: options.max_tokens ?? DEFAULT_MAX_TOKENS,
      stream: true,
    }),
  });
}

/**
 * 把上游 SSE 流逐帧转成事件回调。
 *
 * @param resp    上游 Response(必须 body 非空)
 * @param onDelta 每个增量 token
 * @returns 完整答案(拼接后的 delta)
 */
export async function consumeSSE(
  resp: Response,
  onDelta: (delta: string) => void
): Promise<string> {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let full = "";

  const emitLine = (line: string) => {
    const delta = parseSSEDelta(line);
    if (delta) {
      full += delta;
      onDelta(delta);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      // 收尾: flush decoder + 解析残留
      buf += decoder.decode();
      for (const line of buf.split("\n")) emitLine(line);
      break;
    }
    buf += decoder.decode(value, { stream: true });
    // ⚠️ **只消费完整的行**(以 \n 结尾), 余下的留在 buf 里等下一轮
    let nlIdx: number;
    while ((nlIdx = buf.indexOf("\n")) !== -1) {
      const line = buf.slice(0, nlIdx);
      buf = buf.slice(nlIdx + 1);
      emitLine(line);
    }
  }

  return full;
}
