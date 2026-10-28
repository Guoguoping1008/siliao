/**
 * 应用层 —— 问答服务单测
 *
 * 用可注入的 mock 测编排逻辑: 检索 → 组装 → 引用校验。
 */

import { describe, it, expect } from "vitest";
import { InquiryService, type EvidenceRetriever } from "./inquiry.service";
import { buildRagPrompt } from "./prompt-builder";
import type { Evidence } from "../../domain/inquiry/evidence.vo";

function hit(n: number): Evidence {
  return {
    article_id: `art-${n}`,
    chapter_number: `第${n}章`,
    chapter_title: `第${n}章`,
    article_number: `第${n}条`,
    excerpt: `正文${n}`,
  };
}

describe("buildRagPrompt", () => {
  it("证据最多取 8 条", () => {
    const hits = Array.from({ length: 20 }, (_, i) => hit(i + 1));
    const { userPrompt } = buildRagPrompt("问题", hits);
    expect(userPrompt).toContain("[8]");
    expect(userPrompt).not.toContain("[9]");
  });

  it("引用编号从 1 开始", () => {
    const { userPrompt } = buildRagPrompt("问题", [hit(1), hit(2)]);
    expect(userPrompt).toContain("[1]");
    expect(userPrompt).toContain("[2]");
  });

  it("无证据时标注「无相关证据」", () => {
    const { userPrompt } = buildRagPrompt("问题", []);
    expect(userPrompt).toContain("(无相关证据)");
  });

  it("system prompt 强制「未找到则明说」", () => {
    const { systemPrompt } = buildRagPrompt("问题", []);
    expect(systemPrompt).toContain("未找到相关规定");
  });

  it("system prompt 要求用 [N] 格式引用", () => {
    const { systemPrompt } = buildRagPrompt("问题", []);
    expect(systemPrompt).toContain("[N]");
  });

  it("用户问题出现在 prompt 里", () => {
    const { userPrompt } = buildRagPrompt("维生素C能用吗", []);
    expect(userPrompt).toContain("维生素C能用吗");
  });
});

describe("InquiryService", () => {
  const retriever: EvidenceRetriever = {
    search: async () => ({ hits: [hit(1), hit(2)], query: "q" }),
  };

  it("validate 委托给领域服务", () => {
    const svc = new InquiryService(retriever, {});
    const out = svc.validate("依据 [1]", [hit(1)]);
    expect(out).toHaveLength(1);
    expect(out[0].valid).toBe(true);
  });

  it("buildPrompt 返回 system/user 两段", () => {
    const svc = new InquiryService(retriever, {});
    const p = svc.buildPrompt("问题", [hit(1)]);
    expect(p.systemPrompt).toContain("检索助手");
    expect(p.userPrompt).toContain("问题");
  });
});
