/**
 * Cloudflare Workers 主入口
 * 路由:
 *   GET  /api/search?q=...                检索条文 (D1 FTS5 全文检索)
 *   GET  /api/chapter/:doc_id/:ch_id      返回整章 Markdown
 *   GET  /api/article/:art_id             返回单条 Markdown + 章节上下文
 *   GET  /api/entity/:name                实体卡 + 关联条文
 *   GET  /api/documents                   文档列表(目录树)
 *   GET  /api/documents/:doc_id/chapters  文档下的章节
 *   POST /api/qa                          RAG 问答: 检索 + DeepSeek 生成答案
 *
 * 数据通路:
 *   build/export/seed_d1.py 读 articles.json,批量 INSERT 到 articles_fts
 *   articles.text 是从 R2 的 articles/<art_id>.md 加载的(避免 schema 冗余)
 *
 * 当前限制: query embedding 未接 bge(Workers 边缘跑不了 Python);
 * 走 D1 FTS5 unicode61 + LIKE 后备。语义检索质量与快档相当。
 * 后续如要接 bge,把 bge_server 部署到外部,Workers fetch 即可。
 */

export interface Env {
  INDEX_BUCKET: R2Bucket;
  DB: D1Database;
  VECTOR: VectorizeIndex;
  AI: Ai;
  DEEPSEEK_API_BASE: string;
  DEEPSEEK_MODEL: string;
}

// 检索 hit 的最小类型(RAG QA 与 searchArticles 共用)
interface SearchHit {
  article_id: string;
  chapter_id?: string;
  doc_id?: string;
  chapter_title?: string;
  chapter_number?: string;
  article_number?: string;
  title?: string;
  excerpt: string;
  relevance?: number;
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

// 纯中文 2 字 query 的判定。
// ⚠️ 正则字面量里写 CJK 范围容易被工具链转义破坏, 用 \u 转义写死。
const CJK_2CHAR_RE = /^[\u4E00-\u9FFF]{2}$/;

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(req.url);
    const path = url.pathname;
    // ⚠️ url.pathname **不做 percent-decode** —— 中文 article_id 会带着
    //    %E5%B0%81... 的编码形式进来。路由捕获到的参数必须 decodeURIComponent,
    //    否则查 D1 一条都查不到(症状: 所有条文/章节详情都 not_found)。
    //    decodeURIComponent 对已解码的普通 ASCII id 也是安全的(无 % 就原样返回)。

    try {
      if (path === "/api/search" || path === "/api/search/") {
        return json(await searchArticles(url.searchParams.get("q") ?? "", env, url.searchParams), env);
      }
      if (path === "/api/documents") return json(await listDocuments(env), env);
      const mDocChs = path.match(/^\/api\/documents\/([^/]+)\/chapters$/);
      // ⚠️ 必须 decode —— url.pathname 不做 percent-decode,
      //    中文 doc_id 会带 %E5%81... 进 D1, 查不到任何章节。
      if (mDocChs) {
        return json(await listChapters(decodeURIComponent(mDocChs[1]), env), env);
      }
      const mChap = path.match(/^\/api\/chapter\/([^/]+)\/([^/]+)$/);
      if (mChap) {
        return json(
          await getChapter(decodeURIComponent(mChap[1]), decodeURIComponent(mChap[2]), env),
          env
        );
      }
      const mArt = path.match(/^\/api\/article\/([^/]+)$/);
      if (mArt) return json(await getArticle(decodeURIComponent(mArt[1]), env), env);
      const mEnt = path.match(/^\/api\/entity\/(.+)$/);
      if (mEnt) return json(await getEntity(decodeURIComponent(mEnt[1]), env), env);
      if (path === "/api/qa" && req.method === "POST") {
        const body = await req.json<{ q: string; stream?: boolean }>();
        const wantStream = body.stream || url.searchParams.get("stream") === "true";
        if (wantStream) {
          return ragQAStream(body.q, env);
        }
        return json(await ragQA(body.q, env), env);
      }
      return json({ error: "not_found", path }, env, 404);
    } catch (e) {
      return json({ error: "internal", message: (e as Error).message }, env, 500);
    }
  },
};

