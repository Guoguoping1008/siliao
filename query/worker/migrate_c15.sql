-- ═══════════════════════════════════════════════════════════════
-- C1.5 · 多轮会话 —— D1 schema
-- ═══════════════════════════════════════════════════════════════
--
-- 跑法:
--   npx wrangler d1 execute siliao-db --remote --file ./migrate_c15.sql
--
-- ⚠️ **与 schema.sql 分开**: schema.sql 是给**新库**用的;
--    生产库已有 3145 条条文, 重跑 schema.sql 有清库风险
--    (实测 wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO, 还会清空远端表)。
--
-- ⚠️ **与 migrate_c1.sql 分开**: 同上, 不重跑已有的迁移。
--
-- ## 设计取舍: **不引向量库**
--
-- 会话记忆用**结构化表**存, 不做向量检索:
--   · 用户追问通常只有 2-5 轮, 全量带进 prompt 完全可行
--   · 向量库要多一套索引维护, 而 D1 是本项目唯一的存储
--   · 真正需要向量记忆的场景(几十轮、跨话题)还没出现
--     —— 与 ADR-004「按需展开, 不为不存在的需求建上下文」一致
--
-- 若将来真需要, 这里是加表的位置, 不影响现有结构。

-- ── 会话 ──
CREATE TABLE IF NOT EXISTS qa_sessions (
  session_id    TEXT PRIMARY KEY,
  created_at    TEXT DEFAULT (datetime('now')),
  updated_at    TEXT DEFAULT (datetime('now')),
  -- 轮次数(冗余字段, 便于展示与清理)
  turn_count    INTEGER DEFAULT 0
);

-- ── 会话消息 ──
CREATE TABLE IF NOT EXISTS qa_messages (
  message_id    TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL,
  -- 轮次序号(1-based)
  turn_no       INTEGER NOT NULL,
  role          TEXT NOT NULL,           -- user | assistant
  content       TEXT NOT NULL,
  -- 本轮检索到的证据(article_id 列表, JSON) —— 供下一轮做指代消解
  evidence_json TEXT,
  -- 本轮识别出的实体(JSON) —— 下一轮直接复用
  entities_json TEXT,
  -- 本轮实际用于检索的 query(可能含补全后的上下文)
  resolved_query TEXT,
  created_at    TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (session_id) REFERENCES qa_sessions(session_id)
);

CREATE INDEX IF NOT EXISTS idx_qa_messages_session ON qa_messages(session_id, turn_no);

-- ⚠️ **不做「消息表与会话表强一致」的约束** ——
--    D1 不支持跨表事务, 且会话是**可丢弃的临时状态**
--    (用户关掉页面就没了), 不值得为它引入事务复杂度。
--    写入顺序: 先插 session, 再插 messages; 失败时靠 session 的
--    turn_count 与实际消息数不一致来识别并清理。
