/**
 * Cloudflare Workers 主入口
 * 路由:
 *   GET  /api/search?q=...         检索条文 (向量召回 + D1 元数据补全)
 *   GET  /api/chapter/:doc_id/:ch_id  返回整章 Markdown
 *   GET  /api/article/:art_id      返回单条 Markdown + 章节上下文
 *   GET  /api/entity/:name         实体卡 + 关联条文
 *   GET  /api/documents            文档列表(目录树)
 *   POST /api/qa                   RAG 问答: 检索 + DeepSeek 生成答案
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

// ---------- 检索 ----------
async function searchArticles(
  q: string,
  env: Env,
  filters: URLSearchParams
) {
  if (!q) return { hits: [] };

  // 1. 用 Workers AI 生成 query embedding(bge 走 vllm endpoint,这里用 OpenAI 兼容)
  //    暂留 stub: 实际 Vectorize.query 需要 1024 维向量,需要调用本地 embedding 服务
  //    这里走占位实现: 从 R2 读 chunk 元数据 + 在 D1 做 LIKE 模糊匹配
  const like = `%${q}%`;
  const rows = await env.DB.prepare(
    `SELECT a.article_id, a.chapter_id, a.number, a.title, a.doc_id,
            c.title as chapter_title, c.number as chapter_number
     FROM articles a
     LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.title LIKE ?1 OR a.r2_object_key LIKE ?1 OR c.title LIKE ?1
     LIMIT 20`
  ).bind(like).all();

  // 2. 拿到每个 article 的正文 (从 R2)
  const hits = await Promise.all(
    (rows.results as any[]).map(async (r) => {
      const obj = await env.INDEX_BUCKET.get(r.r2_object_key);
      const text = obj ? (await obj.text()).slice(0, 600) : "";
      return {
        article_id: r.article_id,
        chapter_id: r.chapter_id,
        doc_id: r.doc_id,
        chapter_title: r.chapter_title,
        chapter_number: r.chapter_number,
        article_number: r.number,
        title: r.title,
        excerpt: text,
      };
    })
  );
  return { hits, query: q };
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

// ---------- RAG 问答 ----------
async function ragQA(q: string, env: Env) {
  // 1. 拿候选 chunks
  const hits = await searchArticles(q, env, new URLSearchParams());

  // 2. 拼 prompt
  const context = hits.hits
    .slice(0, 8)
    .map((h, i) => `[${i + 1}] ${h.chapter_number} ${h.chapter_title} · ${h.article_number}: ${h.excerpt}`)
    .join("\n\n");

  const systemPrompt = `你是一名中国农业饲料法规领域的检索助手,只根据下方"检索证据"用中文回答,不要编造。
引用条款时使用格式:"第X章 第Y条"。`;

  const userPrompt = `检索证据:\n${context}\n\n用户问题:${q}\n\n答案:`;

  // 3. 调 DeepSeek
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