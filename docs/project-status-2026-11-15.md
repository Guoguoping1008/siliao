# 饲料法规 RAG 项目 · 现状报告

- **报告日期**: 2026-11-15
- **测量方式**: 生产环境实测 + 本地门禁实跑 + D1 远程直查(非文档复述)
- **代码基线**: `deploy/c-b-hybrid` @ `b22d118`(= `origin/deploy/c-b-hybrid`,工作区干净)
- **生产地址**: 前端 https://siliao-web.pages.dev · API https://siliao-api.guoguoping.workers.dev
- **语料**: `minimax/` 1021 页 → 196 文档 / 529 章 / 3145 条文

---

## 一、结论速览

| 维度 | 状态 | 本次实测依据 |
|---|---|---|
| ① 法规检索 | 🟢 **生产可用** | `/api/search` 200 · 命中含「猪150~300mg/kg」原文表格 · 4.7s |
| ③ 知识问答 | 🟡 **可用但延迟劣化 + 偶发 524** | 6/6 次 200，但延迟 15/32/43/78/78/82s;另有 1 次 524 |
| ④ 知识图谱 | 🟢 **生产可用** | 481 实体 / 1951 关联 / 117 别名 · 中文搜索 15 条 |
| ② 用量合规速查 | 🔴 **闸门未开** | 37 规则 + 387 目录 **双表全 `pending`** → 一律 `not_covered` |
| ⑤ 法规监测 | 🟢 **已上线且健康** | Cron 每天 3 次,连续 8 次 `status=ok`,0 失败 |
| ③ 多轮会话 | 🟢 **生产可用** | `/api/qa/conversation` 200 · 55s |

**一句话**:检索、图谱、监测三块完全健康,指标与基线严丝合缝;问答能答对但延迟中位数已到
**60s**、偶发撞 Cloudflare 100s 上限(524);合规速查是**两道闸门**全关,不是一道 ——
**37 条规则 + 387 条物质目录都要放行**,人工量比文档记的「1-2 小时」多一截。

---

## 二、本次实测挖出的真实问题

### 2.1 【P0 · 业务阻断】合规速查是**两道闸门**,不是一道

文档 `docs/unfinished-features.md` 写的是「37 条规则人工校核(1-2 小时)」。本次直查 D1 发现
**第二道闸门被漏记**:

```
compliance_rules    : 37 条 | pending 37 | reviewed 0
substance_catalog   : 387 条 | pending 387          ← 这道闸门没人提
```

`build/export/apply_review_checklist.py` 开头的表格已经把话说白了:

> 判定引擎要同时拿到规则和物质目录,两道闸门**任一没开都恒返回 `not_covered`**。
> 实测证据(2026-11-03):只把 1 条规则置 `reviewed` → 判定**仍是** `not_covered`;
> 规则 + 目录**同时**置 reviewed → 13/13 全部命中判定。

**含义**:只校核 37 条规则,② 依然全线 `not_covered`。**目录那 387 条也得放行**
(脚本的 `--approve-catalog` 开关一次性全放行,⚠️ 需已核过名称/别名)。

生产实测(参数齐全,`value` 必须数字 + `unit` 必填):

```json
POST /api/compliance/usage
{"substance":"维生素C","species":"猪","value":200,"unit":"mg/kg"}
→ {"status":"not_covered","matchedSubstance":null,
   "coverageGap":{"reason":"规则库未覆盖该物质/动物组合, 需人工确认",
                  "relatedArticles":[...《饲料和饲料添加剂管理条例》第二十五条...]}}
```

value=150 / 200 / 500 三档**返回完全一致** —— 闸门在匹配之前就拦住了,符合设计。
返回体诚实地附了 `coverageGap.reason` + 回落条文原文,**没有静默失败**,这点做得对。

**校核工具已就绪**(实测存在):
- `build/export/make_review_checklist.py` → `review_checklist.csv` / `.md`
- `build/export/apply_review_checklist.py` → 回写 D1(**默认 dry-run,必须 `--apply`**)

**但清单还是空的**:`review_checklist.csv` 37 行的 `decision` 列 **100% 为空字符串**,
即**一条都没校核过**。

### 2.2 【P1 · 体验劣化 + 偶发失败】问答延迟中位数 60s,已撞到 100s 天花板

