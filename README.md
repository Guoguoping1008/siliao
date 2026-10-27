# 农业饲料法规在线知识库

> 基于《中国农业饲料法规 2026 版》扫描件 OCR 全量重建的 RAG 知识库。
> 语料: `minimax/` 1021 页 → 196 份法规 / 529 章 / 3145 条文。

## 🟢 生产环境(2026-10-26 上线)

| 组件 | 地址 |
|---|---|
| 前端 | **https://siliao-web.pages.dev** |
| API | https://siliao-api.guoguoping.workers.dev |
| API 代理 | https://siliao-web.pages.dev/api/* (Pages Functions) |

D1 已灌满 196 文档 / 529 章 / 3145 条文。
**bge 语义层已上线**(`https://ns.hbnongfengyuan.cn`,Docker 容器 + nginx 反代),
生产跑的是 FTS5 + bge hybrid。
**LLM 已接入 MiniMax**(OpenAI 兼容端点,DeepSeek key 余额不足故切换)。
**正文存 D1**(`articles.body`,1.2MB)—— 不依赖 R2,故**无需人工开通任何 Cloudflare 付费产品**。
检索 = D1 FTS5 + bge-m3 公网 hybrid;问答 = MiniMax。
详见 [`docs/deploy-runbook.md`](docs/deploy-runbook.md)。

## 形态

- Web App(响应式),Cloudflare Pages 免费托管
- 检索引擎:D1 FTS5(trigram) **phrase 优先 + bigram RRF + 标题加权** ⊕ bge-m3 语义层
- LLM:MiniMax-Text-01(provider 无关,兼容 DeepSeek) · Embedding:bge-m3(公网自建)
- RAG 问答流式输出,带引用校验(LLM 编造引用自动标红)

## 目录结构

```
siliao/
├── minimax/              # OCR 成品语料树(章/节/文件 三层, 1021 页) —— 事实源
├── data/
│   ├── index/minimax/    # 摄入产物: articles.json / chapters.json / documents.json + 逐条 md
│   ├── raw/              # 旧样本语料(已废)
│   └── markdown/         # 旧切分器产物(已废)
├── build/
│   ├── ocr/              # OCR 流水线
│   ├── export/
│   │   ├── ingest_minimax.py    # minimax/ → 索引产物 + seed.sql
│   │   ├── push_minimax_r2.py   # 推 R2(local wrangler / remote S3 API)
│   │   ├── embed_articles.py    # bge-m3 embedding
│   │   └── seed_d1.py           # 旧语料灌库(保留)
│   ├── graphrag/         # 实体/关系抽取(待启用)
│   └── proxy/            # bge_server.py + openai_to_minimax.py
├── query/worker/         # Cloudflare Workers + wrangler.toml
├── web/                  # Vite + React 18 + Tailwind
├── evals/                # eval_minimax.py + retrieval/faithfulness 用例
├── docs/adr/             # 架构决策记录
└── .github/workflows/    # CI: typecheck + test + build + eval
```

## 阶段进度

- [x] A·项目骨架
- [x] B·章节切分器(旧语料)
- [x] D·灌库脚本(seed_d1 + push_to_r2)
- [x] E·Workers 路由(检索/章节/条文/实体/QA SSE)
- [x] F·前端 Vite + React + Tailwind
- [x] G·Eval 体系
- [x] 端到端部署链路打通(本地 miniflare 验证)
- [x] **OCR 全量 1021 页 → minimax/ 语料树**
- [x] **语料重建: 196 文档 / 529 章 / 3145 条文**
- [x] **检索重构: phrase 优先 + bigram RRF + 标题加权**
- [x] **bge-m3 语义层在新语料上重算 + 部署到公网**(生产 hybrid 已生效)
- [x] **真 Cloudflare 上线**(2026-10-26)

## 性能基线

