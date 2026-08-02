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
  FOREIGN KEY (chapter_id) REFERENCES chapters(chapter_id),
  FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_chapter ON articles(chapter_id);
CREATE INDEX IF NOT EXISTS idx_articles_doc ON articles(doc_id);

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