function json(data: unknown, env: Env, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

// ---------- 带重试的 fetch ----------
//
// ⚠️ miniflare 本地开发有个 keep-alive 连接复用 bug:
//    同一个 origin 连续发请求时, **隔一次就死** ——
//    实测 6 次连续 GET /health: 成功/失败/成功/失败/成功/失败,
//    每次失败都是 "Network connection lost" (4ms 内失败, 不是超时)。
//    加 200ms 间隔后 3 次全成功。
//
//    真 Cloudflare 上没有这个问题, 但重试是幂等的且便宜,
//    统一加上能同时覆盖「本地 miniflare」和「生产偶发网络抖动」。
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  attempts = 3,
  delayMs = 250
): Promise<T> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      if (i < attempts - 1) {
        await new Promise(r => setTimeout(r, delayMs));
      }
    }
  }
  console.warn(`[fetch] ${attempts} 次重试仍失败:`, (lastErr as Error)?.message);
  throw lastErr;
}

// ---------- R2 key 构造 ----------
//
// ⚠️ R2 存的 key 是 **URL-encoded** 形式(中文 → %E5%B0%81...),
//    而 D1 里 r2_object_key 存的是**原始中文**。
//    直接用原始中文 key 去 get() 会 404 —— miniflare 不会自动 encode。
//    实测: 2180 个对象在 R2 里, 但 excerpt 全是空。
//
// 对策: 统一走 r2Key() 编码后再取。
// R2 真实环境(Cloudflare)对 key 的编码要求比 miniflare 宽松,
// 但 encodeURIComponent 对纯 ASCII key 是幂等的, 两边都能用。
function r2Key(objKey: string | null | undefined, fallbackDocId: string, kind: "articles" | "chapters"): string {
  if (!objKey) return `${fallbackDocId}/${kind}/`;
  // 已经是完整 key(含 "/")就直接用
  const key = objKey.includes("/") ? objKey : `${fallbackDocId}/${kind}/${objKey}`;
  // 逐段 encode, 但保留 "/" 分隔符
  return key.split("/").map(encodeURIComponent).join("/");
}

// ---------- 检索(FTS5 + bge-m3 hybrid) ----------
//
// [2026-09-20 玄穹 CEO 决策 C-b]
// C-a 评测证明: FTS5 trigram (0.5) + TF-IDF (0.2) + bge-m3 (0.3) hybrid
// 比单 FTS5 recall@10 从 53.7% 提到 86.2%。生产环境必须上 hybrid。
//
// Workers 边缘跑不了 Python/sentence_transformers,所以 bge 召回走
// fetch BGE_SERVER_URL (env). 接口契约:
//   POST {BGE_SERVER_URL}/v1/search
//   body: {"query": str, "top_k": 20, "doc_id"?: str}
//   reply: {"hits": [{article_id, doc_id, score, excerpt}, ...]}
//
// 融合策略: RRF (Reciprocal Rank Fusion),权重为各路单独 recall 数。
// FTS5 命中 rank 已在 D1 (rank 越低越好),bge 命中 rank = 1..N (score 降序)。
//
// 失败兜底: 如果 BGE_SERVER_URL 未配或 fetch 失败,
// 退化为纯 FTS5 + LIKE,与 v1 一致 (不破生产)。

