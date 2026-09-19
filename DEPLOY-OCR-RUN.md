# siliao 批量 OCR 任务日志

**起:** 2026-09-13 20:04 (用户: 批量转换 E:/workspace/siliao/Images)

## 任务定义
- 输入: Images/ 下 516 张手机翻拍图(4240x3439 横向双页合拍)
- 输出: 章节 md + 表格 md (用户原话)
- 流水线: 沿用 build/ocr/(paddleocr + 表格还原 + 章节切分)

## 现状
- 整本书是《饲料法规文件【2023】》1000+ 页
- doc_id: feed-law-collection-2023-full (新建, 不污染现有 feed-law-collection-2023)
- split: 516 张 → 1029 单页(513 双页 + 3 竖排)
  - v3 spine-aware: 296 张真书脊检测, 217 张 fallback 50% 中线, 3 张竖排
- OCR: 后台 session proc_73fd5d906c42 跑全量
  - 1029 张, 当前 ~380 张 (37%)
  - 预计 50-60 min 跑完
- 后处理脚本:
  - extract_page_order.py (页码提取) — v1 阈值 5% 严,改 12% 后 L 15/169, R 49/169
  - chapter_splitter_v2.py (去重 + 跳过目录) — 修了 toc_end +1 bug
  - post_ocr.sh (一键后处理) — 写好待用
  - table_reconstruct.py (现有)

## 工程量
- split: 2m48s
- OCR: ~1h
- 后处理: ~5 min

## 风险
- v3 spine 在 42% 图上 fallback 中线, 可能切偏(用户拍时手影干扰)
- 页码提取覆盖率 ~50%, 仍可按页码排序但部分图顺序依赖时间戳
- 表格页 ~20% 需人工抽查
- 目录页 60+ 张混在前段, 章节切分已用 toc_range 排除

## 输出位置
- 整本 markdown: data/markdown/feed-law-collection-2023-full/merged.md
- 章节: data/markdown/feed-law-collection-2023-full/chapters/*.md
- 条文: data/markdown/feed-law-collection-2023-full/articles/*.md
- 表格: data/markdown/feed-law-collection-2023-full/pages_tbl/*.md

---

## 2026-09-14 更新: 改用 M3 多模态重做 OCR

**用户反馈**: PaddleOCR 输出的 md 质量差 (目录页粘连/空白页噪声/全角符号丢失/页眉水印残留)
**改用方案**: MiniMax-M3 多模态 OCR (model: `MiniMax-M3`), 直接读图, 按 L/R 分开输出

### M3 任务结果

- 总图: **516** (Images/*.jpg, 4240x3439 双页合拍)
- OCR 成功: **516 / 516 (100%)**
- 主任务期间 fatal (HTTP 529 上游临时过载): 70 张
- 重试 (finalize_m3.py --retry, 单线程间隔 5-15s): **70 / 70 ✓**
- 最终失败: **0**
- 总 md: **1030 个** (516 × L/R, 2 张空白页各只占 1 个 "(空白)" md)
- 成本: ~¥14 (输入 ¥1.5 + 输出 ¥0.5)
- 总耗时: ~50 min (主任务 30 min + 重试 18 min)

### 最终产物位置

- **L/R 分页 md**: `data/markdown/feed-law-collection-2023-full/pages_m3/*.md` ⭐ 最终 OCR 产物
- **元数据**: `pages_m3/_report.json` + `_final_failures.json`
- **D1 灌库 SQL**: `build/export/seed_pages_m3.sql` (516 articles, 平均 1966 B/article)
- **PaddleOCR 旧产物 (废弃)**: `data/markdown/feed-law-collection-2023-full/pages/` `pages_tbl/` `merged.md`
- **LLM 结构化中间产物 (废弃)**: `markdown/feed-law-collection-2023-full/chapters/` `articles/` `pages_struct/`

### 关键脚本

- `build/export/m3_ocr_pages.py` — M3 多模态 OCR 主任务
- `build/export/finalize_m3.py` — fatal 重试 + 最终失败列表
- `build/export/seed_pages_m3.py` — 生成 D1 灌库 SQL
- `build/export/llm_structure.py` / `llm_structure_pages.py` — (废弃, 走 LLM 结构化中间产物路径)

### RAG 召回粒度

每页 1 个 article, 1966 B/article, 适合 FTS5 trigram + bge embedding 双路召回。