本次生产实测(非流式,`POST /api/qa`,同一问题「维生素C 限量」跑 6 次):

```
try1  200  14.95s
try2  200  31.99s
try3  200  78.52s
try4  200  78.32s
try5  200  82.37s
try6  200  42.74s
                    中位数 ≈ 60s   最大 82s
```

**6/6 成功,但波动 5.5 倍**(15s ~ 82s)。文档记的「37-63s」已经不够用了 —— 实测已经出现
78s / 82s。

**更要紧的是:本轮还实测到 1 次 `524`**:

```json
{"error":"llm_error","status":524,"body":"error code: 524\n"}
```

524 = Cloudflare Worker 硬上限(100s)。**这意味着推理段再长一点,问答会直接失败,
不是慢,是没答案。** 这是本次实测与文档最大的差异 —— 文档只说「慢」,没说「会挂」。

**答案质量本身是对的**(实测输出,引用的限量值与语料一致):

> L-抗坏血酸(维生素C)在配合饲料或全混合日粮中的推荐添加量(以维生素计)为:
> 猪150～300 mg/kg,家禽50～200 mg/kg,犊牛125～500 mg/kg;
> 罗非鱼、鲶鱼鱼苗300 mg/kg、鱼种200 mg/kg……

**流式路径(SSE)实测 23.3s 返回** —— 说明慢的是 reasoning 段的等待,不是检索或拼装。
流式能把「首字节时间」变成体感问题,**这是快档里性价比最高的一招**。

### 2.3 【P2】部署卫生

- `git status` 干净,`HEAD == origin/deploy/c-b-hybrid == b22d118`,无未跟踪文件
- 根目录两个 docx 均已跟踪(各 1 份),此前记录的「重复副本」问题已不存在
- `.gitignore` 无 `docx` 规则 —— 但目前不构成问题(两个都是要交付的正式件)

---

## 三、生产实测明细(2026-11-15 21:5x)

### 3.1 端点矩阵

| 端点 | 方法 | 结果 |
|---|---|---|
| `/api/documents` | GET | 🟢 200 · 61177 B · 2.4s |
| `/api/catalog` | GET | 🟢 200 · 62559 B · 1.5s |
| `/api/search?q=维生素C` | GET | 🟢 200 · 4.7s · 命中含原文表格 |
| `/api/entities?q=维生素` | GET | 🟢 200 · 中文命中(L-抗坏血酸(维生素C)等) |
| `/api/qa` | POST | 🟡 200 ×6(15~82s)· 1× 524 |
| `/api/qa` (SSE) | POST | 🟢 200 · 23.3s |
| `/api/compliance/usage` | POST | 🔴 200 `not_covered` · 闸门未开 |
| `/api/compliance/recipe` | POST | ⚪ 404(C2 未实现) |
| `/api/compliance/label` | POST | ⚪ 404(C3 未实现) |
| `/api/calendar` | GET | ⚪ 404(未实现) |
| `/api/monitoring/releases` | GET | 🟢 200 · 5 条已抓公告 |
| `/api/monitoring/impact` | GET | 🟢 200 · 按资产分组的影响面 |
| `/api/monitoring/runs` | GET | 🟢 200 · 连续 8 次 `ok` |
| `/api/monitoring/subscriptions` | GET | 🟢 200 · 空表(订阅了但无推送通道) |

前端页面 `/` `/qa` `/compliance` `/entities` 全部 200。

### 3.2 D1 远程直查(`wrangler d1 execute --remote`)

```
articles              3145   (正文 1.22 MB 存在 articles.body)
chapters               529
documents              196
entities               481   (387 物质 + 94 概念)
entity_articles       1951
entity_aliases         117
substance_catalog      387   review_status: pending 387  ← 第二道闸门
compliance_rules        37   review_status: pending 37    ← 第一道闸门
rule_sets                1
regulation_releases      5
qa_sessions              4
qa_messages              8
```

表清单(24 张):`articles` `articles_fts*` `catalog` `chapters` `compliance_rules`
`documents` `entities` `entity_aliases` `entity_articles` `index_meta`
`monitoring_runs` `qa_messages` `qa_sessions` `regulation_releases` `rule_sets`
`subscriptions` `substance_catalog` + FTS 影子表。

