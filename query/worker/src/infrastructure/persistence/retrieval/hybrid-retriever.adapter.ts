/**
 * 混合检索适配器 —— infrastructure 层
 *
 * 上下文: ① 法规知识库 Regulation 的检索子域
 *
 * ## 架构决策
 *
 * [2026-09-20 玄穹 CEO 决策 C-b]
 * C-a 评测证明: FTS5 trigram (0.5) + TF-IDF (0.2) + bge-m3 (0.3) hybrid
 * 比单 FTS5 recall@10 从 53.7% 提到 86.2%。生产环境必须上 hybrid。
 *
 * ## 三路召回
 *
 * 1. **A 档 phrase** —— query 整句当 phrase 查, BM25 rank 天然最靠前
 * 2. **B 档 bigram RRF** —— 长 query 逐 gram 查 + RRF 融合 + 标题加权
 * 3. **bge-m3 语义** —— 近义表达兜底
 *
 * ⚠️ 两档**不能混在一个分数池里比**: phrase 命中(精确) vs 只命中一个
 *    常见 bigram 的文档, 精度差一个数量级。实测混池时 phrase 命中的目标
 *    被挤到 top20 外; 分档后全部回到 rank 1。
 *
 * ⚠️ bge 失败**静默降级**为纯 FTS5, 不破生产。
 */

import {
  escapeFts,
  fuseRankedRows,
  gramExpr,
  queryTermGrams,
  GRAM_TOP_N,
  RRF_K,
  TITLE_BOOST,
  type FusedRow,
  type RankedRow,
} from "../../../domain/regulation/retrieval-query.vo";
import { plainExcerpt } from "../../../interfaces/acl/regulation.acl";
import { embeddingSearch } from "../../../interfaces/acl/embedding.acl";
import { fetchWithRetry } from "../../../interfaces/acl/llm.acl";
import type { Evidence } from "../../../domain/inquiry/evidence.vo";
import type { D1Like } from "../d1/regulation.repository.impl";
import { mapRows, type DbRow } from "../d1/mappers";

/** 检索参数。 */
export interface RetrievalParams {
  q: string;
  docId?: string;
  chapterId?: string;
  debug?: boolean;
}

/** 检索结果。 */
export interface RetrievalResult {
  hits: Evidence[];
  query: string;
}

/** bge 服务地址(可为空 = 不启用语义路)。 */
export interface EmbeddingEnv {
  BGE_SERVER_URL?: string;
}

/**
 * 混合检索器。
 *
 * 组合 FTS5(A档 + B档 bigram)与 bge-m3 语义路, RRF 融合。
 */
export class HybridRetriever {
  constructor(
    private readonly db: D1Like,
    private readonly embeddingEnv: EmbeddingEnv
  ) {}

  async search(params: RetrievalParams): Promise<RetrievalResult> {
    const { q } = params;
    if (!q) return { hits: [], query: q };

    const ftsQuery = escapeFts(q.trim());
    if (!ftsQuery) return { hits: [], query: q };

    // ⚠️ 长 query (自然语言问题) 直接 MATCH 必然 0 命中:
    //    trigram 要求 query 是正文的**连续子串**, 而「饲料添加剂审定需要提交什么材料」
    //    这种句子在法规里根本不存在。对策: bigram 切分 → 每 gram 单独查 → RRF 融合。
    const grams = queryTermGrams(q.trim());
    const useGramSearch = grams.length > 1;

    let ftsRows: RankedRow[] = [];
    if (useGramSearch) {
      ftsRows = await this.gramSearch(grams, q.trim());
    } else {
      try {
        const result = await this.db.prepare(
          `SELECT article_id, rank FROM articles_fts
           WHERE articles_fts MATCH ?1
           ORDER BY rank
           LIMIT 20`
        ).bind(ftsQuery).all();
        // ⚠️ FTS5 的 rank 是**原始 BM25 值**(负数, 量纲与 bge 的 rank 完全不同)。
        //    融合层按 1/(K+rank) 算 RRF, 必须先转成**序位**(1..N)。
        ftsRows = (result.results as DbRow[]).map((r, i) => ({
          article_id: String(r.article_id),
          rank: i + 1,
        }));
      } catch (e) {
        console.warn(`[search] FTS5 fallback for "${q}":`, (e as Error).message);
      }
    }

    // LIKE 补位 (仅当 FTS5 已有 ≥1 命中)
    if (ftsRows.length > 0 && ftsRows.length < 20 && /[\u4E00-\u9FFF]/.test(q)) {
      const like = `%${q}%`;
      const fallback = await this.db.prepare(
        `SELECT article_id FROM articles_fts
         WHERE title LIKE ?1 OR text LIKE ?1
         ORDER BY instr(text, ?2)
         LIMIT 20`
      ).bind(like, q).all();
      const seen = new Set(ftsRows.map((r) => r.article_id));
      for (const r of fallback.results as DbRow[]) {
        const aid = String(r.article_id);
        if (!seen.has(aid)) {
          // ⚠️ LIKE 补位的行也要给**序位**, 不能用 rank=0 ——
          //    融合层靠 rank>0 判断「这一路命中了」, 给 0 等于把这路贡献丢了。
          ftsRows.push({ article_id: aid, rank: ftsRows.length + 1 });
          seen.add(aid);
        }
      }
    }

    // bge 召回 (失败静默退化为单 FTS5)
    const bgeRows = await this.bgeSearch(q, params.docId || "");

    if (ftsRows.length === 0 && bgeRows.length === 0) return { hits: [], query: q };

    const fusedRows = fuseRankedRows(ftsRows, bgeRows, 20);

    return this.hydrate(fusedRows, params);
  }

