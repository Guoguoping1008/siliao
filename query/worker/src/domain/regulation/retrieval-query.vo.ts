/**
 * 检索查询切分 —— 领域层纯逻辑
 *
 * 上下文: ① 法规知识库 Regulation 的检索子域
 *
 * 纯函数, 不碰数据库。gram 切分 + FTS5 表达式构造都是**纯领域逻辑**,
 * 放在 domain 层可以直接单测, 不用起 D1。
 *
 * ⚠️ 纯度保证 (ADR-004 R3/R5): 零框架依赖, 零 I/O, 无 fetch()。
 */

/** 纯中文 2 字 query 的判定。 */
export const CJK_2CHAR_RE = /^[\u4E00-\u9FFF]{2}$/;

/**
 * 2 字 gram 补后缀用的字符集。
 *
 * ⚠️ **必须包含空格**: 章节名注入文本时是「第一章 总则 标题...」,
 * 「总则 」(含尾随空格)才是真实存在的 3-gram。
 * 只用汉字后缀时「总则」这类章节名 query 会 **0 命中**(实测 0 → 165)。
 *
 * ⚠️ 每个 phrase 必须**加引号**: 否则空格会被当成 FTS5 的 AND/OR 运算符,
 * 整个 MATCH 表达式语义错乱。
 */
const SUFFIXES = [
  " ",
  "\u7684", // 的
  "\u6761", // 条
  "\u89c4", // 规
  "\u5b9a", // 定
  "\u5236", // 制
  "\u6cd5", // 法
  "\u7406", // 理
  "\u7ae0", // 章
  "\u5e94", // 应
  "\u548c", // 和
];

/**
 * 中文停用 bigram —— 这些是虚词组合, 检索价值低。
 */
export const STOP_BIGRAMS = new Set([
  "什么", "如何", "哪些", "是否", "需要", "应该", "可以", "进行", "相关",
  "规定", "的话", "一个", "我们", "他们", "这个", "那个", "因为", "所以",
  "但是", "如果", "以及", "对于", "关于", "怎样", "多少", "为何",
  "有无", "几个", "哪种",
]);

/**
 * 把 query 切成检索用的 term 列表。
 *
 * - 中文段 → 重叠 bigram (2 字)
 * - 英文/数字 → 整词 (≥2 字符)
 * - 单个汉字 → 保留(单字有时是有意义的, 如「鱼」)
 * - 去停用词 + 去重保序
 */
export function queryTermGrams(q: string): string[] {
  const out: string[] = [];
  const push = (s: string) => {
    if (!s) return;
    if (out.includes(s)) return;
    out.push(s);
  };

  for (const w of q.match(/[A-Za-z0-9]+/g) ?? []) {
    if (w.length >= 2) push(w);
  }
  for (const seg of q.match(/[\u4E00-\u9FFF]+/g) ?? []) {
    if (seg.length === 1) {
      push(seg);
      continue;
    }
    for (let i = 0; i < seg.length - 1; i++) {
      const bg = seg.slice(i, i + 2);
      if (STOP_BIGRAMS.has(bg)) continue;
      push(bg);
    }
  }
  return out;
}

/**
 * gram → FTS5 MATCH 表达式 (2 字要 padding 成 3 字 phrase)。
 *
 * trigram 分词器要求**连续 3 个字符**, 2 字 gram 直接 MATCH 必然 0 命中。
 */
export function gramExpr(gram: string): string {
  if (gram.length === 2) {
    return SUFFIXES.map((suf) => `"${gram}${suf}"`).join(" OR ");
  }
  return `"${gram}"`;
}

/**
 * FTS5 trigram 对 query 不要求 phrase 包裹(只要 ≥3 字子串匹配即可),
 * 但要做基本清理: 去控制字符、长度截断、避免用户输入里有 FTS5 语法符号。
 */
export function escapeFts(s: string): string {
  if (!s) return "";
  const cleaned = s.replace(/[\x00-\x1f]/g, " ").trim().slice(0, 64);
  if (!cleaned) return "";
  // 仅对纯中文 2 字 query 加 padding, 避免破坏英文/数字 query
  if (CJK_2CHAR_RE.test(cleaned)) {
    return SUFFIXES.map((suf) => `"${cleaned}${suf}"`).join(" OR ");
  }
  return cleaned;
}

