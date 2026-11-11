-- ============================================================
-- ⑤ 法规监测 Monitoring —— D1 schema
-- ============================================================
-- ⚠️ **必须单独跑,不能重跑 schema.sql**
--    生产库有 3145 条条文,wrangler 4.127+ 对「schema 变了」的库报
--    D1_RESET_DO,**会清空远端表**。
--
--    用法:
--      python build/export/apply_migration.py query/worker/migrate_monitoring.sql
--      npx wrangler d1 execute siliao-db --remote --file ./query/worker/migrate_monitoring.sql
--
-- 归属(ADR-004 §6):
--   regulation_releases / monitoring_runs → ⑤ 监测上下文
--   subscriptions                        → ⑤ 监测上下文
-- ============================================================

-- ------------------------------------------------------------
-- ① regulation_releases —— 抓到的法规发布
-- ------------------------------------------------------------
-- ⚠️ `release_key` 是**权威主键**:公告号(如「第1025号」)。
--    抓不到公告号时回退完整 URL。
--    不用标题做主键 —— 标题会改,会漏掉「同一份公告被修订」。
CREATE TABLE IF NOT EXISTS regulation_releases (
  release_key    TEXT PRIMARY KEY,          -- 公告号,权威唯一标识
  title          TEXT NOT NULL,
  url            TEXT NOT NULL,
  published_at   TEXT,                     -- YYYY-MM-DD,从路径解析
  body_excerpt   TEXT,                     -- 正文前 2000 字
  body_length    INTEGER DEFAULT 0,        -- 正文总长度(判断是否抓全)
  fingerprint    TEXT,                     -- 正文指纹,判断是否被修订
  change_type    TEXT NOT NULL DEFAULT 'new',  -- new | revised | unchanged
  matched_keywords   TEXT,                 -- JSON 数组,命中的关键词
  affected_assets    TEXT,                 -- JSON 数组,推断受影响的资产
  determinable   INTEGER DEFAULT 0,        -- 1=影响面可判定 0=未知
  first_seen_at  TEXT NOT NULL,
  last_seen_at   TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

-- 索引:按发布时间倒序查最近变更
CREATE INDEX IF NOT EXISTS idx_reg_releases_published
  ON regulation_releases(published_at DESC);

-- 索引:只查需要人看的(影响面可判定)
CREATE INDEX IF NOT EXISTS idx_reg_releases_determinable
  ON regulation_releases(determinable, published_at DESC);

-- ------------------------------------------------------------
-- ② monitoring_runs —— 每次抓取的运行记录
-- ------------------------------------------------------------
-- ⚠️ **爬虫失败必须告警而非静默** —— ADR-006 §3。
--    抓不到公告时看这张表:最新一条 status='failed' 就是原因。
CREATE TABLE IF NOT EXISTS monitoring_runs (
  run_id       TEXT PRIMARY KEY,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL DEFAULT 'running',  -- running | ok | failed
  pages        INTEGER DEFAULT 0,
  found        INTEGER DEFAULT 0,               -- 列表抓到的条数
  bodies_ok    INTEGER DEFAULT 0,               -- 成功抓到正文的条数
  bodies_fail  INTEGER DEFAULT 0,               -- 正文抓取失败(不阻断整批)
  new_count    INTEGER DEFAULT 0,               -- 新发布
  revised_count INTEGER DEFAULT 0,             -- 公告被修订
  error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_monitoring_runs_started
  ON monitoring_runs(started_at DESC);

-- ------------------------------------------------------------
-- ③ subscriptions —— 订阅(关注哪些物质/品类)
-- ------------------------------------------------------------
-- ⚠️ 一期只支持**按资产类型**订阅(limit_rules / substance_catalog …)。
--    按单个物质订阅留到有真实用例时再建表 —— ADR-004 的
--    「④ 图谱保持空壳不实现」是同一条纪律:不提前造。
CREATE TABLE IF NOT EXISTS subscriptions (
  subscription_id TEXT PRIMARY KEY,
  asset_type      TEXT NOT NULL,   -- limit_rules | substance_catalog | prohibition_rules | label_rules | species_scope
  label           TEXT NOT NULL,   -- 人类可读的订阅名
  created_at      TEXT NOT NULL,
  last_notified_at TEXT,           -- 上次推送时间(防重复推送)
  active          INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_asset
  ON subscriptions(asset_type, active);
