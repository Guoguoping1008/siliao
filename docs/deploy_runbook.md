# Cloudflare 部署操作员手册

> 适用于本地 miniflare 验证后的真实环境部署。**所有需要 OAuth / 浏览器交互
> 的命令(wrangler login)无法在 sandbox 中完成,需要你手动跑。**

## 0. 前置

- Cloudflare 账户(已有 `guoguoping@gmail.com`)
- Node.js 20+ + npm
- 当前仓库已 commit 到 main 分支(6 个 commit 在本地,**未 push**)

## 1. 安装 wrangler

```bash
cd query/worker
npm install wrangler
```

(已在本仓库 commit)

## 2. 登录 Cloudflare

```bash
npx wrangler login
```

会跳浏览器 → 选 `guoguoping@gmail.com` → 同意授权 → 终端显示成功。
**这一步必须人工操作。**

## 3. 创建 Cloudflare 资源

```bash
# R2 bucket
npx wrangler r2 bucket create siliao-index

# D1 数据库
npx wrangler d1 create siliao-db
# 输出形如:
#   database_id = "abc123-..."
# 把这个 ID 填到 query/worker/wrangler.toml 的 database_id 字段

# Vectorize(本期不启用,但 ADR-001 留接口)
npx wrangler vectorize create feed-law-index --dimensions=1024 --metric=cosine

# Pages 项目(前端)
npx wrangler pages project create siliao-web --production-branch main
```

## 4. 推送数据

```bash
# 4.1 初始化 D1 schema
cd query/worker
npx wrangler d1 execute siliao-db --remote --file ./schema.sql

# 4.2 灌 D1 元数据 + FTS5
cd ../..
python build/export/seed_d1.py \
    data/markdown/feed-law-2026/articles.json \
    data/markdown/feed-law-2026/chapters.json
cd query/worker
npx wrangler d1 execute siliao-db --remote --file ../../build/export/seed.sql

# 4.3 推 R2(22 个文件)
cd ../..
for f in data/markdown/feed-law-2026/articles/*.md \
         data/markdown/feed-law-2026/chapters/*.md; do
  rel="${f#data/markdown/feed-law-2026/}"
  (cd query/worker && npx wrangler r2 object put "siliao-index/feed-law-2026/${rel}" --file "../../${f}" --remote >/dev/null 2>&1 && echo "✓ ${rel}")
done
```

## 5. 设置 Worker 秘密

```bash
cd query/worker
echo "$DEEPSEEK_API_KEY" | npx wrangler secret put DEEPSEEK_API_KEY
# 或:
npx wrangler secret put DEEPSEEK_API_KEY
# 粘贴你的 DeepSeek / MiniMax key
```

## 6. 部署 Worker

```bash
cd query/worker
npx wrangler deploy
# 输出形如:
#   Published siliao-api
#   https://siliao-api.<your-subdomain>.workers.dev
```

记下 Worker URL,前端要用。

## 7. 部署前端 Pages

方式 A · GitHub 集成(推荐)
1. 推仓库到 GitHub:`git push origin main`
2. Cloudflare Dashboard → Pages → Connect to Git
3. 配置:
   - Framework preset: Vite
   - Build command: `cd web && npm ci && npm run build`
   - Build output directory: `web/dist`
   - Environment variables:
     - `VITE_USE_MOCK = false`
     - `VITE_API_BASE = https://siliao-api.<sub>.workers.dev`
       (可选;不填时用同域 Pages Functions proxy)

方式 B · 直传(更快调试)
```bash
cd web
npm run build
npx wrangler pages deploy dist --project-name siliao-web
```

## 8. 烟测

```bash
WORKER="https://siliao-api.<sub>.workers.dev"
WEB="https://siliao-web.pages.dev"

# Worker API
curl -s "$WORKER/api/documents"
curl -s "$WORKER/api/search?q=%E5%AE%A1%E5%AE%9A" | jq '.hits | length'

# 前端打开浏览器
open "$WEB"
```

预期:
- `/api/documents` 返回 1 部法规
- `/api/search?q=审定` 返回 ≥3 条 hits
- 前端首页能加载章节列表,搜索"审定"有结果

## 9. 回滚

- **Pages**:Dashboard → Deployments → 选旧版本 → Rollback
- **Workers**: `npx wrangler rollback` 或 Dashboard → Rollback
- **D1**: `wrangler d1 execute siliao-db --remote --command "SELECT * FROM _cf_KB_history"`

## 10. 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| Workers 部署失败 | database_id 没填 | 替换 wrangler.toml 占位符 |
| R2 excerpt 为空 | r2_object_key 字段错(已修) | 用 doc_id/articles/<id>.md 路径 |
| 检索 0 命中 | FTS5 索引未初始化 | 重跑 schema.sql + seed.sql |
| Pages 404 | SPA fallback 缺失 | 加 web/public/_redirects(已存在) |
| Workers 跨域错误 | CORS 头缺失 | query/worker/src/index.ts 已加 |

## 11. 本地 miniflare 复刻

无 OAuth,纯本地:

```bash
# D1
cd query/worker
npx wrangler d1 execute siliao-db --local --file ./schema.sql
npx wrangler d1 execute siliao-db --local --file ../../build/export/seed.sql

# R2
for f in ../../data/markdown/feed-law-2026/articles/*.md \
         ../../data/markdown/feed-law-2026/chapters/*.md; do
  rel="${f#../../data/markdown/feed-law-2026/}"
  (npx wrangler r2 object put "siliao-index/feed-law-2026/${rel}" --file "${f}" --local >/dev/null 2>&1)
done

# Worker + 前端
npx wrangler dev --local --port 8788 &  # 后台
cd ../../web && VITE_USE_MOCK=false npm run dev &
# curl http://localhost:5173/api/documents 应返回数据
```
