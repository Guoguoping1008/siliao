/**
 * 问答领域服务 —— 应用层
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * 一次问答 = 检索 → 组装证据 → LLM 生成 → 引用校验。
 *
 * 这个服务**不拥有任何业务数据**, 它只调用 ① 检索 与 LLM ACL,
 * 并用 ③ 的领域服务校验引用。
 */

import { buildRagPrompt } from "./prompt-builder";
import { validateCitations } from "../../domain/inquiry/citation-validator.service";
import type { Citation, Evidence } from "../../domain/inquiry/evidence.vo";
import { chatCompletion, llmConfig, type LlmEnv } from "../../interfaces/acl/llm.acl";

/** 检索端口(由 infrastructure 的 HybridRetriever 实现)。 */
export interface EvidenceRetriever {
  search(params: { q: string }): Promise<{ hits: Evidence[]; query: string }>;
}

/** 问答服务。 */
export class InquiryService {
  constructor(
    private readonly retriever: EvidenceRetriever,
    private readonly llmEnv: LlmEnv
  ) {}

  /**
   * 同步问答。
   *
   * @returns 答案 + 引用 + 检索证据 + 耗时
   */
  async ask(question: string): Promise<{
    question: string;
    answer: string;
    citations: Citation[];
    retrieval: Evidence[];
    elapsed_ms: number;
  } | { error: string; status?: number; body?: string }> {
    const t0 = Date.now();
    const { hits } = await this.retriever.search({ q: question });
    const { systemPrompt, userPrompt } = buildRagPrompt(question, hits);

    const llm = llmConfig(this.llmEnv);
    const resp = await chatCompletion(
      llm,
      [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      { temperature: 0.2, max_tokens: 1000, stream: false }
    );

    if (!resp.ok) return { error: "llm_error", status: resp.status, body: await resp.text() };
    const data = (await resp.json()) as { choices: { message: { content: string } }[] };
    const answer = data.choices[0].message.content;
    const citations = validateCitations(answer, hits);

    return {
      question,
      answer,
      citations,
      retrieval: hits.slice(0, 8),
      elapsed_ms: Date.now() - t0,
    };
  }

  /**
   * 流式问答 —— 返回 LLM 的原始 Response, 由调用方透传 SSE。
   *
   * 引用校验在流结束时做(需要完整答案), 所以调用方拿到 Response 后
   * 还要自己累积 delta 并调用 `validateCitations`。
   *
   * 为避免重复实现, 这里额外暴露 `buildPrompt` 与 `validate` 两个方法。
   */
  buildPrompt(question: string, hits: Evidence[]) {
    return buildRagPrompt(question, hits);
  }

  validate(answer: string, hits: Evidence[]): Citation[] {
    return validateCitations(answer, hits);
  }
}
