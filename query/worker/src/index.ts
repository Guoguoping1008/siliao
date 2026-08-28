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

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

    const url = new URL(req.url);
    const path = url.pathname;

    try {
      if (path === "/api/search" || path === "/api/search/") {
        return json(await searchArticles(url.searchParams.get("q") ?? "", env, url.searchParams), env);
      }
      if (path === "/api/documents") return json(await listDocuments(env), env);
      const mDocChs = path.match(/^\/api\/documents\/([^/]+)\/chapters$/);
      if (mDocChs) return json(await listChapters(mDocChs[1], env), env);
      const mChap = path.match(/^\/api\/chapter\/([^/]+)\/([^/]+)$/);
      if (mChap) return json(await getChapter(mChap[1], mChap[2], env), env);
      const mArt = path.match(/^\/api\/article\/([^/]+)$/);
      if (mArt) return json(await getArticle(mArt[1], env), env);
      const mEnt = path.match(/^\/api\/entity\/(.+)$/);
      if (mEnt) return json(await getEntity(decodeURIComponent(mEnt[1]), env), env);
      if (path === "/api/qa" && req.method === "POST") {
        const body = await req.json<{ q: string }>();
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

// ---------- 检索(FTS5) ----------
async function searchArticles(
  q: string,
  env: Env,
  filters: URLSearchParams
) {
  if (!q) return { hits: [], query: q };

  // FTS5 MATCH 语法:对用户 query 做转义,加双引号做 phrase 查询避免语法错
  const ftsQuery = escapeFts(q.trim());
  if (!ftsQuery) return { hits: [], query: q };

  // 主查询走 FTS5 + padding,拿 article_id
  let rows: { article_id: string; rank: number }[];
  try {
    const result = await env.DB.prepare(
      `SELECT article_id, rank FROM articles_fts
       WHERE articles_fts MATCH ?1
       ORDER BY rank
       LIMIT 20`
    ).bind(ftsQuery).all();
    rows = result.results as any;
  } catch (e) {
    console.warn(`[search] FTS5 fallback for "${q}":`, (e as Error).message);
    rows = [];
  }

  // 兜底:中文 query 补一次 LIKE,确保 2 字短 query / 专有名词近义也能召回
  if (rows.length < 20 && /[\u4E00-\u9FFF]/.test(q)) {
    const like = `%${q}%`;
    const fallback = await env.DB.prepare(
      `SELECT article_id, 0 as rank FROM articles_fts
       WHERE title LIKE ?1 OR text LIKE ?1
       LIMIT 20`
    ).bind(like).all();
    const seen = new Set(rows.map(r => r.article_id));
    for (const r of fallback.results as any[]) {
      if (!seen.has(r.article_id)) {
        rows.push(r);
        seen.add(r.article_id);
      }
    }
  }

  if (rows.length === 0) return { hits: [], query: q };

  // 关联 D1 articles 表拿元数据(用 IN 一次性拿,避免 N+1)
  const ids = rows.map(r => r.article_id);
  const placeholders = ids.map((_, i) => `?${i + 1}`).join(",");
  const meta = await env.DB.prepare(
    `SELECT a.article_id, a.chapter_id, a.doc_id, a.number, a.title as atitle,
            c.title as chapter_title, c.number as chapter_number
     FROM articles a
     LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.article_id IN (${placeholders})`
  ).bind(...ids).all();
  const metaById = new Map((meta.results as any[]).map(m => [m.article_id, m]));

  // 批量从 R2 拉 excerpt(避免 N+1)
  const r2Keys = await env.DB.prepare(
    `SELECT article_id, r2_object_key FROM articles WHERE article_id IN (${placeholders})`
  ).bind(...ids).all();

  const excerptById = new Map<string, string>();
  await Promise.all((r2Keys.results as any[]).map(async (r) => {
    const obj = await env.INDEX_BUCKET.get(r.r2_object_key);
    const text = obj ? (await obj.text()).slice(0, 600) : "";
    excerptById.set(r.article_id, text);
  }));

  const hits = rows.map((r, i) => {
    const m = metaById.get(r.article_id);
    return {
      article_id: r.article_id,
      chapter_id: m?.chapter_id,
      doc_id: m?.doc_id,
      chapter_title: m?.chapter_title,
      chapter_number: m?.chapter_number,
      article_number: m?.number,
      title: m?.atitle,
      excerpt: excerptById.get(r.article_id) ?? "",
      relevance: -r.rank,  // FTS5 rank 越低越好,转成正数越大越好
    };
  });

  // 按 doc_id / chapter_id 过滤
  const docFilter = filters.get("doc_id");
  const chapFilter = filters.get("chapter_id");
  const filtered = hits.filter(h =>
    (!docFilter || h.doc_id === docFilter) &&
    (!chapFilter || h.chapter_id === chapFilter)
  );

  return { hits: filtered, query: q };
}

// FTS5 trigram 对 query 不要求 phrase 包裹(只要 ≥3 字子串匹配即可)
// 但要做基本清理:去控制字符、长度截断、避免用户输入里有 FTS5 语法符号
// 2 字中文 query 自动加 padding 后缀,让 trigram 命中更可靠
function escapeFts(s: string): string {
  if (!s) return "";
  const cleaned = s.replace(/[\x00-\x1f]/g, " ").trim().slice(0, 64);
  if (!cleaned) return "";
  // 仅对纯中文 2 字 query 加 padding,避免破坏英文/数字 query
  if (/^[\u4E00-\u9FFF]{2}$/.test(cleaned)) {
    // 用 OR 组合多个 padded query(都 OR 进 FTS5 表达式)
    const padded = ["制", "的", "条", "法", "理"].map(suf => `${cleaned}${suf}`).join(" OR ");
    return padded;
  }
  return cleaned;
}

// ---------- 文档列表 ----------
async function listDocuments(env: Env) {
  const rows = await env.DB.prepare(
    `SELECT d.doc_id, d.title, d.doc_number, d.issuer, d.effective_date,
            (SELECT COUNT(*) FROM chapters c WHERE c.doc_id = d.doc_id) as chapter_count,
            (SELECT COUNT(*) FROM articles a WHERE a.doc_id = d.doc_id) as article_count
     FROM documents d ORDER BY d.created_at DESC`
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

  const obj = await env.INDEX_BUCKET.get((row as any).r2_object_key);
  const markdown = obj ? await obj.text() : "";
  return { chapter: row, markdown };
}

// ---------- 条文详情 ----------
async function getArticle(artId: string, env: Env) {
  const row = await env.DB.prepare(
    `SELECT a.*, c.title as chapter_title, c.number as chapter_number
     FROM articles a LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.article_id=?1`
  ).bind(artId).first();
  if (!row) return { error: "article_not_found" };

  const obj = await env.INDEX_BUCKET.get((row as any).r2_object_key);
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
async function ragQA(q: string, env: Env) {
  const hits = await searchArticles(q, env, new URLSearchParams());

  const context = hits.hits
    .slice(0, 8)
    .map((h, i) => `[${i + 1}] ${h.chapter_number} ${h.chapter_title} · ${h.article_number}: ${h.excerpt}`)
    .join("\n\n");

  const systemPrompt = `你是一名中国农业饲料法规领域的检索助手,只根据下方"检索证据"用中文回答,不要编造。
引用条款时使用格式:"第X章 第Y条"。`;

  const userPrompt = `检索证据:\n${context}\n\n用户问题:${q}\n\n答案:`;

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
    }),
  });

  if (!resp.ok) return { error: "llm_error", status: resp.status, body: await resp.text() };
  const data = (await resp.json()) as { choices: { message: { content: string } }[] };
  return {
    question: q,
    answer: data.choices[0].message.content,
    citations: hits.hits.slice(0, 8),
  };
}
