/**
 * 会话上下文 —— 领域层值对象
 *
 * 上下文: ③ 问答 Inquiry (支撑域)
 *
 * ## 为什么需要
 *
 * 用户问「维生素C在猪饲料中的使用量上限是多少？」, 接着问「那鸡呢?」——
 * 第二句里没有主语。没有会话状态, 检索会拿「那鸡呢」去查, 召回一堆无关条文。
 *
 * ## 核心机制: 指代消解
 *
 * 从上一轮识别出的实体 + 当前问句, 构造**补充检索 query**:
 *
 *   上一轮实体: [「维生素C」]
 *   当前问句:   「那鸡呢?」          → 不含「维生素C」
 *   补充后:     「维生素C 那鸡呢?」   → 检索能召回正确的条文
 *
 * ⚠️ **纯度保证** (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

import type { Evidence } from "./evidence.vo";

/** 从一轮问答里识别出的实体。 */
export interface ExtractedEntities {
  /** 物质名(如「维生素C」「饲料添加剂」)。 */
  substance: string;
  /** 动物种类(如「猪」「家禽」)。 */
  species?: string | null;
}

/** 一轮问答的记录。 */
export interface ConversationTurn {
  /** 用户问的原文。 */
  question: string;
  /** LLM 答的原文。 */
  answer: string;
  /** 本轮检索到的证据。 */
  evidence?: Evidence[];
  /** 本轮识别出的实体(供下一轮做指代消解)。 */
  entities?: ExtractedEntities[];
}

/** 会话上下文。 */
export interface ConversationContext {
  sessionId: string;
  /** 历轮记录(时间正序)。 */
  turns: ConversationTurn[];
  /** 累计识别出的实体(按出现顺序, 后出现的覆盖先出现的)。 */
  entities: ExtractedEntities[];
}

// ─────────────────────────────────────────────────────────────
// 实体识别
// ─────────────────────────────────────────────────────────────

/**
 * 动物种类词表 —— 语料里常见的动物名。
 *
 * ⚠️ 按长度降序匹配 —— 「肉用鸡」必须优先于「鸡」, 否则会截错。
 */
export const SPECIES_TERMS: string[] = [
  "肉用鸡", "蛋用鸡", "后备母猪", "哺乳母猪", "妊娠母猪", "生长猪", "育肥猪",
  "育成猪", "种猪", "仔猪", "乳猪", "后备猪",
  "肉鸡", "蛋鸡", "肉鸭", "蛋鸭", "种鸡", "雏鸡", "青年鸡", "鹌鹑",
  "犊牛", "奶牛", "肉牛", "育成牛", "黄牛", "水牛",
  "罗非鱼", "虹鳟鱼", "鲶鱼", "青鱼", "草鱼", "鲤鱼", "鲫鱼", "鳙鱼",
  "虾类", "蟹类", "贝类", "其他鱼", "海参", "扇贝", "乌贼",
  "水产养殖动物", "畜禽", "家禽", "猪", "牛", "羊", "马", "驴", "兔",
  "鸡", "鸭", "鹅", "狗", "犬", "猫",
];

/**
 * 物质名候选 —— 从问句里识别「查的是什么」。
 *
 * ⚠️ **刻意保守**: 只认**明确出现在问句里**的知名物质。
 *    宁可漏识别(→ 退化成普通单轮问答), 不可错识别
 *    (→ 把不相关的东西塞进下一轮 query, 污染检索)。
 */
export const SUBSTANCE_TERMS: string[] = [
  "维生素C", "抗坏血酸", "维生素D3", "维生素D2", "维生素E", "维生素A",
  "维生素B1", "维生素B2", "维生素B6", "维生素B12", "烟酰胺", "烟酸",
  "生物素", "肌醇", "肉碱", "赖氨酸", "蛋氨酸", "苏氨酸", "色氨酸",
  "蛋氨酸羟基类似物", "植酸酶", "木聚糖酶", "纤维素酶", "淀粉酶",
  "甜菜碱", "氯化胆碱", "叶酸", "泛酸钙", "核黄素",
  "饲料添加剂", "饲料原料", "添加剂品种目录", "生产许可证", "批准文号",
  "饲料标签", "标签标识", "原料目录", "卫生标准", "饲料标准",
  "转基因", "兽药", "进口登记",
];

