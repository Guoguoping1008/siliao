# ADR-001 · 检索后端选型:FTS5(trigram)而非 Vectorize + bge

- **状态**: Accepted
- **日期**: 2026-08-28
- **决策者**: qingmang(青芒 CTO)
- **关联任务**: t_847af457 t_847af458

## 背景

Workers `searchArticles` 原本是 SQL LIKE stub,生产模式语义检索全废。需要做技术选型:

- Workers 边缘跑不了 Python bge
- Cloudflare Workers AI 自带 bge-small(512 dim,中文效果弱)
- D1 内置 FTS5 全文索引(zero external dep)
- 外部 bge HTTP 服务(需要一台常驻 VPS + 网络延迟)

## 决策

**采用 D1 FTS5 + trigram 分词 + LIKE 兜底**。

- 主路径:FTS5 MATCH 走 trigram 分词,对中文 ≥3 字子串命中
- 兜底路径:对所有中文 query 补一次 LIKE,保证 2 字短 query 和专有名词召回
- 2 字 query 自动 padding 后缀(`审定` → `审定制 OR 审定的 OR 审定条 ...`)扩展召回面
- 真接 bge 留作 Phase 2 备选路径

## 取舍

| 方案 | 优点 | 缺点 | 成本 |
|---|---|---|---|
| FTS5 trigram + LIKE(选) | 零外部依赖、tF 延迟 <50ms、D1 自带 | 2 字 query 需 padding、专有名词近义召回弱(评测 9/10) | $0 |
| Workers AI bge-small | 1 行代码、Cloudflare 内置 | 512dim 中文效果弱、免费层有 QPS 限制 | $0 |
| 外部 bge HTTP | 1024dim 中文准、语义近义召回强 | 需 VPS + 运维、Workers→VPS 网络延迟 100ms+ | $5-20/月 |
| D1 FTS5 + Vectorize 混合 | 召回 + 重排、效果好 | 复杂度↑、embedding 仍需外部服务 | $5-20/月 + 工程复杂度 |

## 性能基线

- eval 用例 28 条(23 positive + 5 negative)
- **recall@10 = 95.7%(22/23 positive 通过)**
- **recall@20 = 95.7%**(top_k=10 之外无增量,说明 LIKE 兜底已榨干)
- **MRR = 0.957**(第一条命中极准)
- negative 5/5 通过(假饲料 / 刑法 / 兽药 / 纯英文 / 纯空格 0 召回)
- 1 次 FTS5 MATCH + 1 次 LIKE 兜底,D1 单次查询 ~5-15ms

## 已知限制

- **章节名召回**:查"总则/附则/法律责任"等章节标题需要章节名注入到 articles_fts
  (已在 seed_d1.py 修复:`第一章 总则` 作为 text 前缀灌库)
- **动词短语召回**:查"研制生产经营"(5 个动词被顿号隔开)字面不连续,
  FTS5 trigram 天然召回失败 — 这是 bge 语义召回的典型场景
- **专有名词近义**:`农业农村部` 实际条文写"国务院农业农村主管部门",字面 5 字不连续

## 还债触发器

- 业务反馈"动词短语 / 概念近义召回差"(如查"研制生产经营"找不到 art002) → 接外部 bge
- 语料扩大到 >1000 条法规 → FTS5 + LIKE 召回面可能不够,评估混合检索
- eval recall@10 < 80% 或 MRR < 0.7 → 必须接 bge
- 当前基线 95.7% / MRR 0.957 已足够,**推迟 bge 接入**

## 升级路径

接 bge 时,只需替换 `searchArticles` 主查询:
1. Workers fetch `https://<bge-host>/v1/embeddings` 拿 query 向量
2. `env.VECTOR.query(vector, topK=20)` 召回 vector_id
3. 仍用 D1 拿元数据,R2 拿 excerpt
4. 保留 LIKE 兜底,做混合召回

## 替代方案记录

- **不**用 Workers AI bge-small:实测中文检索质量差(`饲料添加剂` 这种核心 query 召回 <50%)
- **不**用 Postgres + pgvector:架构复杂度大,迁移成本高,D1 完全够用
- **不**用 SQLite FTS5 unicode61:中文不分词,几乎全部 query 召回 0
