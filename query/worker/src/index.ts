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
  // R2 key 约定: <doc_id>/articles/<article_id>.md(用 metaById 的 doc_id 拼)
  const excerptById = new Map<string, string>();
  await Promise.all((meta.results as any[]).map(async (m) => {
    const key = `${m.doc_id}/articles/${m.article_id}.md`;
    const obj = await env.INDEX_BUCKET.get(key);
    const text = obj ? (await obj.text()).slice(0, 600) : "";
    excerptById.set(m.article_id, text);
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

  // R2 key 约定: <doc_id>/chapters/<chapter_id>.md
  const key = `${docId}/chapters/${chId}.md`;
  const obj = await env.INDEX_BUCKET.get(key);
  const markdown = obj ? await obj.text() : "";
  return { chapter: row, markdown };
}

// ---------- 条文详情 ----------
async function getArticle(artId: string, env: Env) {
  const row = await env.DB.prepare(
    `SELECT a.*, c.title as chapter_title, c.number as chapter_number, a.doc_id
     FROM articles a LEFT JOIN chapters c ON c.chapter_id = a.chapter_id
     WHERE a.article_id=?1`
  ).bind(artId).first();
  if (!row) return { error: "article_not_found" };

  // R2 key 约定: <doc_id>/articles/<article_id>.md
  const docId = (row as any).doc_id;
  const key = `${docId}/articles/${artId}.md`;
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
