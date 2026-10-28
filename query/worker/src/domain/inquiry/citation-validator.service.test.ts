/**
 * ③ 问答 —— 引用校验器单测
 *
 * 这是 ADR-004 M1 的核心交付: 领域层纯函数, 零 I/O, 100% 可测。
 *
 * 测的是**业务规则**, 不是实现细节:
 *   - 引用号 N 对应证据第 N 条
 *   - N 越界 → valid: false (LLM 编造)
 *   - 无引用 → 不是「全部有效」
 */

import { describe, it, expect } from "vitest";
import {
  extractCitationRefs,
  validateCitations,
  hasOnlyValidCitations,
} from "./citation-validator.service";
import type { Evidence } from "./evidence.vo";

function ev(n: number): Evidence {
  return {
    article_id: `art-${n}`,
    chapter_id: `chap-${n}`,
    doc_id: "doc-1",
    chapter_title: `第${n}章`,
    chapter_number: `第${n}章`,
    article_number: `第${n}条`,
    title: `标题${n}`,
    excerpt: `正文${n}`,
  };
}

const HITS: Evidence[] = [ev(1), ev(2), ev(3)];

describe("extractCitationRefs", () => {
  it("提取单个引用", () => {
    expect(extractCitationRefs("依据 [1] 得出结论")).toEqual([1]);
  });

  it("提取多个引用并去重", () => {
    expect(extractCitationRefs("见 [1] 与 [3] 与 [1]")).toEqual([1, 3]);
  });

  it("结果升序排列", () => {
    expect(extractCitationRefs("[5] [2] [9]")).toEqual([2, 5, 9]);
  });

  it("无引用返回空数组", () => {
    expect(extractCitationRefs("没有任何引用的答案")).toEqual([]);
  });

  it("空字符串返回空数组", () => {
    expect(extractCitationRefs("")).toEqual([]);
  });

  it("忽略非数字方括号", () => {
    expect(extractCitationRefs("见 [附录] 和 [abc]")).toEqual([]);
  });

  it("支持两位数引用", () => {
    expect(extractCitationRefs("[12] [3]")).toEqual([3, 12]);
  });
});

describe("validateCitations", () => {
  it("有效引用带全部元数据", () => {
    const out = validateCitations("依据 [1]", HITS);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      ref: 1,
      article_id: "art-1",
      article_number: "第1条",
      chapter_title: "第1章",
      valid: true,
    });
  });

  it("越界引用标记为无效", () => {
    const out = validateCitations("依据 [99]", HITS);
    expect(out).toHaveLength(1);
    expect(out[0].valid).toBe(false);
    expect(out[0].article_id).toBeUndefined();
  });

  it("部分有效部分无效", () => {
    const out = validateCitations("[1] 和 [99]", HITS);
    expect(out).toHaveLength(2);
    expect(out[0].valid).toBe(true);
    expect(out[1].valid).toBe(false);
  });

  it("输出按引用号升序", () => {
    const out = validateCitations("[3] [1] [2]", HITS);
    expect(out.map((c) => c.ref)).toEqual([1, 2, 3]);
  });

  it("无引用返回空数组", () => {
    expect(validateCitations("没有引用", HITS)).toEqual([]);
  });

  it("证据为空时所有引用无效", () => {
    const out = validateCitations("[1]", []);
    expect(out[0].valid).toBe(false);
  });

  it("保留 excerpt 供前端渲染引用卡片", () => {
    const out = validateCitations("[2]", HITS);
    expect(out[0].excerpt).toBe("正文2");
  });
});

describe("hasOnlyValidCitations", () => {
  it("全部引用有效 → true", () => {
    expect(hasOnlyValidCitations("依据 [1] [2]", HITS)).toBe(true);
  });

  it("存在编造引用 → false", () => {
    expect(hasOnlyValidCitations("依据 [1] [99]", HITS)).toBe(false);
  });

  it("无引用 → false (无依据的答案不允许发布)", () => {
    expect(hasOnlyValidCitations("没有任何依据", HITS)).toBe(false);
  });

  it("空答案 → false", () => {
    expect(hasOnlyValidCitations("", HITS)).toBe(false);
  });
});
