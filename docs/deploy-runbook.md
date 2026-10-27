# 生产部署 Runbook

生产环境地址(2026-10-26 首次上线):

| 组件 | 地址 | 状态 |
|---|---|---|
| 前端 (Cloudflare Pages) | https://siliao-web.pages.dev | ✅ 已上线 |
| API (Cloudflare Workers) | https://siliao-api.guoguoping.workers.dev | ✅ 已上线 |
| API 代理 (Pages Functions) | https://siliao-web.pages.dev/api/* | ✅ 已上线 |
| D1 数据库 | `siliao-db` / `e406e21e-e770-4c97-822a-57178c347aa6` | ✅ 已灌 3145 条文 |
| R2 桶 | `siliao-index` | ➖ **不再需要**(正文已进 D1,见下) |
| bge 语义层 | `https://ns.hbnongfengyuan.cn` | ✅ **已上线**(见下) |
| LLM (MiniMax) | `MiniMax-Text-01` | ✅ 已接入 |

---

## 一、上线前的前置动作(都要人工做一次)

### 1.1 R2 —— ✅ 已不需要(正文改存 D1)

**原计划**: R2 存正文。但账户的 R2 没激活, API 返
`403 Please enable R2 through the Cloudflare Dashboard`, 而且激活要**人工去
Dashboard 接受条款 + 绑支付方式**(API 绕不过, OAuth token 也没有订阅管理权限)。

**改用 D1(2026-10-26)**, 理由:

| | R2 | D1 |
|---|---|---|
| 需要人工开通 | 是 | 否 |
| 正文总量 | 7.3 MB | 7.3 MB |
| 存储额度 | 10GB/月免费 | 5GB 免费(实际只占 1.2MB) |
| excerpt 怎么拿 | 20 次 R2.get() | **1 次 JOIN** |
| 每条 hit 延迟 | +1 网络往返 | 0 |

改完后 `wrangler.toml` 里 `[[r2_buckets]]` 保持注释状态, `INDEX_BUCKET` 变成可选
binding(代码里 `env.INDEX_BUCKET ? ... : null` 兼容两种)。

**灌正文用 D1 REST API 的 bound params**, 不用 `wrangler d1 execute --file`:

```bash
python build/export/push_d1_bodies.py
```

为什么不用 wrangler(两个坑):
1. wrangler 4.127+ 对「schema 变了」的库报 `D1_RESET_DO` —— 它想走迁移流程,
   不肯直接灌(而且那次失败**把远端表清空了**)。
2. 正文含真实换行, 拼进 SQL 字符串字面量会踩三个 SQLite 限制:
   字符串不能跨行 / 不认 `\n` 转义 / `|| char(10) ||` 拼接会让表达式树超 100 深度。

bound params 全绕过: 值不进 SQL 文本, 换行引号反斜杠原样传。

**D1 raw API 的三个限制**:
- 参数上限 **100 个变量**(不是 SQLite 默认的 999)→ 每行 8 列 → 每请求 12 行
- **多语句 + params 不支持** → 必须单语句多行 INSERT
- 占位符个数要**按实际批大小**生成, 否则最后一批报
  `Wrong number of parameter bindings`

### 1.2 LLM key ✅ 已用 MiniMax 顶上(2026-10-26)

**DeepSeek 的 key 余额不足**(实测 `402 Insufficient Balance`), 所以 LLM 换成了
MiniMax —— 它的 **OpenAI 兼容端点**与 DeepSeek 完全同协议:

| | DeepSeek | MiniMax |
|---|---|---|
| base | `https://api.deepseek.com/v1` | `https://api.minimaxi.com/v1` |
| 端点 | `/chat/completions` | `/chat/completions` ✅ 同路径 |
| 鉴权 | `Authorization: Bearer <key>` | 同 ✅ |
| 响应 | `{choices:[{message:{content}}]}` | 同 ✅ |
| 流式 | `data: {choices:[{delta:{content}}]}` | 同 ✅(但不发 `[DONE]`) |

**Worker 里已改成 provider 无关**: `llmConfig()` 优先读 `LLM_*`,
回退 `DEEPSEEK_*` —— 换 provider 只改 3 个配置值, 不动代码。

```bash
cd query/worker
echo "<minimax key>" | npx wrangler secret put LLM_API_KEY
```

**模型选择**: 用 `MiniMax-Text-01`(干净输出)。
⚠️ 不要用 `MiniMax-M3` —— 它会把 `` 思考过程塞进 `delta.content`,
直接泄漏到用户看到的答案里。`abab6.5s-chat` 已下线(404)。

**不做的后果**: `/api/qa` 检索段正常(SSE 先吐 `meta` + 8 条证据), 生成段返 401。

**DeepSeek 充值后切回去**: 删掉 `wrangler.toml` 里的 `LLM_API_BASE`/`LLM_MODEL`
两行即可(自动回退 `DEEPSEEK_*`), 或者直接把 `LLM_API_BASE` 改成 DeepSeek 的地址。

### 1.3 bge 语义层上生产 ✅ 已完成(2026-10-26)

**部署位置**: `47.108.112.118`(已有的 prod 服务器), Docker 容器 `siliao-bge:1.0`,
nginx 反代, 公网入口 `https://ns.hbnongfengyuan.cn`。

