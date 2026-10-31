/**
 * 多轮会话 —— 应用层服务
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ## 编排流程
 *
 *   1. 载入会话上下文(实体 + 历史轮次)
 *   2. **指代消解** —— 用上一轮实体补全当前问句, 得到检索 query
 *   3. 检索(query = 补全后的)
 *   4. 拼 prompt(带历史轮次)
 *   5. LLM 生成
 *   6. 引用校验(仍然是**本轮**的证据)
 *   7. 落库(本轮的实体 + 证据 + query)
 *
 * ⚠️ **本层不做业务判断** —— 指代消解的规则在
 *    domain/inquiry/conversation-context.vo.ts(纯函数, 可单测)。
 */

import {
  extractEntities,
  mergeEntities,
  recentTurns,
  resolveContext,
} from "../../domain/inquiry/conversation-context.vo";
import type { ConversationContext } from "../../domain/inquiry/conversation-context.vo";
import { buildConversationPrompt } from "./prompt-builder";
import { validateCitations } from "../../domain/inquiry/citation-validator.service";
import type { Citation, Evidence } from "../../domain/inquiry/evidence.vo";
import { chatCompletion, llmConfig, type LlmEnv } from "../../interfaces/acl/llm.acl";

/** 会话仓储端口(由 infrastructure 实现)。 */
export interface ConversationStore {
  load(sessionId: string): Promise<ConversationContext | null>;
  appendTurn(
    sessionId: string,
    turn: {
      question: string;
      answer: string;
      evidence: Evidence[];
      entities: ReturnType<typeof extractEntities>;
      resolvedQuery: string;
    }
  ): Promise<void>;
  clear(sessionId: string): Promise<void>;
}

/** 检索端口(与单轮问答共用)。 */
export interface EvidenceRetriever {
  search(params: { q: string }): Promise<{ hits: Evidence[]; query: string }>;
}

/** 多轮问答请求。 */
export interface ConversationRequest {
  sessionId: string;
  question: string;
}

/** 多轮问答响应。 */
export interface ConversationResponse {
  sessionId: string;
  question: string;
  /** 实际用于检索的 query(可能含上下文补全) —— 前端可展示以便用户理解。 */
  resolvedQuery: string;
  answer: string;
  citations: Citation[];
  retrieval: Evidence[];
  elapsed_ms: number;
}

/** 多轮会话服务。 */
export class ConversationService {
  constructor(
    private readonly store: ConversationStore,
    private readonly retriever: EvidenceRetriever,
    private readonly llmEnv: LlmEnv
  ) {}

  async ask(req: ConversationRequest): Promise<ConversationResponse> {
    const t0 = Date.now();
    const question = (req.question || "").trim();
    const sessionId = req.sessionId;

    // 1. 载入上下文(新会话 → 空上下文)
    const ctx: ConversationContext =
      (await this.store.load(sessionId)) ?? {
        sessionId,
        turns: [],
        entities: [],
      };

    // 2. 指代消解 → 检索 query
    const resolvedQuery = resolveContext(ctx.entities, question);

    // 3. 检索
    const { hits } = await this.retriever.search({ q: resolvedQuery });

    // 4. 拼 prompt(带历史)
    const history = recentTurns(ctx).map((t) => ({
      question: t.question,
      answer: t.answer,
    }));
    const { systemPrompt, userPrompt } = buildConversationPrompt(
      question,
      hits,
      history
    );

    // 5. LLM 生成
    const llm = llmConfig(this.llmEnv);
    const resp = await chatCompletion(
      llm,
      [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      { temperature: 0.2, max_tokens: 1000, stream: false }
    );

    if (!resp.ok) {
      return {
        sessionId,
        question,
        resolvedQuery,
        answer: "",
        citations: [],
        retrieval: [],
        elapsed_ms: Date.now() - t0,
      };
    }
    const data = (await resp.json()) as { choices: { message: { content: string } }[] };
    const answer = data.choices[0].message.content;

    // 6. 引用校验 —— 仍然是**本轮**证据
    const citations = validateCitations(answer, hits);

    // 7. 落库
    const entities = mergeEntities(ctx.entities, extractEntities(question));
    await this.store.appendTurn(sessionId, {
      question,
      answer,
      evidence: hits,
      entities: extractEntities(question),
      resolvedQuery,
    });

    return {
      sessionId,
      question,
      resolvedQuery,
      answer,
      citations,
      retrieval: hits.slice(0, 8),
      elapsed_ms: Date.now() - t0,
    };
  }

  /** 清空会话。 */
  async clear(sessionId: string): Promise<void> {
    await this.store.clear(sessionId);
  }
}