### 3.3 基础设施

| 项 | 状态 | 实测 |
|---|---|---|
| 前端 https://siliao-web.pages.dev | 🟢 | 200 · 1.8s |
| API 代理链路 | 🟢 | 响应头 `X-Proxied-By: siliao-pages-functions` · Pages → Worker 正常 |
| Worker 直连 https://siliao-api...workers.dev | ⚪ | **本机直连超时(21s 无响应)** —— 走 Pages 代理一切正常,判断为本机出网路径问题,**不是生产故障** |
| bge 语义服务 https://ns.hbnongfengyuan.cn | 🟢 | `/health` 200 · `BAAI/bge-m3` · dim 1024 · corpus 3145 · cache_loaded true · uptime 564149s(约 6.5 天) |
| 检索降级标记 | 🟢 | `degraded:false` · 语义召回在生效 |
| ⑤ Cron | 🟢 | 连续 8 次 `status=ok` · found=5 · bodiesFail=0 · new=0 · rev=0 |

---

## 四、门禁现状(本地实跑)

| 门禁 | 结果 | 对比文档记录 |
|---|---|---|
| worker 单测 | 🟢 **309/309**(20 个测试文件) | 254 → **+55** |
| worker typecheck | 🟢 干净(`tsc --noEmit` 无输出) | 持平 |
| web 单测 | 🟢 **34/34**(4 个测试文件) | 持平 |
| 检索 eval(带公网 bge) | 🟢 recall@10 **76.0%** / MRR **0.647** | **与基线完全吻合** |
| ├ 业务 query(20) | 🟢 recall@10 80.0% / MRR **0.717** | 持平 |
| ├ 语料派生(30) | 🟢 recall@10 73.3% / MRR 0.600 | 持平 |
| └ negative 严格精度 | 🟢 100%(0/4 真命中) | 持平 |
| 引用准确率 eval | 🟢 **100%**(阈值 95%)· 无引用占比 0% | 持平 |
| 架构测试 | 🟢 含在 309 内 · 19 条 | 持平 |

> ⚠️ 检索 eval **必须带 `BGE_SERVER_URL=https://ns.hbnongfengyuan.cn`**。
> 脚本默认指向 `127.0.0.1:8080`,本地没起 bge 时会**静默退化为纯 FTS5**(MRR 0.544),
> 看起来像指标掉了,实际是没测到 hybrid。本次已带公网地址跑,指标与基线严丝合缝。

**CI workflow 清单**:`ci.yml`(web-test / web-build / worker-typecheck / worker-test / eval)、
`deploy.yml`(push `main` 与 `deploy/**` 自动部署 Worker + Pages)、
`api-contract.yml`(**手动触发**,打生产后要记得跑)、
`seed-compliance.yml`(**手动触发 / push `seed/compliance`**,D1 写权限用)。

---

## 五、代码结构(ADR-004 DDD 落地态)

```
query/worker/src/
├── index.ts                        (只做「Request 交给路由层」)
├── interfaces/
│   ├── http/routes/                regulation / inquiry / compliance / retrieval / monitoring
│   ├── acl/                        llm · llm-stream · embedding · regulation · moa-source
│   └── composition-root.ts
├── application/
│   ├── inquiry/                    inquiry · conversation · qa-stream · prompt-builder
│   ├── compliance/                 compliance-check.usecase
│   └── monitoring/                 monitoring.usecase · monitoring.repository
├── domain/                         ① regulation ② compliance ③ inquiry ④(空壳) ⑤ monitoring
└── infrastructure/
    ├── persistence/d1/             6 个 repository impl + mappers
    └── persistence/retrieval/      hybrid-retriever.adapter
```

**五条强制依赖规则**由架构测试守护:上下文间只经 ACL、依赖方向单一、外部系统一律 ACL、
只读核心域、领域服务不依赖框架。

**ADR 台账**:

| ADR | 主题 | 状态 |
|---|---|---|
| 0001 | 检索后端选型 FTS5(trigram) | Accepted |
| 0002 | Unlimited-OCR 横评试点延期 | — |
| 0003 | 语料重建 + bigram RRF + 标题加权 | Accepted |
| 0004 | DDD 限界上下文与分层 | **Proposed(待业务方确认后转 Accepted)** |
| 0005 | 方案文档 vs 实现对照 | 提案 |
| 0006 | M4 监测数据源选型与实现路径 | Accepted(实现中) |

