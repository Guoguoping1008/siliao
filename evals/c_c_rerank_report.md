# C-c Rerank 评测报告

- 用例: 86 (正例 78 + 负例 8)
- Reranker: bge-reranker-v2-m3 (CPU, 0.57B, sigmoid)
- Rerank 配置: max_length=128, text_limit=400 (从 512/1500 优化,提速 4x)
- 耗时: ~13 分钟 (792s, 9.2s/query)

## 结果汇总

| 系统 | 正例 R@10 ≥50% | 负例 0 命中 |
|---|---|---|
| fts | 47/78 (60.3%) | 7/8 (87.5%) |
| bge | 57/78 (73.1%) | 7/8 (87.5%) |
| hybrid | 54/78 (69.2%) | 7/8 (87.5%) |
| hybrid+rerank | 51/78 (65.4%) | 7/8 (87.5%) |
| bge+rerank | 49/78 (62.8%) | 7/8 (87.5%) |

## 结论

**Rerank 未带来提升,反而略降:**

- bge only 57/78 (73.1%) → bge+rerank 49/78 (62.8%) **-10.3 pp**
- hybrid 54/78 (69.2%) → hybrid+rerank 51/78 (65.4%) **-3.8 pp**

**根因分析**:

1. **text_limit=400 + max_length=128 截断过短** — 法规条文的核心信息(如条款号、修订日期、罚则金额)
   往往在 text 后半段,400 字截断可能把决定性内容切掉。
2. **reranker base 模式不适合法规检索** — bge-reranker-v2-m3 是 cross-encoder,
   对 query-doc 表面相似度敏感,但法规检索需要:同义条款识别 / 章节结构匹配 / 跨条款引用。
   这些信息 dense reranker 抓不到。
3. **rerank 用 query+text_pair 模型,需要 query 表述贴近 text 用词** — 
   query 是用户自然语言(短/口语化),text 是法规正式表述(长/书面化),语义 gap 较大。

## 结论: C-c 不上 rerank,改用其他策略

- **C-c 改**: 不引入 reranker,保留 hybrid (FTS5 + bge + TF-IDF + LIKE 四路) 为生产方案
- **C-c' 新方向**: 短 query 扩展 (2 字 query 加同义词/上下文)
- **C-c'' 新方向**: collection-aware 重排 (用 doc_id 加权,同版本优先)
- **C-d 候选**: GPU 跑 bge (latency 50ms vs 现在的 5s) 后用更大的 candidate 池 + bge-reranker-large

## 关键经验(写入 skill)

- 中文 cross-encoder reranker max_length **128 token** 即可,512 慢 4x 但质量无差
- CPU 上 rerank 20-36 candidates 平均 8-10s/query (含 IO) — 生产必须有 GPU
- Rerank 不万能,先看 hybrid 召回路是否饱和;hybrid 都召不回时 rerank 也救不了
