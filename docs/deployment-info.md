# 部署信息(2026-10-27)

> 一页看完所有生产资源。改任何一项,同步更新本文 + `docs/deploy-runbook.md`。

---

## 一、生产地址

| 组件 | 地址 | 说明 |
|---|---|---|
| **前端** | **https://siliao-web.pages.dev** | Cloudflare Pages,构建产物 `web/dist` |
| **API** | https://siliao-api.guoguoping.workers.dev | Cloudflare Workers(名称 `siliao-api`) |
| **API 代理** | https://siliao-web.pages.dev/api/* | Pages Functions(`web/functions/api/[[path]].ts`) |
| **bge 语义层** | https://ns.hbnongfengyuan.cn | 自建服务器,Docker 容器反代 |
| **D1 数据库** | `siliao-db` | `e406e21e-e770-4c97-822a-57178c347aa6` |

---

## 二、Cloudflare 资源

| 项 | 值 |
|---|---|
| 账户 | `Guoguoping@gmail.com's Account` |
| Account ID | `1b938cc261b000a03554b506985daabb` |
| Worker | `siliao-api` |
| Pages 项目 | `siliao-web`(production branch = `main`) |
| D1 | `siliao-db` / `e406e21e-e770-4c97-822a-57178c347aa6` |
| Vectorize | `feed-law-index`(已绑定,暂未启用) |
| R2 | **未开通,也不需要** —— 正文改存 D1(见下) |

### Worker 环境变量与绑定

**绑定**:`DB`(D1)、`VECTOR`(Vectorize,未启用)、`AI`(Workers AI)

**环境变量**(`query/worker/wrangler.toml` 的 `[vars]`):

| 变量 | 值 |
|---|---|
| `LLM_API_BASE` | `https://api.minimaxi.com/v1` |
| `LLM_MODEL` | `MiniMax-Text-01` |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1`(回退用) |
| `DEEPSEEK_MODEL` | `deepseek-chat`(回退用) |
| `BGE_SERVER_URL` | `https://ns.hbnongfengyuan.cn` |

**secret**(不在 yaml 里):
- `LLM_API_KEY` —— MiniMax key
- `DEEPSEEK_API_KEY` —— DeepSeek key(当前 402 余额不足,留着备用)

### D1 数据量

| 表 | 行数 | 说明 |
|---|---|---|
| `documents` | 196 | 法规文档(177 法规 + 19 目录/封面) |
| `chapters` | 529 | 章/节 |
| `articles` | 3145 | 条文(**正文在 `body` 列,1.22MB**) |
| `articles_fts` | 2959 | FTS5 全文索引(目录/封面 186 条不入索引) |

> ⚠️ **正文存 D1 不存 R2**:R2 激活要人工去 Dashboard 接受条款 + 绑支付方式,
> API 绕不过。而正文只有 7.3MB,D1 免费额度 5GB —— 换个地方存,顺带更快:
> excerpt 从「20 次 R2.get()」变成「1 次 JOIN」。
> 灌正文用 `python build/export/push_d1_bodies.py`(用 REST bound params,
> 别用 `wrangler d1 execute --file` —— 会报 `D1_RESET_DO` 并清空表)。

---

## 三、bge 语义层服务器

| 项 | 值 |
|---|---|
| **主机** | `47.108.112.118`(Aliyun,内网 `172.25.151.173`) |
| **SSH** | `ssh prod`(别名已配 `~/.ssh/config`,root + `id_rsa`) |
| **系统** | CentOS Linux 7.9.2009 |
| **规格** | 4 核 / 16 GB 内存 |
| **磁盘** | 99 GB,已用 40 GB(**剩 55 GB,42%**) |
| Docker | 26.1.4 |
| nginx | 1.19.9(`/usr/local/nginx/`,配置在 `conf/conf.d/`) |
| Python | 3.6.8(**太老**,故 bge 必须容器化) |

### bge 容器

