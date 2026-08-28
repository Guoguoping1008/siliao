# 农业饲料法规在线知识库

> 基于《中国农业饲料法规 2026 版》搭建的 RAG 知识库;按章节切分,支持扫描版 OCR 增量更新。

## 形态

- Web App(响应式),Cloudflare Pages 免费托管
- 检索引擎:D1 FTS5(trigram) + LIKE 兜底(章节级召回 recall@10 = 95.7%,MRR = 0.957)
- LLM:DeepSeek-V3 · Embedding:bge-large-zh-v1.5(本地,plan B 接外部)
- RAG 问答流式输出,带引用校验(LLM 编造引用自动标红)

## 目录结构

```
siliao/
├── data/
│   ├── raw/              # 原始法规(.md,样本)
│   ├── markdown/         # OCR 产物 + 章节切分
│   └── index/            # GraphRAG 索引产物(待启用)
├── build/
│   ├── ingest.sh         # OCR + 章节切分入口
│   ├── ocr/              # MinerU + chapter_splitter
│   ├── graphrag/         # 实体/关系抽取(待启用)
│   ├── export/           # flatten + seed_d1 + push_to_r2
│   ├── proxy/            # bge_server.py + openai_to_minimax.py
│   └── run_all.sh        # 一条命令完成 ingest → seed → push
├── query/worker/         # Cloudflare Workers + wrangler.toml
├── web/                  # Vite + React 18 + Tailwind
├── evals/                # retrieval.jsonl + faithfulness.jsonl
├── docs/
│   ├── INDEX.md          # 法规目录登记
│   ├── adr/              # 架构决策记录
│   └── deploy_runbook.md # CF 部署操作员手册
└── .github/
    ├── workflows/ci.yml       # PR/push: build + typecheck + eval
    ├── workflows/deploy.yml   # main: Pages + Worker 自动部署
    └── dependabot.yml         # 每周依赖升级 PR
```

## 阶段进度

- [x] A·项目骨架
- [x] B·章节切分器(chapter_splitter.py)
- [x] C·GraphRAG 配置(待跑,需要 DeepSeek key)
- [x] D·灌库脚本(seed_d1 + push_to_r2)
- [x] E·Workers FTS5 + 完整路由
- [x] F·前端 Vite + React + Tailwind(深色/移动端/快捷键)
- [x] G·Eval 体系(retrieval 28 用例 + faithfulness 5 用例)
- [x] 端到端部署链路打通(本地 miniflare 验证)
- [ ] 真 Cloudflare 上线(等 wrangler login)

## 性能基线

| 指标 | 当前值 | 来源 |
|---|---|---|
| 检索 recall@10 | 95.7%(22/23) | evals/retrieval.jsonl |
| 检索 MRR | 0.957 | evals/eval_retrieval.py |
| 检索 negative 精度 | 100%(5/5) | 语料外 query 0 召回 |
| RAG faithfulness | 100%(5/5) | 引用 + 未找到兜底校验 |
| 前端体积 | 193KB / 61KB gzip | web/build |
| 检索延迟 | D1 FTS5 ~5-15ms | 边缘节点 |

## 快速开始(本地)

```bash
# 1. 装依赖
cd web && npm install
cd ../query/worker && npm install

# 2. 跑章节切分(已有样本)
cd ../..
python build/export/seed_d1.py \
    data/markdown/feed-law-2026/articles.json \
    data/markdown/feed-law-2026/chapters.json

# 3. 起 Worker(miniflare 本地 D1 + R2)
cd query/worker
npx wrangler d1 execute siliao-db --local --file ./schema.sql
npx wrangler d1 execute siliao-db --local --file ../../build/export/seed.sql
for f in ../../data/markdown/feed-law-2026/articles/*.md \
         ../../data/markdown/feed-law-2026/chapters/*.md; do
  rel="${f#../../data/markdown/feed-law-2026/}"
  (npx wrangler r2 object put "siliao-index/feed-law-2026/${rel}" --file "${f}" --local >/dev/null 2>&1)
done
npx wrangler dev --local --port 8788 &

# 4. 起前端(默认走 mock,VITE_USE_MOCK=false 走真 worker)
cd ../../web
npm run dev
```

## 真部署

见 `docs/deploy_runbook.md`(11 步操作员手册)。

## 计划文档

完整实施计划:`.hermes/plans/2026-08-02_090000-cn-feed-law-rag.md`
技术决策:`docs/adr/0001-fts5-trigram-search.md`

## 后续增量

- 法规新版本:丢进 `data/raw/` 跑 `build/run_all.sh <doc_id>`
- 扫描版:必须先 MinerU,后面流程相同
- 接 bge embedding:触发条件 eval recall < 80%(当前 95.7% 充足,推迟)
- GraphRAG 真跑:需 DeepSeek API Key