**为什么复用 ns.hbnongfengyuan.cn**:
- 该子域 DNS 已解析到本机, 证书有效到 2026-12-22(SAN: ns + www.ns)
- 原站点反代 `127.0.0.1:9999`, 该端口空置(原业务已下线返回 502)
- → 直接改指向 bge, **不动 DNS、不签新证书**

**关键坑**:
- `bge_server.py` 默认推导 `Path(__file__).parent.parent.parent/'.models'/'hf'`。
  容器里 `__file__` = `/app/bge_server.py` → 推导出 `/.models/hf`(不存在),
  报 `couldn't find them in the cached files`。**必须显式设
  `BGE_CACHE_DIR=/opt/models`**(模型 build 时烤进镜像的位置)。
- 服务器自带 python3.6(CentOS 7), sentence-transformers 要 3.9+ → 必须容器化。
- 该服务器在国内, **DNS 被污染**: `*.workers.dev` 会解析到假 IP,
  但 `api.cloudflare.com` 正常。所以服务器调 Cloudflare API 用域名,
  调 workers.dev 要走 IP。
- 中国网络下 `huggingface.co` 不通, 必须 `HF_ENDPOINT=https://hf-mirror.com`
  (镜像里已 bake 死, 运行时完全离线)。

**实测收益**(经公网 endpoint 跑评测集):

| 指标 | 纯 FTS5 | 生产 hybrid | 变化 |
|---|---|---|---|
| recall@10 | 76.0% | 76.0% | — |
| **recall@20** | 56.0% | **68.0%** | **+12pt** |
| **MRR** | 0.544 | **0.647** | **+19%** |
| **业务 query MRR** | 0.488 | **0.717** | **+47%** |
| negative 严格精度 | 100% | 100% | — |

**运维**:
```bash
ssh prod
docker logs -f siliao-bge                    # 日志
docker restart siliao-bge                    # 重启
docker exec siliao-bge python -c "..."       # 进容器排查
# nginx 配置: /usr/local/nginx/conf/conf.d/ns.hbnongfengyuan.cn.conf
# 语料缓存:  /opt/bge/data/{bge_m3_cache.json, articles_cache.json}
# 容器绑 127.0.0.1:8080, 只经 nginx 对外, 只开 /v1/search 与 /health
```

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

## 一之三、本地开发(修好了, 别再踩)

本地三个服务(都在跑):

```bash
# 1. Worker (8788) —— 必须用 wrangler.local.toml
cd query/worker
npx wrangler dev -c wrangler.local.toml --port 8788 --ip 127.0.0.1

# 2. 前端 (5173) —— 必须绑 127.0.0.1, 否则只监听 ::1
cd web
npx vite --host 127.0.0.1 --port 5173

# 3. bge 语义层 (8080)
cd ../..
HF_HUB_OFFLINE=1 BGE_HOST=0.0.0.0 BGE_PORT=8080 \
  BGE_CACHE=evals/bge_m3_cache.json BGE_ARTICLES=evals/articles_cache.json \
  python build/proxy/bge_server.py
```

### 为什么有两份 wrangler.toml

| 文件 | R2 binding | D1 remote | BGE | 用途 |
|---|---|---|---|---|
| `wrangler.toml` | **注释掉** | `true` | `""` | 远端部署(R2 未开通, 带 binding 会 deploy 失败) |
| `wrangler.local.toml` | 开启 | `false` | `192.168.3.65:8080` | 本地开发 |

三个必须记住的点:

1. **本地必须 `remote = false`** —— `true` 会让 miniflare 去连 Cloudflare 远端
   (R2 没开通直接连不上; D1 也会走网络)。
2. **本地必须用 `-c wrangler.local.toml`** —— 用主配置的话 R2 binding 不存在,
   `env.INDEX_BUCKET` 是 undefined, 表现是**搜索有结果但 excerpt 全空**
   (D1 的 FTS5 照常工作, 很容易误判成"部署成功但数据不全")。
3. **R2 key 必须 URL 编码** —— D1 的 `r2_object_key` 存原始中文, R2 里存的是
   `%E5%B0%81...` 编码形式。Worker 里的 `r2Key()` 负责逐段 encode。
   手工 `wrangler r2 object get` 时也要传编码后的 key。

### 本地自检

```bash
python - <<'EOF'
import json, urllib.request, urllib.parse
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 绕开系统代理
def get(u):
    return json.loads(op.open(urllib.request.Request(u, headers={"User-Agent":"curl/8"}), timeout=60).read())
d = get('http://127.0.0.1:8788/api/search?q=' + urllib.parse.quote('新兽药注册办法'))
ne = sum(1 for x in d['hits'] if x.get('excerpt'))
print(f"hits={len(d['hits'])} excerpt非空={ne}")
assert ne == len(d['hits']), "excerpt 空 → R2 binding 没生效, 检查 wrangler.local.toml"
EOF
```

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

## 五、CI 状态(2026-10-26)

| Workflow | 状态 | 说明 |
|---|---|---|
| CI | ✅ 5/5 绿 | Web vitest 34/34 · e2e 9/9 · typecheck+build · Worker typecheck · Eval(门禁 recall@10 ≥70%, 实测 76.0%) |
| Deploy | ⛔ 卡在凭据 | 仓库 0 个 secret,见「一之二」 |

Deploy 修好 secret 之后就会自动跑,不用手动。
