/**
 * 接口层 —— 防腐层单测
 *
 * ACL 是外部系统的边界。测的重点是:
 *   - 端点解析(provider 无关, MiniMax/DeepSeek 都能用)
 *   - 正文清洗(markdown → 可读文本)
 *   - R2 key 编码
 */

import { describe, it, expect } from "vitest";
import { llmConfig } from "./llm.acl";
import { plainExcerpt, r2Key } from "./regulation.acl";

describe("llmConfig", () => {
  it("优先读 LLM_* 变量", () => {
    const cfg = llmConfig({
      LLM_API_BASE: "https://api.minimaxi.com/v1",
      LLM_MODEL: "MiniMax-Text-01",
      LLM_API_KEY: "k1",
      DEEPSEEK_API_BASE: "https://api.deepseek.com/v1",
      DEEPSEEK_MODEL: "deepseek-chat",
      DEEPSEEK_API_KEY: "k2",
    });
    expect(cfg.base).toBe("https://api.minimaxi.com/v1");
    expect(cfg.model).toBe("MiniMax-Text-01");
    expect(cfg.key).toBe("k1");
  });

  it("回退到 DEEPSEEK_* 变量(兼容存量部署)", () => {
    const cfg = llmConfig({
      DEEPSEEK_API_BASE: "https://api.deepseek.com/v1",
      DEEPSEEK_MODEL: "deepseek-chat",
      DEEPSEEK_API_KEY: "k2",
    });
    expect(cfg.base).toBe("https://api.deepseek.com/v1");
    expect(cfg.model).toBe("deepseek-chat");
    expect(cfg.key).toBe("k2");
  });

  it("缺配置返回空串而不是 undefined", () => {
    const cfg = llmConfig({});
    expect(cfg.base).toBe("");
    expect(cfg.model).toBe("");
    expect(cfg.key).toBe("");
  });
});

describe("plainExcerpt", () => {
  it("去掉标题标记", () => {
    expect(plainExcerpt("### 第三条")).toBe("第三条");
  });

  it("去掉表格分隔行", () => {
    expect(plainExcerpt("|---|:--:|")).toBe("");
  });

  it("去掉行内加粗/代码标记", () => {
    expect(plainExcerpt("**粗体**和`代码`")).toBe("粗体和代码");
  });

  it("链接只留文字", () => {
    expect(plainExcerpt("见[原文](http://x.com)")).toBe("见原文");
  });

  it("保留换行(不能压成一行)", () => {
    expect(plainExcerpt("第一行\n\n第二行")).toBe("第一行\n\n第二行");
  });

  it("压缩连续空行", () => {
    expect(plainExcerpt("A\n\n\n\nB")).toBe("A\n\nB");
  });

  it("超长截断加省略号", () => {
    const out = plainExcerpt("x".repeat(1000), 100);
    expect(out.length).toBeLessThanOrEqual(101);
    expect(out.endsWith("…")).toBe(true);
  });

  it("空输入返回空串", () => {
    expect(plainExcerpt("")).toBe("");
  });
});

describe("r2Key", () => {
  it("完整 key 直接逐段 encode", () => {
    expect(r2Key("a/b/c.md", "doc", "articles")).toBe("a/b/c.md");
  });

  it("中文 key 被 encode", () => {
    expect(r2Key("第一章/总则.md", "doc", "chapters")).toBe(
      "%E7%AC%AC%E4%B8%80%E7%AB%A0/%E6%80%BB%E5%88%99.md"
    );
  });

  it("缺 key 时用 fallback 拼目录", () => {
    expect(r2Key(null, "doc1", "articles")).toBe("doc1/articles/");
  });

  it("纯 ASCII key 是幂等的", () => {
    expect(r2Key("a/b.md", "doc", "articles")).toBe("a/b.md");
  });
});
