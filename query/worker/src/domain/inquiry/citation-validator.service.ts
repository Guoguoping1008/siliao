/**
 * 引用校验器 (CitationValidator) —— 领域服务
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ## 为什么这是**领域服务**而不是工具函数
 *
 * 「答案里的每条引用都必须能落到真实条文上」是**业务规则**, 不是技术细节 ——
 * 它来自架构方案文档的「合规优先」原则:
 *
 *   「涉及监管结论的输出必须可溯源(条款号+原文), 禁止无依据作答」
 *
 * 这个判定决定了一个答案**能不能对外发布**。所以它属于领域层,
 * 且必须是纯函数 —— 不碰网络、不碰数据库, 可被完整单测覆盖。
 *
 * ## 纯度保证 (ADR-004 R3/R5)
 *
 * - 纯 TS, 零框架依赖
 * - 无 I/O, 无 fetch()
 * - 不 import Workers / D1 类型
 */

import type { Citation, Evidence } from "./evidence.vo";

/** 答案里引用标记的格式: `[1]` `[3]`。1-based。 */
const CITATION_PATTERN = /\[(\d+)\]/g;

/**
 * 从答案文本中提取所有引用编号。
 *
 * 去重 + 升序。同一个编号被引用多次只算一次。
 */
export function extractCitationRefs(answer: string): number[] {
  if (!answer) return [];
  const nums = new Set<number>();
  for (const m of answer.matchAll(CITATION_PATTERN)) {
    nums.add(parseInt(m[1], 10));
  }
  return [...nums].sort((a, b) => a - b);
}

/**
 * 校验答案中的引用是否与检索证据对账。
 *
 * 规则:
 *   - 引用号 N 对应证据列表的第 N 条(1-based)
 *   - N 超出证据范围 → `valid: false`(LLM 编造)
 *   - 答案没有任何引用 → 返回空数组(不是错误, 由调用方决定是否可接受)
 *
 * ⚠️ 元数据**直接透传** Evidence 的原值(含 null), 不做 String() 转换 ——
 *    原实现就是直接赋值, 转成字符串会让空值变成 "null"。
 *
 * @param answer  LLM 生成的答案原文
 * @param hits    检索证据(顺序即引用号的顺序)
 */
export function validateCitations(answer: string, hits: Evidence[]): Citation[] {
  const refs = extractCitationRefs(answer);
  const out: Citation[] = [];

  for (const n of refs) {
    const hit = hits[n - 1];
    if (hit) {
      out.push({
        ref: n,
        article_id: hit.article_id,
        chapter_id: hit.chapter_id,
        doc_id: hit.doc_id,
        chapter_number: hit.chapter_number,
        chapter_title: hit.chapter_title,
        article_number: hit.article_number,
        title: hit.title,
        excerpt: hit.excerpt,
        valid: true,
      });
    } else {
      out.push({ ref: n, valid: false });
    }
  }

  return out;
}

/**
 * 判定一个答案是否**全部引用有效**。
 *
 * 这是「能不能对外发布」的闸门:
 *   - 无引用 → false(没有依据的答案不允许发布)
 *   - 有编造引用 → false
 *   - 全部引用有效 → true
 *
 * 注: 与旧实现相比, 这里**新增**了「无引用即不合格」的判定。
 * 旧实现 `validateCitations` 只是把无效引用标出来, 由前端决定怎么显示。
 * 本函数是显式的**发布闸门**, 供 M2 的合规校验与未来的审核工作流使用。
 * 现有 QA 接口行为不变(仍调用 validateCitations 逐条标注)。
 */
export function hasOnlyValidCitations(answer: string, hits: Evidence[]): boolean {
  const citations = validateCitations(answer, hits);
  if (citations.length === 0) return false;
  return citations.every((c) => c.valid);
}
