# 农业饲料法规在线知识库

> 基于《中国农业饲料法规 2026 版》搭建的 RAG 知识库;按章节切分,支持扫描版 OCR 增量更新。

## 形态
- Web App(响应式),Cloudflare Pages 免费托管
- 检索引擎:GraphRAG(章节级 chunks + 实体关系图谱)
- LLM:DeepSeek-V3 · Embedding:bge-large-zh-v1.5(本地)

## 目录结构
```
siliao/
├── data/
│   ├── raw/              # 原始 PDF/扫描版(待你提供)
│   ├── markdown/         # OCR 产物 + 章节切分
│   └── index/            # GraphRAG 索引产物
├── build/                # 构建脚本(OCR / GraphRAG / 导出)
├── query/                # Cloudflare Workers 查询层
├── web/                  # 前端 Vite + React 18
└── docs/INDEX.md         # 法规目录索引
```

## 阶段进度
- [x] A·项目骨架
- [ ] B·OCR + 章节切分
- [ ] C·GraphRAG 构建
- [ ] D·索引导出上传
- [ ] E·Cloudflare Workers
- [ ] F·前端 Web App
- [ ] G·E2E 验证

## 计划文档
完整实施计划: `.hermes/plans/2026-08-02_090000-cn-feed-law-rag.md`