> ⚠️ ADR-004 仍是 **Proposed**。它是整个代码结构的宪法,建议顺手转 Accepted。

---

## 六、未完成功能(实测复核)

| # | 功能 | 状态 | 阻塞 | 工作量 |
|---|---|---|---|---|
| 1 | D1 灌库(C1 合规规则) | ✅ 已完成 | — | 37 规则 + 387 目录 |
| 2 | C1.5 会话表建表 | ✅ 已完成 | — | 生产实测 200 |
| 11 | ④ 知识图谱 | ✅ 已补齐 | — | 481 实体 / 1951 关联 |
| 8 | ⑤ 法规监测 | ✅ **已上线 11-11** | — | 领域层 + ACL + D1 + 7 端点 + Cron |
| **3** | **37 条规则校核** | ⏳ **等人** | **等人** | **1-2 小时** |
| **3b** | **🆕 387 条物质目录放行** | ⏳ **等人** | **等人** | **脚本一键,但需先核过名称/别名** |
| 5 | 组合/条件规则抽取 | 🚧 未开工 | 可做 | 1-2 天 |
| 4 | 禁用规则抽取 | 🚧 未开工 | 可做 | 2-3 天 |
| 9 | 合规日历 | 🚧 未开工 | 可做 | 2-3 天 |
| 10 | 版本追溯 + 领域标记 | 🚧 未开工 | 可做 | 2-3 天 |
| 6 | C2 配方批量审查 | 🚧 未开工 | 可做 | 5-8 天 |
| 7 | C3 标签审查(GB 10648) | 🚧 未开工 | 可做 | 5-8 天 |

**依赖链**:#4 禁用规则 → #6 C2 配方审查(缺禁用规则做不出「禁用成分标红」)。

**⑤ 监测的剩余缺口(诚实列)**:
`RegulationReleaseDetected` **无消费者**(① 入库路径 `ingestRelease` 未开)·
**无推送通道**(订阅表建了只落库不发通知)· 只到**公告级 diff**(条文级未做)·
关键词表需人工维护(实测已漏过 1 次)· 无爬虫健康外部告警。

**明确不做(数据源不存在,不是没排期)**:
企业资质审查 · 抽检「同类产品风险提示」 · 合规日历·换证年检提醒 ·
真正的历史版本回溯 · 「物质→可用替代品」映射 · 跨模块 Planner。

---

## 七、下一步(双档)

### 快档(半天到一天,低风险)

| 项 | 做法 | 收益 | 代价 / 债 |
|---|---|---|---|
| **A1 · 前端走 SSE** | 前端问答默认用流式端点 | 首字节从 60s → ~23s,体感提升最明显 | 需前端改造 + SSE 中断重试;**债**:流式与非流式两套渲染路径 |
| **A2 · reasoning 熔断** | `reasoning_content` 超阈值/超时 → 降级非 reasoning 模型 | 直接压住 524(实测已发生) | **债**:降级后质量未验证,需重跑引用准确率 eval |
| **A3 · P95 指标 + 超时告警** | 采集 elapsed_ms 分位数,超阈值告警 | 让劣化**可观测**,不再静默 | 无 |
| **A4 · ADR-004 转 Accepted** | 改 ADR 状态 | 架构宪法落地 | 无 |
| **A5 · 文档同步** | README / project-status 停在 11-09 | 消除认知偏差 | 无 |

### 对档(1-2 周)

| 项 | 做法 | 收益 | 代价 / 债 |
|---|---|---|---|
| **B1 · 双闸门开闸** | 37 条规则逐条校核 + 387 目录核名放行 | ② 正式上线,三态可实测 | 人工量比文档记的多一截(目录那 387 条) |
| **B2 · 换非 reasoning 模型** | MiniMax 非 thinking 版,延迟回 10-15s | 根治延迟 | **必须重跑引用准确率 eval 确认质量不降** |
| **B3 · #10 版本追溯 + 领域标记** | 加 `domain` 字段 + `supersedes_doc_id` | 支持「只查兽药法规」;32 份兽药法规可过滤 | schema 变更 → 需单独 migration(**绝不能重跑 schema.sql**) |
| **B4 · #5 + #4 规则抽取** | 组合/条件 + 禁用规则 | 覆盖 39 个含「禁用」条款的文件 | 抽取必须走 `review_status` 闸门(假阳性:「不得在饲料生产过程中进行维修、焊接」不是禁用物质) |