/**
 * RRF (Reciprocal Rank Fusion) 常数 —— 原 RRF 论文推荐值 K=60。
 */
export const RRF_K = 60;

/**
 * 标题加权系数。
 *
 * 查询往往直接点名法规(「新兽药注册办法」就是文件名), 标题命中是强信号。
 */
export const TITLE_BOOST = 3.0;

/**
 * 单个 gram 的召回条数上限。
 */
export const GRAM_TOP_N = 30;

/**
 * 融合两路召回: FTS5 与 bge-m3。
 *
 * ⚠️ **两路的分数量纲必须先归一化**。
 *    gram 路径的 ftsScore 是「A 档 1000+ / B 档 RRF ~0.05」的混合值,
 *    而 bge 的贡献是 1/(K+rank) ~ 0.005 —— 差 3~4 个数量级。
 *    直接相加再 slice, 结果是 **bge 的命中全被挤出 top20**
 *    (实测: bge 自己的 top20 有 20 条, 最终结果里 0 条带 bge_rank)。
 *
 * 对策: 每路各自算 RRF 分(量纲一致, 都是 1/(K+rank) 量级), 再按权重相加。
 *
 * ⚠️ 两路权重必须**相等**(1.0 : 1.0):
 *   - bge 权重太小 → 它的命中全被 FTS5 挤出 top20
 *   - bge 权重太大 → 稀释「精确短语」query 的命中
 *   实测扫参(evals/eval_minimax.py):
 *     FTS5 only  → recall@10 50.0% / MRR 0.544 / 业务 MRR 0.488
 *     w=0.7      → recall@10 50.0% / MRR 0.645 / 业务 MRR 0.700
 *     w=1.0(选)  → recall@10 56.0% / MRR 0.647 / 业务 MRR 0.717
 */
export const FTS_WEIGHT = 1.0;
export const BGE_WEIGHT = 1.0;

/** 一路召回的结果。rank 是**序位**(1..N), 不是原始 BM25 值。 */
export interface RankedRow {
  article_id: string;
  rank: number;
  score?: number;
}

/** 融合后的行。 */
export interface FusedRow {
  article_id: string;
  fused_score: number;
  ftsRank: number;
  bgeRank: number;
  bgeScore: number;
}

/**
 * RRF 融合两路召回结果。
 *
 * 纯函数 —— 可直接单测, 不用起 D1 或 bge 服务。
 */
export function fuseRankedRows(
  ftsRows: RankedRow[],
  bgeRows: RankedRow[],
  topN = 20
): FusedRow[] {
  const fused = new Map<string, { ftsRank: number; bgeRank: number; bgeScore: number; ftsScore: number }>();

  for (const r of ftsRows) {
    fused.set(r.article_id, {
      ftsRank: r.rank,
      bgeRank: 0,
      bgeScore: 0,
      ftsScore: r.score ?? 0,
    });
  }
  for (const r of bgeRows) {
    const ex = fused.get(r.article_id);
    if (ex) {
      ex.bgeRank = r.rank;
      ex.bgeScore = r.score ?? 0;
    } else {
      fused.set(r.article_id, { ftsRank: 0, bgeRank: r.rank, bgeScore: r.score ?? 0, ftsScore: 0 });
    }
  }

  return [...fused.entries()]
    .map(([aid, v]) => {
      const ftsC = v.ftsRank > 0 ? FTS_WEIGHT / (RRF_K + v.ftsRank) : 0;
      const bgeC = v.bgeRank > 0 ? BGE_WEIGHT / (RRF_K + v.bgeRank) : 0;
      return {
        article_id: aid,
        fused_score: ftsC + bgeC,
        ftsRank: v.ftsRank,
        bgeRank: v.bgeRank,
        bgeScore: v.bgeScore,
      };
    })
    .sort((a, b) => b.fused_score - a.fused_score)
    .slice(0, topN);
}