| 指标 | 纯 FTS5 | 生产 hybrid | 来源 |
|---|---|---|---|
| 检索 recall@10(minimax 语料, 50 用例) | 76.0% | **76.0%** | evals/eval_minimax.py |
| 检索 recall@20 | 56.0% | **68.0%** | 同上 |
| 检索 MRR | 0.544 | **0.647** | 同上 |
| ├ 业务 query(20 条自然语言问句) | recall@10 75.0% / MRR 0.488 | recall@10 **80.0%** / MRR **0.717** | 同上 |
| └ 语料派生 query(30 条正文片段) | recall@10 76.7% / MRR 0.581 | recall@10 73.3% / MRR 0.600 | 同上 |
| negative 严格精度 | **100%** (0/4 真命中) | **100%** | 同上 |
| 检索对比:重构前(长 query 直接 MATCH) | recall@10 25%(业务 query) | ADR-003 |
| 检索对比:纯 FTS5(不接 bge) | MRR 0.544 / 业务 MRR 0.488 | EVAL_NO_BGE=1 |
| 前端单元测试 | 34/34 通过 | vitest,4 个测试文件 |
| 前端 e2e 测试 | 9/9 通过 | Playwright,CI 自动装 Chromium |
| 前端体积 | 197.51KB / 62.76KB gzip(主 chunk) | web/dist |
| 检索延迟 | D1 FTS5 ~5-15ms;gram 路径 2 批 D1 batch | 边缘节点 |

> **bge 语义层**(可选,本地跑 `build/proxy/bge_server.py`):
> 业务 query 的 MRR 从 0.488 → **0.717**(+47%)——这是纯 FTS5 拿不到的语义近义召回。

## 快速开始(本地)

```bash
# 1. 装依赖
cd web && npm install
cd ../query/worker && npm install

# 2. 摄入: minimax/ → 索引产物 + seed.sql
cd ../..
python build/export/ingest_minimax.py

# 3. 起 Worker(miniflare 本地 D1 + R2)
cd query/worker
npx wrangler d1 execute siliao-db --local --file ./schema.sql
npx wrangler d1 execute siliao-db --local --file ../../build/export/seed.sql

# 4. 推 R2(3674 个对象, local 走 wrangler; 线上走 S3 API)
cd ../..
python build/export/push_minimax_r2.py            # local
python build/export/push_minimax_r2.py --remote   # 真 Cloudflare

# 5. (可选)起 bge 语义服务 —— 不起则自动退化为纯 FTS5
cd ..
HF_HUB_OFFLINE=1 BGE_HOST=0.0.0.0 BGE_PORT=8080 \
  BGE_CACHE=$PWD/evals/bge_m3_cache.json \
  BGE_ARTICLES=$PWD/evals/articles_cache.json \
  python build/proxy/bge_server.py &

# 6. 起 Worker(BGE_SERVER_URL 要填**本机 LAN IP**, 127.0.0.1 在 miniflare 沙箱里指不到宿主)
cd query/worker
npx wrangler dev --local --port 8788 --ip 127.0.0.1

# 7. 起前端(默认走 mock;VITE_USE_MOCK=false 走真 worker)
cd ../../web
npm run dev
```

## 真部署

见 `docs/deploy_runbook.md` 与 `docs/adr/0003-minimax-corpus-rebuild-and-bigram-retrieval.md`。

## 技术决策

- `docs/adr/0001-fts5-trigram-search.md` —— 检索后端选型
- `docs/adr/0003-minimax-corpus-rebuild-and-bigram-retrieval.md` —— **语料重建 + 检索路径重构**

## 后续增量

- 新一版法规:放进 `minimax/` 对应目录 → 重跑 `ingest_minimax.py` → 重灌 D1/R2
- bge 语义召回:`evals/bge_m3_cache.json` 需为新语料重算(`build/export/embed_articles.py`),
  生产 Worker 通过 `BGE_SERVER_URL` 访问外部 bge 服务(见 `build/proxy/`)
- GraphRAG 真跑:需 DeepSeek API Key
