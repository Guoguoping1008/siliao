/**
 * ① 法规知识库 —— 文档聚合单测
 *
 * 测的是**领域不变量**: 层级一致性、条文顺序。
 */

import { describe, it, expect } from "vitest";
import {
  sortArticlesByOrder,
  validateAggregation,
  type RegulationArticle,
  type RegulationChapter,
  type RegulationDocument,
} from "./regulation-document.aggregate";

const doc: RegulationDocument = {
  doc_id: "doc-1",
  title: "饲料和饲料添加剂管理条例",
};

const chapters: RegulationChapter[] = [
  { chapter_id: "c1", doc_id: "doc-1", number: "第一章", title: "总则", sort_order: 1 },
  { chapter_id: "c2", doc_id: "doc-1", number: "第二章", title: "登记", sort_order: 2 },
];

const articles: RegulationArticle[] = [
  { article_id: "a1", chapter_id: "c1", doc_id: "doc-1", number: "第一条", sort_order: 1 },
  { article_id: "a2", chapter_id: "c1", doc_id: "doc-1", number: "第二条", sort_order: 2 },
  { article_id: "a3", chapter_id: "c2", doc_id: "doc-1", number: "第三条", sort_order: 3 },
];

describe("validateAggregation", () => {
  it("一致的聚合无违规", () => {
    expect(validateAggregation(doc, chapters, articles)).toEqual([]);
  });

  it("条文 chapter_id 悬空 → 报错", () => {
    const bad: RegulationArticle[] = [
      ...articles,
      { article_id: "aX", chapter_id: "nope", doc_id: "doc-1", number: "第四条", sort_order: 4 },
    ];
    const errs = validateAggregation(doc, chapters, bad);
    expect(errs.length).toBe(1);
    expect(errs[0]).toContain("aX");
  });

  it("条文 doc_id 与聚合根不一致 → 报错", () => {
    const bad: RegulationArticle[] = [
      { article_id: "a1", chapter_id: "c1", doc_id: "other", number: "第一条", sort_order: 1 },
    ];
    const errs = validateAggregation(doc, chapters, bad);
    expect(errs.some((e) => e.includes("doc_id"))).toBe(true);
  });

  it("章节 doc_id 与聚合根不一致 → 报错", () => {
    const bad: RegulationChapter[] = [
      { chapter_id: "cX", doc_id: "other", number: "第九章", title: "X", sort_order: 9 },
    ];
    const errs = validateAggregation(doc, bad, []);
    expect(errs.length).toBe(1);
    expect(errs[0]).toContain("cX");
  });

  it("空聚合不报错", () => {
    expect(validateAggregation(doc, [], [])).toEqual([]);
  });
});

describe("sortArticlesByOrder", () => {
  it("按 sort_order 升序", () => {
    const shuffled: RegulationArticle[] = [articles[2], articles[0], articles[1]];
    expect(sortArticlesByOrder(shuffled).map((a) => a.article_id)).toEqual(["a1", "a2", "a3"]);
  });

  it("不修改原数组", () => {
    const shuffled: RegulationArticle[] = [articles[2], articles[0]];
    const before = [...shuffled];
    sortArticlesByOrder(shuffled);
    expect(shuffled).toEqual(before);
  });

  it("不能靠 article_id 字典序排(实测 95/529 章顺序会错)", () => {
    // 故意构造 article_id 字典序与原文顺序相反的情况
    const weird: RegulationArticle[] = [
      { article_id: "a9", chapter_id: "c1", doc_id: "doc-1", number: "第一条", sort_order: 1 },
      { article_id: "a1", chapter_id: "c1", doc_id: "doc-1", number: "第二条", sort_order: 2 },
    ];
    expect(sortArticlesByOrder(weird)[0].article_id).toBe("a9");
  });

  it("空数组返回空数组", () => {
    expect(sortArticlesByOrder([])).toEqual([]);
  });
});
