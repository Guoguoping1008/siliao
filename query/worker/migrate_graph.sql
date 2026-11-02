-- ═══════════════════════════════════════════════════════════════
-- ④ 知识图谱 —— 实体别名表
-- ═══════════════════════════════════════════════════════════════
--
-- 跑法:
--   python build/export/apply_migration.py query/worker/migrate_graph.sql
--
-- ⚠️ **与 schema.sql 分开**: schema.sql 是给**新库**用的;
--    生产库已有 3145 条条文, 重跑 schema.sql 有清库风险
--    (实测 wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO, 还会清空远端表)。
--
-- ## 为什么需要这张表
--
-- 实体名取自《饲料添加剂品种目录》的**通用名称** —— 权威但不好念:
--
--     实体名     L-抗坏血酸(维生素C)
--     用户搜的   维生素C
--
-- 只按 `entities.name` 精确查,「维生素C」查不到 —— 实测生产
-- `GET /api/entity/维生素C` 返回 entity_not_found,
-- 而「核黄素(维生素B2)」这种带括号的更是完全没法搜。
--
-- ## 契约:**别名必须唯一指向一个实体**
--
-- 一个别名指向多个实体时**不入库** —— 查到了也只能随便挑一个,
-- 那是在猜。例:
--
--     维生素B1 → 盐酸硫胺(维生素B1) / 硝酸硫胺(维生素B1)
--     螯合物   → 9 个不同的络合物
--
-- 这些别名**故意不收录** —— 宁可「查不到」也不给错答案。
-- 这与 ② 合规规则的 `alignSubstanceName` 是同一条纪律:
-- **候选不唯一就不采用**。
--
-- ⚠️ **不引外部 FK** —— `entity_id` 指向 `entities`(同一上下文 ④),
--    这是上下文**内部**的引用,合规。

CREATE TABLE IF NOT EXISTS entity_aliases (
  alias       TEXT PRIMARY KEY,   -- 别名(归一后)
  entity_id   TEXT NOT NULL,      -- 指向 entities.entity_id
  alias_kind  TEXT NOT NULL       -- bracket | alias | en
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_entity ON entity_aliases(entity_id);

-- ⚠️ **不建指向 entities 的 FOREIGN KEY** ——
--    虽然同属 ④ 上下文,但 SQLite 的 FK 会让「先删实体再删别名」变成隐式约束。
--    这里用逻辑引用,删实体时由灌库脚本一并清理别名。
