-- 幂等迁移: 老库补列。
--
-- ⚠️ `CREATE TABLE IF NOT EXISTS` **不会**给已存在的表加列。
--    schema.sql 加了 documents.is_toc / documents.sort_order 之后,
--    已有 DB 仍然缺这两列 → seed.sql 的 INSERT 报
--    "table documents has no column named is_toc"。
--
--    重复执行会报 "duplicate column name" —— 这是**预期行为**,
--    迁移脚本会逐条执行并忽略该错误。
--
-- 跑法:
--    npx wrangler d1 execute siliao-db --local --command \
--      "ALTER TABLE documents ADD COLUMN is_toc INTEGER DEFAULT 0"
--    npx wrangler d1 execute siliao-db --local --command \
--      "ALTER TABLE documents ADD COLUMN sort_order INTEGER DEFAULT 0"

ALTER TABLE documents ADD COLUMN is_toc INTEGER DEFAULT 0;
ALTER TABLE documents ADD COLUMN sort_order INTEGER DEFAULT 0;
