/**
 * ③ 问答 · 多轮会话服务单测
 *
 * 用假仓储 + 假检索 + 假 LLM, 测**编排顺序**与**指代消解的接线**。
 * 纯领域逻辑(指代消解规则)在 conversation-context.vo.test.ts 里测。
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { ConversationService, type ConversationStore } from "./conversation.service";
import type { ConversationContext } from "../../domain/inquiry/conversation-context.vo";
import type { Evidence } from "../../domain/inquiry/evidence.vo";
import { chatCompletion } from "../../interfaces/acl/llm.acl";

// ── 假 LLM ──
vi.mock("../../interfaces/acl/llm.acl", () => ({
  llmConfig: (env: any) => ({ apiBase: env.LLM_API_BASE ?? "", apiKey: env.LLM_API_KEY ?? "", model: env.LLM_MODEL ?? "m" }),
  chatCompletion: vi.fn(),
}));

const mockChat = vi.mocked(chatCompletion);

function evidence(n: number): Evidence {
  return {
    article_id: `art${n}`,
    chapter_id: `ch${n}`,
    doc_id: `doc${n}`,
    chapter_number: "第一章",
    chapter_title: "总则",
    article_number: `第${n}条`,
    title: `标题${n}`,
    excerpt: `这是第${n}条的原文摘录`,
  } as Evidence;
}

/** 内存版仓储。 */
function makeStore(): ConversationStore & { turns: ConversationContext["turns"] } {
  const store = {
    turns: [] as ConversationContext["turns"],
    async load(sessionId: string): Promise<ConversationContext | null> {
      if (!store.turns.length) return null;
      const entities = store.turns.flatMap((t) => t.entities ?? []);
      return { sessionId, turns: store.turns, entities };
    },
    async appendTurn(sessionId: string, turn: any) {
      store.turns.push({
        question: turn.question,
        answer: turn.answer,
        evidence: turn.evidence,
        entities: turn.entities,
      });
    },
    async clear() {
      store.turns = [];
    },
  };
  return store as any;
}

const llmEnv = {
  LLM_API_BASE: "https://example.invalid/v1",
  LLM_MODEL: "test-model",
  LLM_API_KEY: "k",
};

function okResponse(content: string) {
  return {
    ok: true,
    json: async () => ({ choices: [{ message: { content } }] }),
    text: async () => "",
  } as any;
}

describe("ConversationService", () => {
  beforeEach(() => {
    mockChat.mockReset();
  });

  it("新会话: 第一轮不做上下文补全", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    const r = await svc.ask({ sessionId: "s1", question: "维生素C在猪饲料的上限?" });

    expect(r.resolvedQuery).toBe("维生素C在猪饲料的上限?");
    expect(search).toHaveBeenCalledWith({ q: "维生素C在猪饲料的上限?" });
    expect(r.citations.length).toBe(1);
    expect(r.citations[0].valid).toBe(true);
  });

  it("✅ 第二轮追问: 指代消解补上上一轮的物质", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    await svc.ask({ sessionId: "s1", question: "维生素C在猪饲料的上限?" });
    const r2 = await svc.ask({ sessionId: "s1", question: "那鸡呢?" });

    // 检索 query 必须被补全
    expect(r2.resolvedQuery).toContain("维生素C");
    expect(r2.resolvedQuery).toContain("那鸡呢");
    // 第二轮调用时用的就是补全后的 query
    expect(search).toHaveBeenLastCalledWith({ q: r2.resolvedQuery });
  });

  it("✅ 历史进入 prompt(LLM 能看到上一轮问了什么)", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    await svc.ask({ sessionId: "s1", question: "维生素C在猪饲料的上限?" });
    await svc.ask({ sessionId: "s1", question: "那鸡呢?" });

    const calls = mockChat.mock.calls;
    const secondPrompt = calls[1]![1].find((m: any) => m.role === "user")!.content;
    expect(secondPrompt).toContain("对话历史");
    expect(secondPrompt).toContain("维生素C在猪饲料的上限?");
    expect(secondPrompt).toContain("那鸡呢?");
  });

  it("⚠️ 引用编号只能用本轮证据(历史不带 evidence)", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    await svc.ask({ sessionId: "s1", question: "维生素C在猪饲料的上限?" });
    await svc.ask({ sessionId: "s1", question: "那鸡呢?" });

    const calls = mockChat.mock.calls;
    const secondUser = calls[1]![1].find((m: any) => m.role === "user")!.content;
    // 历史里不该出现上一轮的证据编号
    const historyPart = secondUser.split("# 本轮检索证据")[0];
    expect(historyPart).not.toContain("[1] ");
  });

  it("⚠️ 引用超出本轮证据 → 标为 invalid(不静默放过)", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1] 和 [5]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    const r = await svc.ask({ sessionId: "s1", question: "维生素C在猪的上限?" });
    expect(r.citations.length).toBe(2);
    expect(r.citations.find((c) => c.ref === 1)?.valid).toBe(true);
    expect(r.citations.find((c) => c.ref === 5)?.valid).toBe(false);
  });

  it("LLM 失败 → 返回空答案,不崩", async () => {
    mockChat.mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "boom",
    } as any);
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    const r = await svc.ask({ sessionId: "s1", question: "维生素C?" });
    expect(r.answer).toBe("");
    expect(r.citations).toEqual([]);
  });

  it("clear 清空会话", async () => {
    mockChat.mockResolvedValue(okResponse("答案 [1]"));
    const store = makeStore();
    const search = vi.fn().mockResolvedValue({ hits: [evidence(1)], query: "q" });
    const svc = new ConversationService(store, { search }, llmEnv);

    await svc.ask({ sessionId: "s1", question: "维生素C在猪的上限?" });
    expect(store.turns.length).toBe(1);
    await svc.clear("s1");
    expect(store.turns.length).toBe(0);
  });
});