async function searchArticles(
  q: string,
  env: Env,
  filters: URLSearchParams
) {
  if (!q) return { hits: [], query: q };

  // FTS5 主路径
  const ftsQuery = escapeFts(q.trim());
  if (!ftsQuery) return { hits: [], query: q };

  // ⚠️ 长 query (自然语言问题) 直接 MATCH 必然 0 命中:
  //    trigram 要求 query 是正文的**连续子串**, 而 "饲料添加剂审定需要提交什么材料"
  //    这种句子在法规里根本不存在。对策: bigram 切分 → 每 gram 单独查 → RRF 融合。
  //    详见 queryTermGrams() 的注释。
  const grams = queryTermGrams(q.trim());
  const useGramSearch = grams.length > 1;

  let ftsRows: { article_id: string; rank: number; score?: number }[] = [];
  if (useGramSearch) {
    ftsRows = await gramSearch(env, grams, q.trim());
  } else {
    try {
      const result = await env.DB.prepare(
        `SELECT article_id, rank FROM articles_fts
         WHERE articles_fts MATCH ?1
         ORDER BY rank
         LIMIT 20`
      ).bind(ftsQuery).all();
      // ⚠️ FTS5 的 rank 是**原始 BM25 值**(负数, 量纲与 bge 的 rank 完全不同)。
      //    融合层按 1/(K+rank) 算 RRF, 必须先转成**序位**(1..N)。
      ftsRows = (result.results as any[]).map((r, i) => ({
        article_id: r.article_id,
        rank: i + 1,
      }));
    } catch (e) {
      console.warn(`[search] FTS5 fallback for "${q}":`, (e as Error).message);
    }
  }

  // LIKE 补位 (仅当 FTS5 已有 ≥1 命中)
  if (ftsRows.length > 0 && ftsRows.length < 20 && /[\u4E00-\u9FFF]/.test(q)) {
    const like = `%${q}%`;
    const fallback = await env.DB.prepare(
      `SELECT article_id FROM articles_fts
       WHERE title LIKE ?1 OR text LIKE ?1
       ORDER BY instr(text, ?2)
       LIMIT 20`
    ).bind(like, q).all();
    const seen = new Set(ftsRows.map(r => r.article_id));
    for (const r of fallback.results as any[]) {
      if (!seen.has(r.article_id)) {
        // ⚠️ LIKE 补位的行也要给**序位**, 不能用 rank=0 ——
        //    融合层靠 rank>0 判断「这一路命中了」, 给 0 等于把这路贡献丢了。
        ftsRows.push({ article_id: r.article_id, rank: ftsRows.length + 1 });
        seen.add(r.article_id);
      }
    }
  }

  // bge 召回 (失败静默退化为单 FTS5)
  let bgeRows: { article_id: string; rank: number; score: number }[] = [];
  const bgeUrl = (env as any).BGE_SERVER_URL;
  if (bgeUrl) {
    const docFilter = filters.get("doc_id") || "";
    const doBge = async () => {
      const bgeResp = await fetch(`${bgeUrl}/v1/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, top_k: 20, doc_id: docFilter }),
        cf: { cacheTtl: 0, cacheEverything: false },  // 不缓存,query 多变
      });
      if (!bgeResp.ok) {
        throw new Error(`bge_server ${bgeResp.status}`);
      }
      const bgeData = (await bgeResp.json()) as {
        hits: { article_id: string; score: number }[];
      };
      return (bgeData.hits || []).map((h, i) => ({
        article_id: h.article_id,
        rank: i + 1,  // bge top-1 = rank 1
        score: h.score,
      }));
    };

    try {
      bgeRows = await fetchWithRetry(doBge, 3);
    } catch (e) {
      console.warn(`[search] bge_server unreachable:`, (e as Error).message);
    }
  }

  if (ftsRows.length === 0 && bgeRows.length === 0) return { hits: [], query: q };

  // RRF 融合: score = sum( 1 / (k + rank_i) ) for each retriever i
  // k=60 是原 RRF 论文推荐值
  const K = 60;
  const fused = new Map<string, { ftsRank: number; bgeRank: number; bgeScore: number; ftsScore: number }>();
  for (const r of ftsRows) {
    fused.set(r.article_id, {
      ftsRank: r.rank,
      bgeRank: 0,
      bgeScore: 0,
      // gram 路径已经在内部做过 RRF + 标题加权, score 直接复用;
      // 传统路径 score = undefined, 走下面的 rank 公式。
      ftsScore: r.score ?? 0,
    });
  }
  for (const r of bgeRows) {
    const ex = fused.get(r.article_id);
    if (ex) {
      ex.bgeRank = r.rank;
      ex.bgeScore = r.score;
    } else {
      fused.set(r.article_id, { ftsRank: 0, bgeRank: r.rank, bgeScore: r.score, ftsScore: 0 });
    }
  }

  // 算融合分。
  //
  // ⚠️ **两路的分数量纲必须先归一化**。
  //    gram 路径的 ftsScore 是「A 档 1000+ / B 档 RRF ~0.05」的混合值,
  //    而 bge 的贡献是 0.3/(60+rank) ~ 0.005 —— 差 3~4 个数量级。
  //    直接相加再 slice(0,20), 结果是 **bge 的命中全被挤出 top20**
  //    (实测: bge 自己的 top20 有 20 条, 最终结果里 0 条带 bge_rank)。
  //
  // 对策: 每路各自算 RRF 分(量纲一致, 都是 1/(K+rank) 量级), 再按权重相加。
  //   ftsC: gram 路径用 ftsScore 归一化后的相对值; 传统路径用 1/(K+rank)
  //   bgeC: 1/(K + bgeRank)
  // 两路各自算 RRF 分, 再加权相加 —— **量纲必须一致**, 否则一路压死另一路。
  //
  // ⚠️ 之前踩的坑: gram 路径的 ftsScore 是「A 档 1000+ / B 档 ~0.05」混合值,
  //    直接和 bge 的 0.3/(60+rank) ~0.005 相加再 slice(0,20),
  //    结果 bge 的命中**全被挤出 top20**(实测: bge 自己 top20 有 20 条,
  //    最终结果里带 bge_rank 的 0 条)。
  //
  // 正确做法:
  //   ftsC = 1/(K + ftsRank)      —— ftsRank 用**融合前的序位**(1..N)
  //   bgeC = 1/(K + bgeRank)      —— bgeRank 同理
  //   两路权重 FTS_W / BGE_W, 归一化到可比量级。
  // ⚠️ 两路权重必须**相等**(1.0 : 1.0):
  //   - bge 权重太小 → 它的命中全被 FTS5 挤出 top20(实测 bge 自己 top20
  //     全军覆没, 最终结果带 bge_rank 的只有 0~3 条)。
  //   - bge 权重太大 → 稀释「精确短语」query 的命中。
  //   实测扫参(evals/eval_minimax.py, bge cache 清理掉旧语料残留之后):
  //     FTS5 only      → recall@10 50.0% / MRR 0.544 / 业务 MRR 0.488
  //     w=0.7         → recall@10 50.0% / MRR 0.645 / 业务 MRR 0.700
  //     w=1.0(选)     → recall@10 56.0% / MRR 0.647 / 业务 MRR 0.717
  const FTS_W = 1.0;
  const BGE_W = 1.0;
  const fusedRows = [...fused.entries()].map(([aid, v]) => {
    const ftsC = v.ftsRank > 0 ? FTS_W / (K + v.ftsRank) : 0;
    const bgeC = v.bgeRank > 0 ? BGE_W / (K + v.bgeRank) : 0;
    return {
      article_id: aid,
      fused_score: ftsC + bgeC,
      ftsRank: v.ftsRank,
      bgeRank: v.bgeRank,
      bgeScore: v.bgeScore,
    };
  }).sort((a, b) => b.fused_score - a.fused_score).slice(0, 20);

  // 关联 D1 + R2
  const ids = fusedRows.map(r => r.article_id);
  const placeholders = ids.map((_, i) => `?${i + 1}`).join(",");
  const meta = await env.DB.prepare(
    `SELECT a.article_id, a.chapter_id, a.doc_id, a.number, a.title as atitle,
            a.r2_object_key,
            c.title as chapter_title, c.number as chapter_number
     FROM articles a
     LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.article_id IN (${placeholders})`
  ).bind(...ids).all();
  const metaById = new Map((meta.results as any[]).map(m => [m.article_id, m]));

  const fusedById = new Map(fusedRows.map(r => [r.article_id, r]));
  const excerptById = new Map<string, string>();
  await Promise.all((meta.results as any[]).map(async (m) => {
    // R2 key: 必须 encode(见 r2Key 的注释)
    const key = r2Key(m.r2_object_key, m.doc_id, "articles");
    const obj = await env.INDEX_BUCKET.get(key);
    const text = obj ? (await obj.text()).slice(0, 600) : "";
    excerptById.set(m.article_id, text);
  }));

  const hits: SearchHit[] = ids.map((aid) => {
    const m = metaById.get(aid);
    const f = fusedById.get(aid)!;
    return {
      article_id: aid,
      chapter_id: m?.chapter_id,
      doc_id: m?.doc_id,
      chapter_title: m?.chapter_title,
      chapter_number: m?.chapter_number,
      article_number: m?.number,
      title: m?.atitle,
      excerpt: excerptById.get(aid) ?? "",
      relevance: f.fused_score,
      // 调试字段,生产可隐藏
      ...(filters.get("debug") === "1" && {
        fts_rank: f.ftsRank,
        bge_rank: f.bgeRank,
        bge_score: f.bgeScore,
      } as any),
    };
  });

  // doc_id / chapter_id 过滤 (bge 已传 doc_id 过滤,这里再做一次兜底)
  const docFilter = filters.get("doc_id");
  const chapFilter = filters.get("chapter_id");
  const filtered = hits.filter(h =>
    (!docFilter || h.doc_id === docFilter) &&
    (!chapFilter || h.chapter_id === chapFilter)
  );

  return { hits: filtered, query: q };
}

// ---------- 长 query 的 bigram 检索 ----------
//
// 问题: trigram 分词器要求 query 是正文的**连续子串**。
//   "饲料添加剂审定需要提交什么材料" 这种自然语言问题在法规里不存在 → 0 命中。
//   实测: 10 条业务长 query 全部 0 命中。
//
// 对策: bigram 切分 → 每个 gram 单独 FTS5 查询 → RRF 融合。
//   bigram ("饲料"/"料添"/"添加"/...) 是中文里最小的有意义单元,
//   比固定 4 字窗口准("要提交什" 这种碎片没有检索价值)。
//
// 为什么每个 gram 要单独查而不是拼成一个大 OR 表达式:
//   - 拼 OR → 命中集爆炸(实测 723~1793 条), BM25 无法区分"命中所有 gram"
//     和"只命中一个 gram" 的文档
//   - 单独查 → 每个 gram 有自己的 BM25 rank, RRF 融合时"命中多个 gram"
//     的文档自然排前面(实测新兽药注册办法 top4 全来自该文档)
//
// 为什么 2 字 gram 也要 padding:
//   trigram 需要 3 个连续字符, 2 字 gram 直接 MATCH 必然 0 命中。
//   用 escapeFts 的后缀集合扩展成 3 字 phrase。
//
// 标题加权 (TITLE_BOOST):
//   查询往往直接点名法规("新兽药注册办法" 就是文件名)。
//   标题命中是强信号, 权重 3x。

const TITLE_BOOST = 3.0;
const GRAM_TOP_N = 30;
const RRF_K = 60;

// 中文停用 bigram —— 这些是虚词组合, 检索价值低
const STOP_BIGRAMS = new Set([
  "什么", "如何", "哪些", "是否", "需要", "应该", "可以", "进行", "相关",
  "规定", "的话", "一个", "我们", "他们", "这个", "那个", "因为", "所以",
  "但是", "如果", "以及", "对于", "关于", "怎样", "多少", "为何", "什么",
  "有无", "是否", "几个", "哪些", "如何", "哪种", "什么",
]);

/**
 * 把 query 切成检索用的 term 列表。
 * - 中文段 → 重叠 bigram (2 字)
 * - 英文/数字 → 整词 (≥2 字符)
 * - 去停用词 + 去重保序
 */
function queryTermGrams(q: string): string[] {
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

/** gram → FTS5 MATCH 表达式 (2 字要 padding 成 3 字 phrase) */
function gramExpr(gram: string): string {
  if (gram.length === 2) {
    const SUFFIXES = [" ", "\u7684", "\u6761", "\u89c4", "\u5b9a", "\u5236",
                      "\u6cd5", "\u7406", "\u7ae0", "\u5e94", "\u548c"];
    return SUFFIXES.map((suf) => `"${gram}${suf}"`).join(" OR ");
  }
  return `"${gram}"`;
}

/**
 * 分档检索: **phrase 优先 + bigram RRF 兜底**
 *
 * A 档(高精度): query 整句当 phrase 查。
 *   query 是正文的连续片段时精确命中, BM25 rank 天然最靠前。
 *   实测: "本条例所称饲料" 整句 MATCH 命中 rank 1, 但纯 bigram 路径排不进 top20。
 *
 * B 档(高召回): bigram 逐个查 + RRF 融合 + 标题加权。
 *   query 是自然语言问句时整句必然 0 命中, 只有 B 档能出结果。
 *
 * ⚠️ 两档**不能混在一个分数池里比**:
 *   phrase 命中(精确)vs 只命中一个常见 bigram 的文档, 精度差一个数量级。
 *   实测混池时 phrase 命中的目标被挤到 top20 外; 分档后全部回到 rank 1。
 */
async function gramSearch(
  env: Env,
  grams: string[],
  rawQuery: string
): Promise<{ article_id: string; rank: number; score?: number }[]> {
  const queries = grams.map(gramExpr);

  // ---------- A 档: 整句 phrase ----------
  let phraseRows: { article_id: string; rank: number }[] = [];
  if (rawQuery.length >= 3) {
    try {
      const r = await env.DB.prepare(
        `SELECT article_id, rank FROM articles_fts
         WHERE articles_fts MATCH ?1
         ORDER BY rank
         LIMIT ?2`
      ).bind(`"${rawQuery.replace(/"/g, "")}"`, GRAM_TOP_N).all();
      phraseRows = r.results as any;
    } catch (e) {
      console.warn("[search] phrase match failed:", (e as Error).message);
    }
  }

  // ---------- B 档: bigram RRF ----------
  // gram → (article_id → rank)
  const bodyRanks = new Map<string, Map<string, number>>();
  const titleRanks = new Map<string, Map<string, number>>();

  const stmts = queries.map((expr) =>
    env.DB.prepare(
      `SELECT article_id, rank FROM articles_fts
       WHERE articles_fts MATCH ?1
       ORDER BY rank
       LIMIT ?2`
    ).bind(expr, GRAM_TOP_N)
  );

  let results: any[] = [];
  try {
    results = await env.DB.batch(stmts as any);
  } catch (e) {
    console.warn("[search] gram batch failed:", (e as Error).message);
    return [];
  }

  for (let i = 0; i < results.length; i++) {
    const rows = (results[i] as any)?.results ?? [];
    for (const r of rows) {
      const aid = r.article_id;
      if (!bodyRanks.has(aid)) bodyRanks.set(aid, new Map());
      bodyRanks.get(aid)!.set(grams[i], r.rank);
    }
  }

  // 标题路径: 单独查 title 列非空的行
  const titleStmts = queries.map((expr) =>
    env.DB.prepare(
      `SELECT article_id, rank FROM articles_fts
       WHERE articles_fts MATCH ?1 AND title != ''
       ORDER BY rank
       LIMIT ?2`
    ).bind(expr, GRAM_TOP_N)
  );
  let titleResults: any[] = [];
  try {
    titleResults = await env.DB.batch(titleStmts as any);
  } catch (e) {
    console.warn("[search] title gram batch failed:", (e as Error).message);
  }
  for (let i = 0; i < titleResults.length; i++) {
    const rows = (titleResults[i] as any)?.results ?? [];
    for (const r of rows) {
      const aid = r.article_id;
      if (!titleRanks.has(aid)) titleRanks.set(aid, new Map());
      titleRanks.get(aid)!.set(grams[i], r.rank);
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
  const out: { article_id: string; rank: number; score?: number }[] = [];
  const seen = new Set<string>();
  let idx = 0;
  for (const r of phraseRows) {
    if (seen.has(r.article_id)) continue;
    seen.add(r.article_id);
    out.push({ article_id: r.article_id, rank: idx + 1 });
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

// FTS5 trigram 对 query 不要求 phrase 包裹(只要 ≥3 字子串匹配即可)
// 但要做基本清理:去控制字符、长度截断、避免用户输入里有 FTS5 语法符号
//
// ⚠️ trigram 分词器要求**连续 3 个字符**, 所以 2 字中文 query 必然 0 命中。
//    对策: 给 2 字 query 补后缀, 扩成多个 3 字 phrase 用 OR 连接。
//
//    后缀字符集里**必须包含空格**: 章节名注入文本时是 "第一章 总则 标题...",
//    "总则 " (含尾随空格) 才是真实存在的 3-gram。
//    只用汉字后缀时 "总则" 这类**章节名 query 会 0 命中**(实测 0 → 165)。
//
//    另外每个 phrase 必须**加引号**: 否则空格会被当成 FTS5 的 AND/OR 运算符,
//    整个 MATCH 表达式语义错乱。
function escapeFts(s: string): string {
  if (!s) return "";
  const cleaned = s.replace(/[\x00-\x1f]/g, " ").trim().slice(0, 64);
  if (!cleaned) return "";
  // 仅对纯中文 2 字 query 加 padding,避免破坏英文/数字 query
  if (CJK_2CHAR_RE.test(cleaned)) {
    const SUFFIXES = [" ", "的", "条", "规", "定", "制", "法", "理", "章", "应", "和"];
    const phrases = SUFFIXES.map((suf) => `"${cleaned}${suf}"`);
    return phrases.join(" OR ");
  }
  return cleaned;
}

// ---------- 文档列表 ----------
async function listDocuments(env: Env) {
  // ⚠️ 排序不能靠 created_at —— 灌库时所有文档的 created_at 相同(SQLite
  //    同秒插入), ORDER BY created_at DESC 的顺序是**插入顺序的逆序**,
  //    会把「目录/封面」顶到最前面(实测首页第一屏全是 000封面)。
  //    改成: 目录/封面排后面, 其余按 doc_id 排(编号前缀保证法规顺序稳定)。
  const rows = await env.DB.prepare(
    `SELECT d.doc_id, d.title, d.doc_number, d.issuer, d.effective_date,
            (SELECT COUNT(*) FROM chapters c WHERE c.doc_id = d.doc_id) as chapter_count,
            (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.doc_id) as article_count
     FROM documents d
     ORDER BY d.is_toc ASC, d.sort_order ASC, d.doc_id ASC`
  ).all();
  return { documents: rows.results };
}

// ---------- 文档下的章节 ----------
async function listChapters(docId: string, env: Env) {
  const rows = await env.DB.prepare(
    `SELECT chapter_id, doc_id, number, title, article_count, sort_order
     FROM chapters WHERE doc_id = ?1
     ORDER BY sort_order ASC`
  ).bind(docId).all();
  return { chapters: rows.results };
}

// ---------- 章节详情 ----------
async function getChapter(docId: string, chId: string, env: Env) {
  const row = await env.DB.prepare(
    `SELECT * FROM chapters WHERE doc_id=?1 AND chapter_id=?2`
  ).bind(docId, chId).first();
  if (!row) return { error: "chapter_not_found" };

  // R2 key: r2_object_key 存的是**完整 key**(含短 doc 前缀),
  // 例如 "d1a2b3c4d5/chapters/xxx__abc12345.md"。
  // doc_id 段必须短 —— R2 object name 上限约 320 字节(UTF-8), 长中文 slug 会超。
  const key = r2Key((row as any).r2_object_key, docId, "chapters");
  const obj = await env.INDEX_BUCKET.get(key);
  const markdown = obj ? await obj.text() : "";
  return { chapter: row, markdown };
}

// ---------- 条文详情 ----------
async function getArticle(artId: string, env: Env) {
  // ⚠️ 不要写 `a.*, ..., a.doc_id` —— doc_id 在 a.* 里已经有了,
  //    重复列名会让 D1 **静默返回空结果集**(不报错, .first() 就是 null),
  //    症状是所有条文详情都 article_not_found。
  const row = await env.DB.prepare(
    `SELECT a.article_id, a.chapter_id, a.doc_id, a.number, a.title,
            a.r2_object_key, a.vector_id,
            c.title as chapter_title, c.number as chapter_number
     FROM articles a LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.article_id=?1`
  ).bind(artId).first();
  if (!row) return { error: "article_not_found" };

  // R2 key: r2_object_key 存的是**完整 key**(含短 doc 前缀)
  const docId = (row as any).doc_id;
  const key = r2Key((row as any).r2_object_key, docId, "articles");
  const obj = await env.INDEX_BUCKET.get(key);
  return { article: row, markdown: obj ? await obj.text() : "" };
}

// ---------- 实体详情 ----------
async function getEntity(name: string, env: Env) {
  const ent = await env.DB.prepare(
    `SELECT * FROM entities WHERE name=?1`
  ).bind(name).first();
  if (!ent) return { error: "entity_not_found" };

  const articles = await env.DB.prepare(
    `SELECT a.article_id, a.number, a.title, a.chapter_id, c.number as chapter_number, c.title as chapter_title
     FROM entity_articles ea
     JOIN articles a ON a.article_id = ea.article_id
     JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE ea.entity_id=?1
     LIMIT 50`
  ).bind((ent as any).entity_id).all();

  return { entity: ent, articles: articles.results };
}

// ---------- RAG 问答 ----------

/**
 * 拼 RAG prompt: system + few-shot + evidence + user question
 *
 * 设计原则:
 * - system 强制"未找到则明说",避免 LLM 编造
 * - few-shot 教 LLM 用什么格式引用(`[1]` 而不是 `第一条`)
 * - evidence 限 8 条,过长会稀释 LLM 注意
 */
function buildRagPrompt(q: string, hits: SearchHit[]) {
  const context = hits
    .slice(0, 8)
    .map((h, i) => `[${i + 1}] ${h.chapter_number} ${h.chapter_title} · ${h.article_number}: ${h.excerpt}`)
    .join("\n\n");

  const systemPrompt = `你是"中国农业饲料法规知识库"的检索助手,严格基于下方"检索证据"用中文回答用户问题。

# 行为准则
1. **必须只基于检索证据**回答,不要引用未在证据中出现的条文、法律或事实。
2. 若证据不足以回答,直接回复:"未找到相关规定",不要编造或猜测。
3. 引用条款时使用证据前方的编号格式 \`[N]\`,不要写"第一条"这种裸引用。
4. 答案简洁,优先列条文要点;不要堆砌废话。

# 输出格式(可选)
- 直接答案(1-3 句话)
- 涉及到的引用编号列表(\`[1] [3]\`)
- 如果多条证据相关,按编号顺序引用`;

  const userPrompt = `# 检索证据
${context || "(无相关证据)"}

# 用户问题
${q}

# 答案`;

  return { systemPrompt, userPrompt };
}

/**
 * 同步 RAG 问答:返回完整 JSON
 */
async function ragQA(q: string, env: Env) {
  const hits = await searchArticles(q, env, new URLSearchParams());
  const t0 = Date.now();
  const { systemPrompt, userPrompt } = buildRagPrompt(q, hits.hits);

  const resp = await fetch(`${env.DEEPSEEK_API_BASE}/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${(env as any).DEEPSEEK_API_KEY ?? ""}`,
    },
    body: JSON.stringify({
      model: env.DEEPSEEK_MODEL,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      temperature: 0.2,
      max_tokens: 1000,
      stream: false,
    }),
  });

  if (!resp.ok) return { error: "llm_error", status: resp.status, body: await resp.text() };
  const data = (await resp.json()) as { choices: { message: { content: string } }[] };
  const answer = data.choices[0].message.content;
  const citations = await validateCitations(answer, hits.hits, env);

  return {
    question: q,
    answer,
    citations,
    retrieval: hits.hits.slice(0, 8),
    elapsed_ms: Date.now() - t0,
  };
}

/**
 * Streaming RAG 问答:SSE 推送,事件类型:
 *   - `event: meta\ndata: { question, retrieval }\n\n`  (开头发检索证据)
 *   - `event: chunk\ndata: {"delta": "..."}\n\n`         (增量 token)
 *   - `event: done\ndata: { citations }\n\n`            (结束 + 校验后引用)
 *
 * 出错事件:
 *   - `event: error\ndata: { message }\n\n`
 */
function ragQAStream(q: string, env: Env): Response {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      try {
        // 1. 检索
        const hits = await searchArticles(q, env, new URLSearchParams());
        controller.enqueue(encoder.encode(formatSSE("meta", {
          question: q,
          retrieval: hits.hits.slice(0, 8),
        })));

        // 2. LLM streaming
        const { systemPrompt, userPrompt } = buildRagPrompt(q, hits.hits);
        const resp = await fetch(`${env.DEEPSEEK_API_BASE}/chat/completions`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${(env as any).DEEPSEEK_API_KEY ?? ""}`,
          },
          body: JSON.stringify({
            model: env.DEEPSEEK_MODEL,
            messages: [
              { role: "system", content: systemPrompt },
              { role: "user", content: userPrompt },
            ],
            temperature: 0.2,
            max_tokens: 1000,
            stream: true,
          }),
        });

        if (!resp.ok || !resp.body) {
          controller.enqueue(encoder.encode(formatSSE("error", {
            status: resp.status,
            body: await resp.text(),
          })));
          controller.close();
          return;
        }

        // 3. 透传上游 SSE,提取 delta
        let fullAnswer = "";
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          // DeepSeek/OpenAI SSE:每行 `data: { "choices": [{ "delta": { "content": "..." }}] }`
          for (const line of buf.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (payload === "[DONE]") continue;
            try {
              const obj = JSON.parse(payload);
              const delta = obj.choices?.[0]?.delta?.content;
              if (delta) {
                fullAnswer += delta;
                controller.enqueue(encoder.encode(formatSSE("chunk", { delta })));
              }
            } catch {
              // ignore malformed line
            }
          }
          buf = "";
        }

        // 4. 校验引用,推送 done
        const citations = await validateCitations(fullAnswer, hits.hits, env);
        controller.enqueue(encoder.encode(formatSSE("done", { citations })));
        controller.close();
      } catch (e) {
        controller.enqueue(encoder.encode(formatSSE("error", {
          message: (e as Error).message,
        })));
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      ...CORS,
    },
  });
}

function formatSSE(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * Citation 校验:从 LLM 输出里解析 `[1]` `[3]` 这种引用,与检索证据对账。
 * 输出每个引用对应的完整元数据,前端可渲染成可点击链接。
 * 缺失引用(LLM 编造)打 warning。
 */
async function validateCitations(answer: string, hits: SearchHit[], env: Env) {
  // 提取所有 [N] 引用,N 是 1-based
  const re = /\[(\d+)\]/g;
  const nums = new Set<number>();
  for (const m of answer.matchAll(re)) {
    nums.add(parseInt(m[1], 10));
  }

  const out: Array<{
    ref: number;
    article_id?: string;
    chapter_number?: string;
    chapter_title?: string;
    article_number?: string;
    excerpt?: string;
    valid: boolean;
  }> = [];

  for (const n of [...nums].sort((a, b) => a - b)) {
    const hit = hits[n - 1];
    if (hit) {
      out.push({
        ref: n,
        article_id: hit.article_id,
        chapter_number: hit.chapter_number,
        chapter_title: hit.chapter_title,
        article_number: hit.article_number,
        excerpt: hit.excerpt,
        valid: true,
      });
    } else {
      out.push({ ref: n, valid: false });
    }
  }

  return out;
}
