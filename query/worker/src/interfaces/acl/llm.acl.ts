/**
 * LLM 防腐层 (ACL)
 *
 * 上下文: ③ 问答 Inquiry 的外部依赖
 *
 * ## 为什么需要 ACL
 *
 * LLM 供应商(MiniMax / DeepSeek / 任何 OpenAI 兼容端点)的差异是**外部概念**,
 * 不该渗透进领域层。领域层只知道「我要一次 chat completion」,
 * 不知道 base_url 长什么样、model 叫什么、key 从哪个环境变量读。
 *
 * ## 纯度边界 (ADR-004 R3)
 *
 * 领域层**不得**出现 fetch()。所有 LLM 调用必须经过这里。
 */

/** LLM 连接配置。 */
export interface LlmConfig {
  base: string;
  model: string;
  key: string;
}

/** Worker 环境变量里 LLM 相关的部分(最小必要集)。 */
export interface LlmEnv {
  LLM_API_BASE?: string;
  LLM_MODEL?: string;
  LLM_API_KEY?: string;
  DEEPSEEK_API_BASE?: string;
  DEEPSEEK_MODEL?: string;
  DEEPSEEK_API_KEY?: string;
}

/**
 * 解析 LLM 端点(provider 无关)。
 *
 * ⚠️ MiniMax 的 OpenAI 兼容端点是 `https://api.minimaxi.com/v1/chat/completions`,
 *    鉴权与响应格式和 DeepSeek 完全一致, 可以直接换 base_url + model。
 *
 * ⚠️ 注意 model 名不同:
 *      DeepSeek: "deepseek-chat"
 *      MiniMax : "MiniMax-Text-01"(或 abab6.5s-chat 等)
 *    所以 model 必须一起改, 不能只改 base_url。
 *
 * 优先读 LLM_*, 回退到旧的 DEEPSEEK_*(兼容存量部署)。
 */
export function llmConfig(env: LlmEnv): LlmConfig {
  const base = env.LLM_API_BASE || env.DEEPSEEK_API_BASE || "";
  const model = env.LLM_MODEL || env.DEEPSEEK_MODEL || "";
  const key = env.LLM_API_KEY || env.DEEPSEEK_API_KEY || "";
  return { base, model, key };
}

/**
 * 带重试的 fetch。
 *
 * ⚠️ miniflare 本地开发有个 keep-alive 连接复用 bug:
 *    同一个 origin 连续发请求时, **隔一次就死** ——
 *    实测 6 次连续 GET /health: 成功/失败/成功/失败/成功/失败,
 *    每次失败都是 "Network connection lost" (4ms 内失败, 不是超时)。
 *    加 200ms 间隔后 3 次全成功。
 *
 *    真 Cloudflare 上没有这个问题, 但重试是幂等的且便宜,
 *    统一加上能同时覆盖「本地 miniflare」和「生产偶发网络抖动」。
 */
export async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  attempts = 3,
  delayMs = 250
): Promise<T> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      if (i < attempts - 1) {
        await new Promise((r) => setTimeout(r, delayMs));
      }
    }
  }
  console.warn(`[fetch] ${attempts} 次重试仍失败:`, (lastErr as Error)?.message);
  throw lastErr;
}

/** OpenAI 兼容的 chat completion 请求体。 */
export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

/** chat completion 响应(只取用到的字段)。 */
export interface ChatCompletionResponse {
  choices: { message: { content: string } }[];
}

/**
 * 调用 LLM 的 chat completions 接口。
 *
 * @param cfg        端点配置
 * @param messages   对话消息
 * @param options    temperature / max_tokens / stream
 */
export async function chatCompletion(
  cfg: LlmConfig,
  messages: ChatMessage[],
  options: { temperature?: number; max_tokens?: number; stream?: boolean } = {}
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
      max_tokens: options.max_tokens ?? 1000,
      stream: options.stream ?? false,
    }),
  });
}