/** 从文本里找出出现的动物种类(按长度降序, 去重)。 */
export function findSpeciesTerms(text: string): string[] {
  if (!text) return [];
  const found = new Set<string>();
  for (const term of SPECIES_TERMS) {
    if (text.includes(term)) found.add(term);
  }
  // 「猪」与「肉猪」会同时命中 —— 保留更长的那个, 删掉被包含的短的
  const list = [...found].sort((a, b) => b.length - a.length);
  const kept: string[] = [];
  for (const t of list) {
    if (!kept.some((k) => k.includes(t))) kept.push(t);
  }
  return kept;
}

/** 从文本里找出出现的物质名。 */
export function findSubstanceTerms(text: string): string[] {
  if (!text) return [];
  const found = new Set<string>();
  for (const term of SUBSTANCE_TERMS) {
    if (text.includes(term)) found.add(term);
  }
  return [...found].sort((a, b) => b.length - a.length);
}

/**
 * 从一轮问答里抽取实体。
 *
 * ⚠️ **只从「用户问句」里抽**, 不从 LLM 答案里抽 ——
 *    答案里出现「维生素C」可能是复述, 也可能是 LLM 自己引入的。
 *    问句才是用户真正在问的东西。
 */
export function extractEntities(question: string): ExtractedEntities[] {
  const subs = findSubstanceTerms(question);
  const species = findSpeciesTerms(question);
  const out: ExtractedEntities[] = [];
  for (const s of subs) {
    out.push({ substance: s, species: species[0] ?? null });
  }
  // 没有物质名但有动物 —— 也记一条, 便于「那鸡呢」继承物质
  if (!subs.length && species.length) {
    out.push({ substance: "", species: species[0] });
  }
  return out;
}

// ─────────────────────────────────────────────────────────────
// 指代消解
// ─────────────────────────────────────────────────────────────

/**
 * 构造下一轮的检索 query。
 *
 * ## 规则
 *
 * 1. 当前问句已含任一已知物质 → **不补**(用户已经换了话题)
 * 2. 当前问句含动物但不含物质 → 补上**上一轮的物质**
 *    (「那鸡呢?」→ 「维生素C 那鸡呢?」)
 * 3. 当前问句既无物质也无动物 → 补上**上一轮的动物**
 *    (「那上限呢?」→ 「维生素C 那上限呢?」)
 * 4. 当前问句含物质 → 不补
 * 5. 没有历史实体 → 不补
 *
 * ⚠️ **只补一轮**, 不累加 —— 补多了会把 query 撑爆, 稀释语义。
 */
export function resolveContext(
  previousEntities: ExtractedEntities[],
  currentQuestion: string
): string {
  const q = (currentQuestion || "").trim();
  if (!q) return q;
  if (!previousEntities.length) return q;

  // 规则 1/4: 当前问句已含物质 → 不补
  const currentSubs = findSubstanceTerms(q);
  if (currentSubs.length) return q;

  const currentSpecies = findSpeciesTerms(q);

  // 找上一轮最后一个「有物质名」的实体
  const withSubstance = [...previousEntities].reverse().find((e) => e.substance);

  // 规则 2: 含动物不含物质 → 补上一轮的物质
  if (currentSpecies.length && withSubstance) {
    return `${withSubstance.substance} ${q}`;
  }

  // 规则 3: 什么都不含 → 补上一轮的物质(若没有则补动物)
  if (!currentSpecies.length) {
    if (withSubstance) return `${withSubstance.substance} ${q}`;
    const last = [...previousEntities].reverse()[0];
    if (last?.species) return `${last.species} ${q}`;
  }

  return q;
}

/**
 * 合并两轮的实体(新一轮的覆盖旧的)。
 *
 * ⚠️ 同一物质重复出现时, **只保留最新的一条** —— 它的 species 可能更准确
 *    (「维生素C 在猪…」之后问「那鸡呢」→ 鸡的信息应该被记下来)。
 */
export function mergeEntities(
  previous: ExtractedEntities[],
  current: ExtractedEntities[]
): ExtractedEntities[] {
  const merged = [...previous];
  for (const e of current) {
    if (!e.substance && !e.species) continue;
    const idx = merged.findIndex((m) => m.substance === e.substance);
    if (idx >= 0) {
      merged[idx] = e;
    } else {
      merged.push(e);
    }
  }
  return merged;
}

/**
 * 从历史轮次里取最近 N 轮, 供拼 prompt 用。
 *
 * ⚠️ **带上历史问题的原文** —— LLM 需要看到「第 1 轮问了什么」
 *    才能理解「第 2 轮的『那鸡呢』指什么」。
 */
export function recentTurns(
  ctx: ConversationContext,
  maxTurns = 3
): ConversationTurn[] {
  return ctx.turns.slice(-maxTurns);
}