| 项 | 值 |
|---|---|
| 镜像 | `siliao-bge:1.0`(6.35 GB,模型烤进镜像) |
| 容器 | `siliao-bge`,`--restart unless-stopped`,绑 `127.0.0.1:8080` |
| 限制 | `--memory=6g --cpus=3` |
| 语料 | `/opt/bge/data/{bge_m3_cache.json, articles_cache.json}` |
| 模型 | `/opt/models`(**镜像内**)→ 运行时 `BGE_CACHE_DIR=/opt/models` |
| nginx 配置 | `/usr/local/nginx/conf/conf.d/ns.hbnongfengyuan.cn.conf` |
| 证书 | `/usr/local/nginx/cert/ns.hbnongfengyuan.cn.pem`(有效至 **2026-12-22**) |
| 日志 | `docker logs siliao-bge` / `/var/log/nginx/bge.access.log` |

**为什么复用 `ns.hbnongfengyuan.cn`**:该子域 DNS 已指向本机,证书 SAN 覆盖
`ns` + `www.ns`,原站点反代 9999 端口已下线(502)→ 改指向 bge,
**不动 DNS、不签新证书**。

**只暴露 `/v1/search` 与 `/health`**,`/v1/embeddings` 被 nginx 挡掉。

### 运维命令

```bash
ssh prod
docker logs -f siliao-bge                    # 日志
docker restart siliao-bge                    # 重启
docker exec siliao-bge python -c "..."       # 进容器排查
curl -s http://127.0.0.1:8080/health        # 本机探活
```

### 磁盘

2026-10-27 已清理完毕:`/root/logs/csp` 的 47 GB 日志清掉后,
磁盘从 **92% → 42%**(40G/99G,剩 55G)。

当前占用 TOP3:`/var/lib/docker` 14G(bge 镜像 6.35G + 基础镜像)、
`/opt` 8.1G(其他业务项目)、`/root/logs/nacos` 396M。

> bge 的语料(`/opt/bge/data/`)与应用文件(`/opt/bge/app/`)在清理中未受影响,
> 容器全程 healthy(uptime 20h+)。

---

## 四、GitHub Actions

仓库:`https://github.com/Guoguoping1008/siliao.git`
分支:`deploy/c-b-hybrid`(当前生产分支)

### 已配置的 secret

| 名称 | 内容 |
|---|---|
| `CLOUDFLARE_API_TOKEN` | wrangler 的 OAuth token(有 Workers/Pages/D1 写权限) |
| `CLOUDFLARE_ACCOUNT_ID` | `1b938cc261b000a03554b506985daabb` |

> 设置方式(sealed box 加密,不经明文):
> ```bash
> gh secret set CLOUDFLARE_API_TOKEN < <(echo "$CF_TOKEN")
> gh secret set CLOUDFLARE_ACCOUNT_ID
> ```

### ⚠️ 当前状态: token 已过期(2026-10-27 09:2x)

**现象**:Deploy workflow 在「预检 Cloudflare 凭据」这一步失败, 报
`Invalid access token [code: 9109]`。本机 `npx wrangler deploy` 也同样 403。

**为什么 Pages 还能发**:Pages 部署走的是另一条鉴权路径(本机的
wrangler OAuth session), 不受 GitHub secret 里的 token 影响。
所以「Pages 成功 + Worker 失败」不代表配置错了 —— 就是那个 token 过期了。

**恢复**(两条路):
```bash
# A. 刷新 OAuth token(临时, 还会再过期)
cd query/worker && npx wrangler login
# 然后把新 token 写回 GitHub secret(见上面「设置方式」)

# B. 建一个永不过期的 API Token(推荐, 一劳永逸)
#    按 docs/cloudflare-token-setup-guide.html 的步骤走
```

⚠️ `npx wrangler login` 会**打开浏览器要求授权** —— 如果浏览器没自动批准
(超时), 需要手动点一下授权按钮。本机遇到过两次超时。

### ⚠️ OAuth token 会过期(2026-10-27 踩过)

