# Cloudflare Pages 部署指南

> 阶段 E 的 `query/worker/`(Workers API)和阶段 F 的 `web/`(前端)都部署到 Cloudflare 免费层。

## 前置

1. **Cloudflare 账户**(已有 `guoguoping@gmail.com`)
2. **域名**(可选,先用 `*.pages.dev` 子域)
3. **Node.js 20+** + `npm install -g wrangler`

## 一·配置 Cloudflare

```bash
# 1. 登录(会弹浏览器 OAuth)
wrangler login

# 2. 创建 R2 bucket(放索引 + 法规原文)
wrangler r2 bucket create siliao-index

# 3. 创建 D1 数据库(放元数据)
wrangler d1 create siliao-db
# 输出形如:
#   database_id = "abc123-..."
# 把这个 ID 填到 query/worker/wrangler.toml 的 [[d1_databases]] 里

# 4. 创建 Vectorize 索引(向量检索,1024 维 bge-large-zh)
wrangler vectorize create feed-law-index --dimensions=1024 --metric=cosine

# 5. 创建 Pages 项目
wrangler pages project create siliao-web --production-branch main
```

## 二·填充数据(只有你跑过 GraphRAG 才有)

### 2.1 上传索引到 R2

```bash
# flatten 后 data/index/ 下应有:
#   entities.json  relationships.json  text_units.json
#   communities.json  community_reports.json  documents.json
cd build/export
for f in entities relationships text_units communities community_reports documents; do
    wrangler r2 object put "siliao-index/${f}.json" --file "../../data/index/${f}.json" --remote
done

# 上传章节 Markdown(R2 里 chapters/ch01.md 等)
for ch in data/markdown/*/chapters/*.md; do
    name=$(basename "$ch")
    doc=$(basename "$(dirname "$(dirname "$ch")")")
    wrangler r2 object put "siliao-index/${doc}/chapters/${name}" --file "$ch" --remote
done
```

### 2.2 灌 Vectorize

```bash
# 1. 启动本地 bge 服务(llama.cpp / vllm 都行)
#    例:  llama.cpp --server --model bge-large-zh-v1.5.gguf --port 8080

# 2. 生成 ndjson(把 chunks 转成 1024 维向量)
python build/export/embed_to_vectorize.py \
    data/index/text_units.json \
    data/index/vectors.ndjson

# 3. 灌入
wrangler vectorize insert feed-law-index --file data/index/vectors.ndjson
```

### 2.3 初始化 D1 schema

```bash
cd query/worker
wrangler d1 execute siliao-db --remote --file ./schema.sql
```

## 三·部署 Workers API

```bash
cd query/worker

# 设置 wrangler.toml 里的 REPLACE_AFTER_WRANGLER_D1_CREATE 为真实 database_id
# vim wrangler.toml

# 设置环境变量(如果有 MiniMax key,在这里注入,而不是 .env)
wrangler secret put DEEPSEEK_API_KEY  # 或 MINIMAX_API_KEY

# 部署
wrangler deploy
# 输出形如:
#   Published siliao-api
#   https://siliao-api.<your-subdomain>.workers.dev
```

测试:
```bash
curl https://siliao-api.<sub>.workers.dev/api/documents
```

## 四·部署前端 Pages

### 方式 A: 连接 GitHub 自动部署(推荐)

1. 推送仓库到 GitHub(已完成:`github.com/Guoguoping1008/siliao`)
2. Cloudflare Dashboard → Pages → Connect to Git → 选仓库
3. 配置:
   - **Framework preset**: Vite
   - **Build command**: `cd web && npm run build`
   - **Build output directory**: `web/dist`
   - **Root directory**: `/`(空)
   - **Environment variables**:
     - `VITE_USE_MOCK` = `false`(切到生产 API)
     - `VITE_API_BASE` = `https://siliao-api.<sub>.workers.dev`(可选,默认用同域 proxy)
4. 触发首次部署:Save and Deploy

### 方式 B: 命令行直传(更快调试)

```bash
cd web
npm run build
wrangler pages deploy dist --project-name siliao-web
```

## 五·配置自定义域(可选)

Pages → 项目 → Custom domains → 添加 `siliao.example.com`
Workers → 项目 → Triggers → 添加 Routes:
- `siliao.example.com/api/*` → `siliao-api`

## 六·本项目特殊配置

由于前端用 `BrowserRouter`,**Cloudflare Pages 需要 SPA fallback**:

```toml
# 创建 web/public/_redirects(或者 wrangler.toml 的 pages 配置)
echo "/*  /index.html  200" > web/public/_redirects
```

或 `web/_routes.json`:
```json
{
  "version": 1,
  "include": ["/*"],
  "exclude": ["/api/*"]
}
```

## 七·故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| 路由 404 刷成 Cloudflare 默认页 | 缺 SPA fallback | 加 `_redirects` 或 `_routes.json` |
| API 跨域错误 | Workers 没配 CORS | query/worker/src/index.ts 已有 CORS 头 |
| Vectorize 维度错误 | bge-m3 是 1024,text-embedding-3-* 是 1536 | 用 `wrangler vectorize delete` 重创建 |
| Workers 部署失败 | database_id 没填 | wrangler.toml 替换 `REPLACE_AFTER_WRANGLER_D1_CREATE` |
| 第一次 build 超时 | Pages 默认 20min,够用 | 如果 npm 慢,加 `npm ci --prefer-offline` |

## 八·回滚

- **Pages**:Dashboard → Deployments → 选旧版本 → Rollback
- **Workers**: `wrangler rollback` 或 Dashboard → Deployments → Rollback
- **D1**: `wrangler d1 execute siliao-db --remote --command "SELECT * FROM _cf_KB_history"`
- **R2**: R2 → Bucket → 选中 object → Version history → 恢复

## 九·CI/CD(可选)

`.github/workflows/deploy.yml`:

```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy-web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: cd web && npm ci && npm run build
      - uses: cloudflare/pages-action@v1
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          projectName: siliao-web
          directory: web/dist
          gitHubToken: ${{ secrets.GITHUB_TOKEN }}

  deploy-worker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: cd query/worker && npm ci
      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          workingDirectory: query/worker
          command: deploy
```

需要的 GitHub Secrets:
- `CLOUDFLARE_API_TOKEN` — Cloudflare Dashboard → My Profile → API Tokens → Create Token → Edit Cloudflare Pages / Workers
- `CLOUDFLARE_ACCOUNT_ID` — Dashboard 右下角