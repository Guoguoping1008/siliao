# C-b Hybrid 召回评测报告

- 用例总数: 86 (正例 78 + 负例 8)
- bge-m3 server: `http://127.0.0.1:8080`
- 对比: 单 bge /v1/search vs eval_retrieval.search() (FTS5 trigram + TF-IDF + bge + LIKE 四路)
- 耗时: 22.9s

| 系统 | 正例 R@10 ≥50% | 负例 0 命中 |
|---|---|---|
| bge | 57/78 (73.1%) | 8/8 (100.0%) |
| hybrid | 64/78 (82.1%) | 8/8 (100.0%) |

## Hybrid 失败 case

- `饲料管理部门`: expected ['feedlawco_art027', 'feedlawco_art010', 'feedlawco_art038', 'feedlawco_art026', 'feedlawco_art017'], got ['feedlawco_art038', 'feedlawco_art017']
- `生产许可证`: expected ['feedlawco_art029', 'feedlawco_art013', 'feedlawco_art004'], got ['feedlawco_art004']
- `饲料添加剂品种目录`: expected ['feedlawco_art014', 'feedlawco_art016', 'feedlawco_art010'], got ['feedlawco_art016']
- `适用范围`: expected ['fee_sec024', 'fee_sec012', 'fee_sec040', 'fee_sec001'], got ['fee_sec001']
- `试验`: expected ['fee_sec041', 'fee_sec030', 'fee_sec029', 'fee_sec014', 'fee_sec003'], got ['fee_sec030']
- `饲料添加剂管理条例`: expected ['feedlaw2_art002', 'feedlawco_art002', 'flc23_p0008'], got ['flc23_p0008']