  /** bge 语义召回。失败静默降级, 不抛异常。 */
  private async bgeSearch(q: string, docFilter: string): Promise<RankedRow[]> {
    const bgeUrl = this.embeddingEnv.BGE_SERVER_URL;
    if (!bgeUrl) return [];

    try {
      const hits = await fetchWithRetry(
        () => embeddingSearch(bgeUrl, q, 20, docFilter),
        3
      );
      return hits.map((h, i) => ({
        article_id: h.article_id,
        rank: i + 1, // bge top-1 = rank 1
        score: h.score,
      }));
    } catch (e) {
      console.warn(`[search] bge_server unreachable:`, (e as Error).message);
      return [];
    }
  }

  /**
   * 分档检索: **phrase 优先 + bigram RRF 兜底**
   *
   * A 档(高精度): query 整句当 phrase 查。
   *   query 是正文的连续片段时精确命中, BM25 rank 天然最靠前。
   *   实测: 「本条例所称饲料」整句 MATCH 命中 rank 1, 但纯 bigram 路径排不进 top20。
   *
   * B 档(高召回): bigram 逐个查 + RRF 融合 + 标题加权。
   *   query 是自然语言问句时整句必然 0 命中, 只有 B 档能出结果。
   */
  private async gramSearch(
    grams: string[],
    rawQuery: string
  ): Promise<RankedRow[]> {
    const queries = grams.map(gramExpr);

    // ---------- A 档: 整句 phrase ----------
    let phraseRows: DbRow[] = [];
    if (rawQuery.length >= 3) {
      try {
        const r = await this.db.prepare(
          `SELECT article_id, rank FROM articles_fts
           WHERE articles_fts MATCH ?1
           ORDER BY rank
           LIMIT ?2`
        ).bind(`"${rawQuery.replace(/"/g, "")}"`, GRAM_TOP_N).all();
        phraseRows = r.results as DbRow[];
      } catch (e) {
        console.warn("[search] phrase match failed:", (e as Error).message);
      }
    }

    // ---------- B 档: bigram RRF ----------
    // gram → (article_id → rank)
    const bodyRanks = new Map<string, Map<string, number>>();
    const titleRanks = new Map<string, Map<string, number>>();

    const stmts = queries.map((expr) =>
      this.db.prepare(
        `SELECT article_id, rank FROM articles_fts
         WHERE articles_fts MATCH ?1
         ORDER BY rank
         LIMIT ?2`
      ).bind(expr, GRAM_TOP_N)
    );

    let results: { results: DbRow[] }[] = [];
    try {
      results = (await this.db.batch(stmts as unknown[])) as { results: DbRow[] }[];
    } catch (e) {
      console.warn("[search] gram batch failed:", (e as Error).message);
      return [];
    }

    for (let i = 0; i < results.length; i++) {
      const rows = results[i]?.results ?? [];
      for (const r of rows) {
        const aid = String(r.article_id);
        if (!bodyRanks.has(aid)) bodyRanks.set(aid, new Map());
        bodyRanks.get(aid)!.set(grams[i], Number(r.rank));
      }
    }

    // 标题路径: 单独查 title 列非空的行
    const titleStmts = queries.map((expr) =>
      this.db.prepare(
        `SELECT article_id, rank FROM articles_fts
         WHERE articles_fts MATCH ?1 AND title != ''
         ORDER BY rank
         LIMIT ?2`
      ).bind(expr, GRAM_TOP_N)
    );
    let titleResults: { results: DbRow[] }[] = [];
    try {
      titleResults = (await this.db.batch(titleStmts as unknown[])) as { results: DbRow[] }[];
    } catch (e) {
      console.warn("[search] title gram batch failed:", (e as Error).message);
    }
    for (let i = 0; i < titleResults.length; i++) {
      const rows = titleResults[i]?.results ?? [];
      for (const r of rows) {
        const aid = String(r.article_id);
        if (!titleRanks.has(aid)) titleRanks.set(aid, new Map());
        titleRanks.get(aid)!.set(grams[i], Number(r.rank));
      }
    }

    const fused = new Map<string, number>();
    for (const [aid, ranks] of bodyRanks) {
      let s = 0;
      for (const r of ranks.values()) s += 1 / (RRF_K + r);
      fused.set(aid, s);
    }
    for (const [aid, ranks] of titleRanks) {
      let s = 0;
      for (const r of ranks.values()) s += 1 / (RRF_K + r);
      fused.set(aid, (fused.get(aid) ?? 0) + TITLE_BOOST * s);
    }

    // ---------- 合并: A 档在前, B 档补后 ----------
    // ⚠️ rank 必须是**序位**(1,2,3...), 不能是 FTS5 的原始 BM25 值
    //    (BM25 是负数, 且量纲跟 bge 的 rank 完全不同)。
    //    融合层按 1/(K+rank) 算 RRF, 两路序位才可比。
    const out: RankedRow[] = [];
    const seen = new Set<string>();
    let idx = 0;
    for (const r of phraseRows) {
      const aid = String(r.article_id);
      if (seen.has(aid)) continue;
      seen.add(aid);
      out.push({ article_id: aid, rank: idx + 1 });
      idx++;
    }
    const bSorted = [...fused.entries()].sort((a, b) => b[1] - a[1]);
    for (const [aid] of bSorted) {
      if (seen.has(aid)) continue;
      seen.add(aid);
      out.push({ article_id: aid, rank: idx + 1 });
      idx++;
      if (out.length >= 20) break;
    }
    return out.slice(0, 20);
  }