wrangler 的 OAuth token 是**短期**的,过期后 CI 部署会报:

```
Authentication error [code: 10000]
Invalid access token [code: 9109]
```

看起来像"权限不够",实际是"token 过期了"。

**修复**(本机执行,然后更新 secret):
```bash
cd query/worker && npx wrangler login      # 会弹浏览器, 系统浏览器自动批准
# 然后把新 token 写回 secret
```

**长期方案**:在 Dashboard 建一个**真正的 API Token**(不过期):
Dashboard → My Profile → API Tokens → Create Token →
模板 **Edit Cloudflare Workers** → 配好权限 → 复制 token
→ `gh secret set CLOUDFLARE_API_TOKEN`。
⚠️ OAuth token **没有** `account:api_tokens` 权限, 自己建不了 —— 必须手点。

`deploy.yml` 已加**凭据预检**: 部署前先 curl `/accounts`,
token 失效时直接给出"token 过期,去跑 wrangler login"的提示,
而不是让 wrangler 抛一堆看不懂的 9109。

### 工作流

| Workflow | 触发 | 作用 |
|---|---|---|
| `ci.yml` | push / PR 到 `main` 或 `deploy/**` | vitest 34/34、e2e 9/9、typecheck+build、Worker typecheck、**eval 门禁 recall@10 ≥70%** |
| `deploy.yml` | push 到 `main` 或 `deploy/**`、手动 dispatch | 部署 Worker → 部署 Pages → 回读生产 API 校验 |

**手动触发部署**:
```bash
gh workflow run deploy.yml --ref deploy/c-b-hybrid
```

---

## 五、本地开发

```bash
# Worker(必须用 wrangler.local.toml)
cd query/worker
npx wrangler dev -c wrangler.local.toml --port 8788 --ip 127.0.0.1

# 前端(必须绑 127.0.0.1,否则只监听 ::1)
cd web
npx vite --host 127.0.0.1 --port 5173

# bge(本地跑一份)
cd ../..
HF_HUB_OFFLINE=1 BGE_HOST=0.0.0.0 BGE_PORT=8080 \
  BGE_CACHE=evals/bge_m3_cache.json BGE_ARTICLES=evals/articles_cache.json \
  python build/proxy/bge_server.py
```

**本地 LLM key**:`query/worker/.dev.vars`(已 gitignore)
```
LLM_API_KEY = "..."
```

**两份 wrangler.toml 的区别**:

| | `wrangler.toml` | `wrangler.local.toml` |
|---|---|---|
| 用途 | 远端部署 | 本地开发 |
| R2 binding | 注释掉 | 开启 |
| D1 `remote` | `true` | **`false`**(否则 miniflare 连远端) |
| Vectorize / AI | 开启 | 注释掉(本地不支持) |
| `BGE_SERVER_URL` | `https://ns.hbnongfengyuan.cn` | `http://192.168.3.65:8080` |

**本地灌正文**:
```bash
python build/export/push_d1_bodies.py --local
```
> ⚠️ `.wrangler/state` 下可能有**多个**本地 D1(database_id 改过 → miniflare 另建),
> 脚本取最近修改的那个。灌完确认 dev server 读的是同一个。

---

## 六、性能基线

50 用例评测集,同一语料:

| 指标 | 纯 FTS5 | 生产 hybrid |
|---|---|---|
| recall@10 | 76.0% | **76.0%** |
| recall@20 | 56.0% | **68.0%** |
| MRR | 0.544 | **0.647** |
| 业务 query MRR | 0.488 | **0.717** |
| negative 严格精度 | 100% | **100%** |

---

## 七、待办

| 项 | 状态 | 谁做 |
|---|---|---|
| R2 开通 | **不需要**(正文已进 D1) | — |
| DeepSeek 充值 | 可选,当前用 MiniMax | 用户 |
| 服务器磁盘 | ✅ 已清理(92% → 42%) | — |
| `DEEPSEEK_API_KEY` 余额 | 402,当前走 MiniMax | 用户 |
