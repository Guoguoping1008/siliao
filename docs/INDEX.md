# 法规目录索引

> 登记每部法规的元数据;OCR/GraphRAG 流程读取本表生成任务清单。

## 当前收录

| doc_id | 标题 | 文号 | 颁布日期 | 生效日期 | 章节数 | 文件 | 状态 |
|---|---|---|---|---|---|---|---|
| feed-law-2026 | 中国农业饲料法规 2026 版 | 农业农村部令 第X号 | 2026 | 2026 | 6 | `data/markdown/feed-law-2026/` | indexed |
| feed-law-collection-2023 | 饲料法规文件汇编 2023 | - | 2023 | 2023 | 5 | `data/markdown/feed-law-collection-2023/` | indexed |
| feed-trial-guideline-2023 | 饲料和饲料添加剂靶动物有效性评价试验指南(试行) | 饲料法规文件【2023】 | 2023 | 2023 | 15 | `data/markdown/feed-trial-guideline-2023/` | indexed |

## 元数据 JSON 模板(每部法规一份)

文件: `data/index/<doc_id>.meta.json`

```json
{
  "doc_id": "feed-law-2026",
  "title": "中国农业饲料法规 2026 版",
  "doc_number": "农业农村部令 第X号",
  "issuer": "农业农村部",
  "issue_date": "2026-XX-XX",
  "effective_date": "2026-XX-XX",
  "chapter_count": null,
  "article_count": null,
  "source_file": "data/raw/feed-law-2026.pdf",
  "scan_status": "ocr_pending|ocr_done|indexed",
  "version": "v1"
}
```

## 如何补入法规

1. 把 PDF/扫描版放进 `data/raw/`
2. 在本表登记一行 + 在 `data/index/` 写一份 `.meta.json`
3. 跑 `bash build/run_all.sh feed-law-2026`(待写)