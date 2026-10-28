-- ═══════════════════════════════════════════════════════════════
-- ② 合规规则上下文 —— D1 schema (ADR-004 M2 / 功能设计 C1)
-- ═══════════════════════════════════════════════════════════════
--
-- 跑法:
--   npx wrangler d1 execute siliao-db --remote --file ./migrate_c1.sql
--
-- ⚠️ **与 schema.sql 分开**: schema.sql 是给**新库**用的;
--    生产库已有 3145 条条文, 重跑 schema.sql 有清库风险
--    (实测 wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO, 还会清空远端表)。
--
-- ⚠️ **不变量 2 落在表结构上**: compliance_rules.source_article_id 是
--    NOT NULL —— **没有出处就不可能入库**, 不依赖应用层自觉。

-- ── 规则集版本 ──
-- 版本化是硬要求: 方案文档的「知识时效可审计」原则 ——
-- 每条判定结论必须能回溯到「当时用的是哪版规则」。
CREATE TABLE IF NOT EXISTS rule_sets (
  version       TEXT PRIMARY KEY,   -- v2026.10
  created_at    TEXT DEFAULT (datetime('now')),
  note          TEXT,
  rules_count   INTEGER DEFAULT 0,
  reviewed_by   TEXT
);

-- ── 结构化规则库 ──
CREATE TABLE IF NOT EXISTS compliance_rules (
  rule_id        TEXT PRIMARY KEY,
  -- 规则类型: limit | prohibition | condition | combination
  rule_type      TEXT NOT NULL,
  -- 规则主体
  substance      TEXT,                       -- 物质通用名(中文), 组合规则为 NULL
  substance_alias TEXT,                      -- 英文名/化学名, 用于别名匹配
  -- 适用对象
  species        TEXT,                       -- 动物种类
  stage          TEXT,                       -- 阶段(鱼苗/育肥猪…)
  -- 阈值
  min_value      REAL,
  max_value      REAL,
  unit           TEXT,                       -- mg/kg | g/kg | IU/kg | %
  -- 附加条件
  condition_text TEXT,
  -- ⚠️ 不变量 2: 溯源必填 —— 无出处不允许入库
  source_article_id TEXT NOT NULL,
  source_doc_id     TEXT NOT NULL,
  source_excerpt    TEXT,                    -- 原文摘录, 前端直接展示
  -- 规则集版本
  rule_set_version  TEXT NOT NULL,
  -- 抽取方式与审核状态
  extraction_method TEXT DEFAULT 'auto',     -- auto | manual
  -- ⚠️ 审核闸门: 未审核的规则**不参与判定**
  --    (domain/compliance/compliance-rule-set.aggregate.ts 只读 reviewed)
  review_status     TEXT DEFAULT 'pending',  -- pending | reviewed | rejected
  created_at      TEXT DEFAULT (datetime('now')),
  updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rules_substance ON compliance_rules(substance);
CREATE INDEX IF NOT EXISTS idx_rules_species   ON compliance_rules(species);
CREATE INDEX IF NOT EXISTS idx_rules_status    ON compliance_rules(review_status);
CREATE INDEX IF NOT EXISTS idx_rules_version   ON compliance_rules(rule_set_version);

-- ── 物质目录 ──
-- 《饲料添加剂品种目录》是「某物质是否在目录内」的权威清单。
-- 抽成结构化表后一次 SQL 精确匹配即可 —— 不需要知识图谱。
CREATE TABLE IF NOT EXISTS substance_catalog (
  substance_id   TEXT PRIMARY KEY,
  name_cn        TEXT NOT NULL,              -- 通用名称
  name_en        TEXT,                       -- 英文名称
  substance_alias TEXT,                      -- 额外别名(如「核黄素」)
  formula        TEXT,                       -- 化学式或描述
  source         TEXT,                       -- 来源
  spec           TEXT,                       -- 含量规格
  category       TEXT,                       -- 添加剂 | 原料 | 载体
  scope_text     TEXT,                       -- 适用范围原文
  -- ⚠️ 不变量 2: 溯源必填
  source_article_id TEXT NOT NULL,
  source_doc_id     TEXT NOT NULL,
  rule_set_version  TEXT NOT NULL,
  review_status     TEXT DEFAULT 'pending',
  created_at      TEXT DEFAULT (datetime('now')),
  updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_catalog_name_cn ON substance_catalog(name_cn);
CREATE INDEX IF NOT EXISTS idx_catalog_name_en ON substance_catalog(name_en);
CREATE INDEX IF NOT EXISTS idx_catalog_status  ON substance_catalog(review_status);
