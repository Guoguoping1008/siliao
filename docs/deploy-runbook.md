# 生产部署 Runbook

生产环境地址(2026-10-26 首次上线):

| 组件 | 地址 | 状态 |
|---|---|---|
| 前端 (Cloudflare Pages) | https://siliao-web.pages.dev | ✅ 已上线 |
| API (Cloudflare Workers) | https://siliao-api.guoguoping.workers.dev | ✅ 已上线 |
| API 代理 (Pages Functions) | https://siliao-web.pages.dev/api/* | ✅ 已上线 |
| D1 数据库 | `siliao-db` / `e406e21e-e770-4c97-822a-57178c347aa6` | ✅ 已灌 3145 条文 |
| R2 桶 | `siliao-index` | ⛔ **未开通**(见下) |
| bge 语义层 | 本机 `192.168.3.65:8080` | ⛔ 边缘连不到(见下) |
| DeepSeek | `deepseek-chat` | ⛔ key 未设(见下) |

---

## 一、上线前的前置动作(都要人工做一次)

### 1.1 开通 R2(阻塞 excerpt / 原文正文)

账户的 R2 还没激活, API 返 `403 Please enable R2 through the Cloudflare Dashboard`。

1. 打开 https://dash.cloudflare.com → 左侧 **R2** → **Enable R2**
2. 首次开通要接受条款 + 绑支付方式(信用卡即可, 免费额度 10GB/月)
3. 激活后执行:

```bash
cd query/worker
npx wrangler r2 bucket create siliao-index

# 取消 wrangler.toml 里 [[r2_buckets]] 那段的注释
python build/export/push_minimax_r2.py --remote     # 推 3674 个对象
npx wrangler deploy
```

不做的后果: 检索照常能出结果, 但 `/api/article` 的正文是空串, 搜索结果的 excerpt 是空。

### 1.2 设置 DeepSeek key(阻塞 QA 生成)

```bash
cd query/worker
echo "sk-你的key" | npx wrangler secret put DEEPSEEK_API_KEY
```

不做的后果: `/api/qa` 的**检索段正常**(SSE 先吐 `meta` + 8 条证据), 但生成段返 401。

### 1.3 bge 语义层上生产(可选, 提升召回)

Cloudflare 边缘连不到本机 LAN IP, 所以生产目前跑的是**纯 FTS5**。两个方案:

- **A. 部署到公网**: 把 `build/proxy/bge_server.py` 放到 VPS / Cloud Container,
  用 HTTPS endpoint 填进 `wrangler.toml` 的 `BGE_SERVER_URL`
- **B. 换 Workers AI**: 用 `@cf/baai/bge-large-zh` 替换, 无需自建服务(注意维度和
  当前 1024 维 bge-m3 不一致, 要重跑 embedding)

量化收益(本地同语料实测): recall@20 56% → 68%, MRR 0.544 → 0.647, 业务 query MRR +47%。

---

## 一之二、配置 GitHub Actions 自动部署(一次性)

`deploy.yml` 需要两个仓库 secret, **现在还没配**(2026-10-26 实测:
`GET /repos/Guoguoping1008/siliao/actions/secrets` 返回 0 个,
workflow 里 `CLOUDFLARE_API_TOKEN:` 是空的 → 部署必挂)。

需要 **repo admin 权限**的人操作:

1. Cloudflare API Token:
   Dashboard → My Profile → API Tokens → **Create Token**
   → 模板选 **Edit Cloudflare Workers**(含 Workers Scripts:Edit / D1:Edit / R2:Edit)
   → 复制 token
2. Account ID: Dashboard 右下角, 形如 `1b938cc261b000a03554b506985daabb`
3. 存进 GitHub:
   `gh secret set CLOUDFLARE_API_TOKEN` / `gh secret set CLOUDFLARE_ACCOUNT_ID`
   (或 Settings → Secrets and variables → Actions → New repository secret)

配好后 `deploy.yml` 会自动: 部署 Worker → 灌 Pages → **回读生产 API 校验**。

未配之前: 手动发布照常可用(见下一节), 只是 CI 的 Deploy job 会红,
并且会打印明确提示而不是玄学错误。

## 二、日常发布

```bash
# 1. 重建索引(语料改了才需要)
python build/export/ingest_minimax.py --apply
python build/export/ingest_minimax.py --apply --seed-only   # 只出 seed.sql

# 2. 灌远端 D1
cd query/worker
npx wrangler d1 execute siliao-db --remote --file ../../build/export/seed.sql

# 3. 部署 Worker
npx wrangler deploy

# 4. 构建 + 部署前端(必须 VITE_USE_MOCK=false)
cd ../../web
VITE_USE_MOCK=false npm run build
npx wrangler pages deploy dist --project-name siliao-web --branch main --commit-dirty=true
```

**坑**:
- `wrangler pages deploy` 必须从 `web/` 目录跑, 且要带 `--commit-dirty=true`,
  否则 Functions bundle 不会被打进去(代理函数丢失, 前端拿不到 API)
- 前端构建**必须** `VITE_USE_MOCK=false`, 否则线上加载 mock 语料, 看起来能用其实没连 Worker
- `npx wrangler pages deploy` 若在 `query/worker/` 下跑, 会读到 worker 的 wrangler.toml
  并因缺 `pages_build_output_dir` 报警告

---

## 三、验证

```bash
# 静态站点
curl -s https://siliao-web.pages.dev | grep -o '<title>[^<]*'

# API 代理(应看到 X-Proxied-By: siliao-pages-functions)
curl -sI https://siliao-web.pages.dev/api/documents | grep -i x-proxied-by

# 文档数(应 196)
curl -s https://siliao-web.pages.dev/api/documents | python -c "import json,sys; print(len(json.load(sys.stdin)['documents']))"

# 搜索(应 20 hits)
curl -s 'https://siliao-web.pages.dev/api/search?q=新兽药注册办法' | python -c "import json,sys; print(len(json.load(sys.stdin)['hits']))"

# QA 检索段(SSE 应先出 meta)
curl -sN -X POST https://siliao-web.pages.dev/api/qa \
  -H 'Content-Type: application/json' -d '{"q":"新兽药注册办法","stream":true}' | head -3
```

---

## 四、资源清单

Cloudflare 账户: `Guoguoping@gmail.com's Account`
Account ID: `1b938cc261b000a03554b506985daabb`

| 资源 | 名称 | ID / URL |
|---|---|---|
| D1 | siliao-db | e406e21e-e770-4c97-822a-57178c347aa6 |
| Worker | siliao-api | siliao-api.guoguoping.workers.dev |
| Pages | siliao-web | siliao-web.pages.dev |
| Vectorize | feed-law-index | (已绑定, 暂未启用) |
| Pages secret | API_BASE | https://siliao-api.guoguoping.workers.dev |