### ⚠️ 我建议的顺序

> **先 A1 + A2 + A3(半天,纯工程,无人工依赖),同时把 B1 的校核清单发给业务方**。
> A1 是唯一能把「60s 体感」变成「23s 体感」的改动,代价最小;A2 直接消除 524 这个
> 真失败。B1 是 ② 上线的唯一门槛,但卡在人,越早发起越好。

---

## 八、已踩过的坑(别重蹈)

1. **`return promise` 不会进 try/catch** —— 必须 `return await promise`。
   抽路由层时丢了 await,生产报 1101,根因是 D1 报错被掩盖成 Worker 崩溃。
2. **`.gitignore` 行内注释不生效** —— `Images/   # 说明` 整行都是匹配模式,
   曾提交 510 张扫描图(3.2GB)。注释必须单独占一行。
3. **不能重跑 `schema.sql`** —— 生产库 3145 条条文,wrangler 4.127+ 对「schema 变了」
   的库报 `D1_RESET_DO`,**会清空远端表**。用 `migrate_c1.sql` / `migrate_c15.sql` 单独跑。
4. **不要用 wrangler OAuth token 跑 CI** —— 1 小时过期且 refresh_token 每次轮换。
5. **SQLite 的 `LIKE` 对中文无效** —— 实测 `?q=维生素` → 0 条。改用 `instr()` → 15 条。
   **换回 LIKE 不会报错,只是永远搜不到东西。**
6. **eval 不指定公网 BGE 地址会静默退化** —— 看着像指标掉了,实际没测到 hybrid。
7. **reasoning 模型 `max_tokens` 与 `content` 共用配额** —— 给太小答案整段变空,
   给太大延迟劣化到 40-60s,**再大就撞 100s 变 524**。
8. **合规速查是两道闸门** —— 只校核规则不放行目录,判定恒为 `not_covered`。
9. **`/api/qa` 的 body 字段是 `q`**(别名 `question` / `ask`),且 `stream` 可选。
   **写错字段名会静默返回 400 `missing_query`**,不会报错提示。
10. **`/api/compliance/usage` 必须 `value` 数字 + `unit` 必填** —— 缺一个都是 400。

---

## 九、资源快照

| 项 | 值 |
|---|---|
| 语料 `minimax/` | 1021 页 → 4.8 MB |
| `data/`(摄入产物 + 旧产物) | 2.8 GB(大部分是已废的 raw/markdown) |
| `evals/bge_m3_cache.json` | 69 MB |
| `evals/tfidf_cache.json` | 19 MB |
| `evals/articles_cache.json` | 3.4 MB |
| D1 `articles.body` 正文 | 1.22 MB(不依赖 R2) |
| bge 服务 | `https://ns.hbnongfengyuan.cn` · BAAI/bge-m3 · dim 1024 · corpus 3145 |
| LLM | MiniMax-M3.1-Flash(reasoning 模型,OpenAI 兼容端点) |
| tag | `v1.0.0-production` @ `b4645d7`(纯 RAG 基线,M1~M4 均在其后) |

---

## 关联文档

| 文档 | 关系 |
|---|---|
| `docs/project-status-2026-11-09.md` | 上一版现状(本文档的增量来源) |
| `docs/unfinished-features.md` | 未完成功能清单(11-02 版,**部分已过时**) |
| `docs/c1-status.md` | C1 交付状态 |
| `docs/adr/0004-ddd-bounded-contexts.md` | DDD 限界上下文(**仍 Proposed**) |
| `docs/adr/0006-m4-monitoring-source-selection.md` | M4 监测数据源选型 |
| `docs/deployment-info.md` | 生产资源与凭据权限 |
| `build/export/apply_review_checklist.py` | **两道闸门**的权威说明 + 回写脚本 |
| `query/worker/src/interfaces/acl/llm.acl.ts:98-127` | reasoning 模型 max_tokens 实测记录 |