  /**
   * 关联 D1 元数据与正文,组装最终 hit。
   *
   * ⚠️ 2026-10-26: 正文改从 D1 的 articles.body 直接取(随 JOIN 一起出来),
   *    不再逐条 R2.get()。旧写法 20 hits → 20 次网络往返。
   */
  private async hydrate(fusedRows: FusedRow[], params: RetrievalParams): Promise<RetrievalResult> {
    const ids = fusedRows.map((r) => r.article_id);
    if (ids.length === 0) return { hits: [], query: params.q };

    const placeholders = ids.map((_, i) => `?${i + 1}`).join(",");
    const meta = await this.db.prepare(
      `SELECT a.article_id, a.chapter_id, a.doc_id, a.number, a.title as atitle,
              a.body,
              c.title as chapter_title, c.number as chapter_number
       FROM articles a
       LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
       WHERE a.article_id IN (${placeholders})`
    ).bind(...ids).all();

    const metaById = new Map((meta.results as DbRow[]).map((m) => [String(m.article_id), m]));
    const fusedById = new Map(fusedRows.map((r) => [r.article_id, r]));
    const excerptById = new Map<string, string>(
      (meta.results as DbRow[]).map((m) => [String(m.article_id), plainExcerpt(String(m.body || ""))])
    );

    const hits: Evidence[] = ids.map((aid) => {
      const m = metaById.get(aid);
      const f = fusedById.get(aid)!;
      return {
        article_id: aid,
        chapter_id: m?.chapter_id ? String(m.chapter_id) : undefined,
        doc_id: m?.doc_id ? String(m.doc_id) : undefined,
        chapter_title: m?.chapter_title ? String(m.chapter_title) : undefined,
        chapter_number: m?.chapter_number ? String(m.chapter_number) : undefined,
        article_number: m?.number ? String(m.number) : undefined,
        title: m?.atitle ? String(m.atitle) : undefined,
        excerpt: excerptById.get(aid) ?? "",
        relevance: f.fused_score,
        // 调试字段,生产可隐藏
        ...(params.debug && {
          fts_rank: f.ftsRank,
          bge_rank: f.bgeRank,
          bge_score: f.bgeScore,
        } as any),
      };
    });

    // doc_id / chapter_id 过滤 (bge 已传 doc_id 过滤,这里再做一次兜底)
    const filtered = hits.filter((h) =>
      (!params.docId || h.doc_id === params.docId) &&
      (!params.chapterId || h.chapter_id === params.chapterId)
    );

    return { hits: filtered, query: params.q };
  }
}
