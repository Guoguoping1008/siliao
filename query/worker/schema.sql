-- D1 schema: 文档 / 章节 / 索引元信息
-- 跑法:  wrangler d1 execute siliao-db --remote --file ./schema.sql

CREATE TABLE IF NOT EXISTS documents (
  doc_id       TEXT PRIMARY KEY,
  title        TEXT NOT NULL,
  doc_number   TEXT,
  issuer       TEXT,
  issue_date   TEXT,
  effective_date TEXT,
  source_url   TEXT,
  version      TEXT DEFAULT 'v1',
  -- is_toc: 1 = 目录/封面页(不是法规正文, 不进 FTS, 列表排后面)
  is_toc       INTEGER DEFAULT 0,
  sort_order   INTEGER DEFAULT 0,
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chapters (
  chapter_id   TEXT PRIMARY KEY,
  doc_id       TEXT NOT NULL,
  number       TEXT NOT NULL,           -- "第一章"
  title        TEXT NOT NULL,           -- "总则"
  article_count INTEGER DEFAULT 0,
  sort_order   INTEGER NOT NULL,
  r2_object_key TEXT NOT NULL,           -- R2 中 chapters/ch01.md 的 key
  -- ⚠️ 章节正文**不单独存**: 它是本章下所有条文 body 的拼接,
  --    单独存会让 seed.sql 的单条 INSERT 超过 D1 的 SQLITE_TOOBIG(实测 115KB),
  --    而且正文重复存一遍。Worker 改为按 chapter_id 聚合 articles.body 现拼。
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_chapters_doc ON chapters(doc_id, sort_order);

CREATE TABLE IF NOT EXISTS articles (
  article_id   TEXT PRIMARY KEY,
  chapter_id   TEXT NOT NULL,
  doc_id       TEXT NOT NULL,
  number       TEXT NOT NULL,           -- "第一条"
  title        TEXT,
  r2_object_key TEXT NOT NULL,
  vector_id    TEXT,                    -- 对应 Vectorize 中的 id
  -- 正文全文(markdown)。
  --
  -- ⚠️ 2026-10-26: 正文改存在 D1,不再依赖 R2。
  --    原因: 本账户 R2 未开通(Dashboard 手动激活 + 绑支付方式, API 绕不过),
  --    而正文只有 7.3MB —— D1 免费额度 5GB, 完全放得下。
  --    附带好处: excerpt 不用 20 次 R2 GET 拼, 一次 JOIN 就出来,
  --    每条 hit 少一个网络往返(21 次 → 1 次)。
  --    r2_object_key 保留(将来开 R2 了可以搬回去, 也兼容旧数据)。
  body         TEXT,
  -- 本章内的条文顺序。⚠️ 不能靠 article_id 排序 —— 它按字典序排,
  -- 会打乱原文顺序(实测 95/529 个章节的条文顺序与原文不一致)。
  -- 章节正文是按这个顺序拼出来的。
  sort_order   INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (chapter_id) REFERENCES chapters(chapter_id),
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_chapter ON articles(chapter_id);
CREATE INDEX IF NOT EXISTS idx_articles_doc ON articles(doc_id);

-- 目录树(书籍原版层级: 一级分类 → 子类 → 文件, 带文号 + 起始页)
--
-- ⚠️ 为什么不直接从 documents 表拼?
--    documents 表是 ingest 按**目录树顺序**存的, 只有 scope/section 两级,
--    没有「起始页」也没有原版的二级分类名(数据里是 '01_（一）新产品审定',
--    目录里是 '（一）新产品审定')。目录页本身是独立信息源, 整棵存最省事。
--
-- 一行存整棵 JSON(压缩后约 61KB)—— 目录是只读的, 没有查询需求,
-- 拆成多表反而增加 join 复杂度。
CREATE TABLE IF NOT EXISTS catalog (
  id          INTEGER PRIMARY KEY CHECK (id = 1),   -- 永远只有一行
  tree        TEXT NOT NULL,                       -- JSON
  stats       TEXT,                                -- JSON
  updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id    TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  type         TEXT NOT NULL,           -- LAW / AGENCY / CERTIFICATE 等
  description  TEXT,
  doc_id       TEXT
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

CREATE TABLE IF NOT EXISTS entity_articles (
  entity_id    TEXT NOT NULL,
  article_id   TEXT NOT NULL,
  PRIMARY KEY (entity_id, article_id),
  FOREIGN KEY (entity_id) REFERENCES entities(entity_id),
  FOREIGN KEY (article_id) REFERENCES articles(article_id)
);

CREATE TABLE IF NOT EXISTS index_meta (
  id              TEXT PRIMARY KEY,
  doc_count       INTEGER,
  entity_count    INTEGER,
  relationship_count INTEGER,
  chunk_count     INTEGER,
  community_count INTEGER,
  updated_at      TEXT DEFAULT (datetime('now'))
);

-- 全文检索(FTS5): 用 articles 的 title + 正文做 MATCH 查询
-- articles_search 表是 articles 的镜像 + 文本列,触发器保持同步
-- 这样 searchArticles 可走 MATCH,不需要 LIKE
-- tokenize=trigram: 中文 CJK 友好(unicode61 对中文不分词,2 字查询会 miss)
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
  article_id UNINDEXED,
  chapter_id UNINDEXED,
  doc_id UNINDEXED,
  number UNINDEXED,
  title,
  text,
  tokenize = 'trigram'
);