# 饲料法规 RAG 项目 · 状态报告

> ⚠️ **本文档是 2026-11-02 的快照，已过时。**
> **最新现状见 [`docs/project-status-2026-11-09.md`](project-status-2026-11-09.md)（含 HTML 版）**。
>
> 11-02 → 11-09 的关键变化：
> - ① **D1 灌库阻塞已解除**（`CLOUDFLARE_D1_TOKEN` 不再需要，走本地 OAuth）
> - ② **37 条规则仍全为 `pending`** → 合规速查一律返回 `not_covered`（闸门按设计工作，但业务上等于未上线）
> - ④ **知识图谱已补齐**：481 实体 / 1951 关联 / 117 别名（原 94 实体、0 关联）
> - ③ **问答延迟劣化**：换 reasoning 模型 `MiniMax-M3.1-Flash` 后 11s → 37-63s
> - worker 单测 227 → **254**；检索 eval 与基线严丝合缝（recall@10 76.0% / MRR 0.647）

- **报告日期**: 2026-11-02
- **测量时点**: 生产环境实测(2026-11-02 08:56 ~ 09:02 UTC)
- **基线 tag**: `v1.0.0-production` (b4645d7)
- **当前分支**: `deploy/c-b-hybrid` @ `e73a4c4`
- **生产地址**: 前端 https://siliao-web.pages.dev · API https://siliao-api.guoguoping.workers.dev

---

## 一、结论速览

| 维度 | 状态 | 说明 |
|---|---|---|
| 法规检索(①) | ✅ **生产可用** | 语义+全文双路,实测 `GET /api/search` 正常返回 |
| 知识问答(③) | ✅ **生产可用** | `POST /api/qa` 实测 200,引用 5 条,耗时 11.1s |
| 多轮会话(③) | ✅ **生产可用** | D1 表已建,实测 200 + 引用正常(2026-11-02) |
| 用量合规速查(②) | 🟡 **数据就绪,等校核** | 表已建 + 数据已灌(37 规则/387 目录);规则仍 `pending`,人工校核后才参与判定 |
| 知识图谱(④) | ✅ **实体+关联+别名可用** | **481 实体**(387 物质 + 94 概念)/ **1951 条**实体↔条文关联 / **117 条**别名;`/entities` 列表页 + `/entity/:name` 完整渲染(2026-11-03) |
| 法规监测(⑤) | ⚪ **未开工** | M4,4-6 周 |

**一句话**: 检索与问答两条主链路在生产上跑得很好;合规速查这条最有业务价值的链路,
**代码 100% 完成、数据 100% 就绪,唯独卡在「一个带 D1 写权限的 Cloudflare token」**。

本次实测还挖出一个**未被任何文档记录的 P0 回归**(路由层 try/catch 失效 → 生产报 Cloudflare 1101),
已定位根因、已修复、已加回归测试。

---

## 二、本次新发现:P0 回归 —— 路由层错误处理失效

### 2.1 现象(生产实测)

```
POST   /api/compliance/usage    → 500  Cloudflare 1101 (Worker threw exception)
POST   /api/qa/conversation     → 500  Cloudflare 1101
DELETE /api/qa/conversation     → 500  Cloudflare 1101
```

返回的不是我们自己的 `{"error","message"}` JSON,而是 Cloudflare 的未捕获异常页:

```json
{"error_code":1101,"error_name":"worker_threw_exception",
 "detail":"A Worker script ... threw an unhandled exception while processing this request."}
```

### 2.2 根因

`query/worker/src/interfaces/http/router.ts` 的 try/catch **捕获不到 async handler 抛出的错误**:

```ts
try {
  return handleComplianceUsage(app, req);   // ← 返回 Promise,没有 await
} catch (e) {
  return errorJson("internal", ...);        // ← 永远走不到
}
```

`return promise` 时 try 块**已经正常返回**,catch 不会执行;错误变成 **unhandled rejection** → Workers 报 1101。

**这是 M3 抽路由层时引入的**:重构前(`index.ts` 单文件)是
`return json(await app.complianceCheck.check(...))` —— **await 在 try 块内**,能捕获。
M3 把 `await` 留在了 handler 内部,外层 try/catch 就失去了作用。

### 2.3 影响面

凡 handler 内部会抛错的端点,全部丢失错误契约:

| 端点 | 修复前 | 修复后 |
|---|---|---|
| `GET /api/documents` | 1101 | 500 JSON |
| `GET /api/catalog` | 1101 | 500 JSON |
| `GET /api/article/:id` | 1101 | 500 JSON |
| `GET /api/entity/:name` | 1101 | 500 JSON |
| `POST /api/compliance/usage` | 1101 | 500 JSON |
| `POST /api/qa/conversation` | 1101 | 500 JSON |
| `DELETE /api/qa/conversation` | 1101 | 500 JSON |

**当前生产上最常见的触发原因就是 D1 表不存在**(C1/C1.5 未灌库)——
所以「1101」实际上一直是「表没建」的表现形式,被这个 bug 掩盖成了 Worker 崩溃。
**这是它没有早点被发现的根本原因**:表面看是环境问题,实际是代码回归。

### 2.4 修法与验证

- **修法**:每个 handler 调用加 `await`(`router.ts` 10 处),让错误回到 try 块内走统一 500 JSON 契约。
- **验证**:新增 `query/worker/src/interfaces/http/router.error-handling.test.ts`(7 用例)。
  修前 **6/7 失败**(错误逃逸成 unhandled rejection),修后 **7/7 通过**。
- **回归全绿**:worker 单测 220 → **227**;typecheck 干净。
- 提交:`e73a4c4 fix(worker): 路由层 try/catch 失效 → 生产 1101 回归`

> ⚠️ `GET /api/search` **故意不**是 500:检索层多路降级
> (FTS5 → phrase → bigram → bge),每路各自 catch,D1 全挂时返回**空命中**。
> 这条契约差异已在测试里单独标注。

---

## 三、唯一阻塞项:D1 灌库需要写权限

### 3.1 现象

CI 的 `seed-compliance` workflow 跑起来了,但**两条灌库路径都失败**:

```
D1 REST API 失败,回退到 wrangler d1 execute
建表失败 —— 需要有 D1 编辑权限的 token
```

2026-10-28 的 5 次 workflow 运行**全部 failure**,最后一次尝试后没有再触发。

### 3.2 已排除的可能

| 可能 | 排除依据 |
|---|---|
| API 路径写错 | 本地实测 `/d1/database/{id}/query` 用无效 token 返回 **401 Authentication error**(不是 404 / No route) |
| SQL 语法错 | 建表拆成 10 条独立 `CREATE TABLE IF NOT EXISTS`;且探测步骤的**读查询成功** |
| Python 依赖问题 | 抽取步骤成功,脚本能跑 |
| workflow 没注册 | 已修(GitHub 只从默认分支读 workflow);push 触发器已验证生效 |

### 3.3 唯一原因

**`CLOUDFLARE_API_TOKEN` secret 没有 D1 编辑权限。**

这与 `docs/deployment-info.md` 的记录完全一致:

> `/d1/database` → ⚠️ 401 —— 部署不需要,D1 数据是一次性灌的
> **没给 D1 权限是有意的** —— 最小权限原则

那个 token 是**故意**做成最小权限的(部署只需写 Worker/Pages)。而灌 D1 是另一类操作。

### 3.4 需要你做的(约 3 分钟)

1. Cloudflare Dashboard → 你的账户 → **API Tokens** → Create Token
2. 权限选 **Account → D1 → Edit**(Account Resources 选你的账户)
3. ⚠️ **不要设过期时间**(TTL 留空)—— OAuth token 1 小时就过期、refresh_token 每次刷新都轮换
4. `gh secret set CLOUDFLARE_D1_TOKEN`
5. 告诉我一声 → 我改 workflow 用新 secret 名(`seed-compliance.yml` 现在有 **3 处** `CLOUDFLARE_API_TOKEN`、**0 处** `CLOUDFLARE_D1_TOKEN`),再触发灌库

> **本地 wrangler token 也已过期**(9109 Invalid access token,refresh 报 `invalid_grant`)。
> 所以本地走不通,只能靠 CI + 一个有 D1 权限的永久 token。

### 3.5 拿到 token 后的执行序列

```bash
# ① 建 C1.5 的会话表(必须单独跑)
npx wrangler d1 execute siliao-db --remote --file ./query/worker/migrate_c15.sql

# ② 建 C1 的合规表 + 灌数据(走 CI 的 seed-compliance workflow)
gh workflow run seed-compliance.yml
```

> ⚠️ **`migrate_c15.sql` 与 `migrate_c1.sql` 都必须单独跑,不能重跑 `schema.sql`** ——
> 生产库有 3145 条条文,wrangler 4.127+ 对「schema 变了」的库报 `D1_RESET_DO`,**会清空远端表**。

---

## 四、各模块完成度

### ① 法规知识库 —— 90%,生产可用

| 项 | 实测值 |
|---|---|
| 语料 | 1021 页扫描件 → 196 文档 / 529 章 / 3145 条文 |
| 检索 | D1 FTS5(phrase 优先 + bigram RRF + 标题加权)⊕ bge-m3 语义 |
| recall@10 | **76.0%**(50 用例评测集) |
| MRR | **0.647**(业务 query 0.717) |
| recall@20 | 68.0% |
| 负例严格精度 | 100% |

**生产实测**:`GET /api/documents` / `/api/catalog` / `/api/search` / `/api/article/:id` 全部 200 正常。

**待补**:版本追溯(需 `status` / `supersedes_doc_id` 字段 + 历史数据,第一期只做字段不做功能)、
领域标记(`documents.domain` 字段,支持「只查兽药法规」)。

### ② 合规规则 —— 代码 100%,数据 100%,**灌库 0%**

| 项 | 状态 |
|---|---|
| 限量规则抽取器 | ✅ **37 条 / 11 种物质**,溯源 100% |
| 物质目录抽取 | ✅ **387 条**(修列错位后,原 74) |
| 中英对照 | ✅ 98 对(5 条 OCR 拉丁名已转中文) |
| 领域层 | ✅ 聚合根 + 判定器 + 三级命名匹配 |
| D1 schema | ✅ `migrate_c1.sql`(3 表) |
| API | ✅ `POST /api/compliance/usage`(代码完成,生产待灌库) |
| 前端 | ✅ `/compliance` 页已上线(HTTP 200) |
| 真实数据集成测试 | ✅ **20 用例跑真实抽取产物** |
| 人工校核清单 | ⏳ 已生成(37 条,**8 条自动标记**待重点看) |
| **灌库进 D1** | ❌ **被 token 权限挡住** |

**规则现状**(`build/export/compliance_rules.json`,实测):

```
规则总数     37      rule_type: limit × 37
审核状态     pending × 37   ← 未审核规则不参与判定(安全闸门)
覆盖物种     猪10 牛4 鲤鱼3 羊3 鱼类3 家禽2 + 9 个单一物种
物质(11)    L-抗坏血酸(维生素C) · 烟酰胺 · 烟酸 · 维生素D2 · 维生素D3
             天然维生素E · D-生物素 · 肌醇 · L-肉碱 · L-肉碱酒石酸盐
             二甲基嘧啶醇亚硫酸氢钠甲萘醌
```

**两条不可协商的不变量**(已用单测锁死):

1. **规则未覆盖必须返回 `not_covered`,绝不能返回 `compliant`**
   测试用**故意构造的未覆盖物质**锁死这个分支 —— 它极容易在后续重构里被"优化"掉。
2. **每条规则必绑 `source_article_id`**,无出处不允许入库
   这条同时落在 D1 表结构上(`source_article_id TEXT NOT NULL`),**不依赖应用层自觉**。

**命名匹配:三级,不做模糊匹配**

```
1 精确  →  2 括号别名(维生素C → L-抗坏血酸(维生素C))  →  3 别名表(英文名)
```

向量相似度匹配出的「维生素C ≈ 抗坏血酸钙」在合规判定里是**危险**的 —— 两者限量完全不同。
**宁可说「未覆盖,需人工确认」,不可猜。**

### ③ 知识问答 —— 85%,生产可用

| 能力 | 状态 |
|---|---|
| 引用来源自动标注到具体条款 | ✅ `CitationValidator` + 前端引用卡片 |
| 幻觉引用标红 | ✅ `valid:false` → 前端标红 |
| 流式输出 | ✅ SSE `meta`/`chunk`/`done`/`error` 四事件 |
| 拒答机制 | ✅ system prompt 强制「证据不足则回复未找到相关规定」 |
| 多轮追问 | ❌ 代码完成 + 生产已部署,**但表未建**(同一个 D1 blocker) |

**生产实测**:`POST /api/qa` 返回 200,答案含 5 条引用、8 条检索证据,耗时 11.1s。
引用准确率 eval **实测 100%**(15 问题 / 39 引用,CI 门禁已生效)。

### ④ 知识图谱 —— 实体已补齐(2026-11-03)

**两轮实测数据**:

| 表 | 补之前 | 补之后 |
|---|---|---|
| `entities` | 94(全是 GraphRAG 通用概念) | **481**(387 物质 + 94 概念) |
| `entity_articles` | 1533 | **1951** |
| `entity_aliases` | —(表都没有) | **117** |

孤儿 / 悬空 / 孤儿别名 **全 0**;原始 `articles` **3145 条未动**。

**关键发现**:94 个旧实体里**一条物质都没有** —— 而 `substance_catalog` 的
387 条物质与 `entities` 重名 **0 条**。《饲料添加剂品种目录》在图谱里完全缺席,
图谱与业务主语(C1 合规速查的物质)**脱节**。

**关联靠权威出处,不靠猜**:387 条物质**全部**有 `source_article_id`
(不变量 2 的溯源字段),全部指向《品种目录》的 4 个条文 —— **零猜测**。
再叠加三路变体(括号别名 / `name_en` / `substance_alias`)补充正文提及。

**别名一对多 → 一律不收录**(`维生素B1` → 两种盐、`螯合物` → 9 个络合物)。
与 ② 合规规则的 `alignSubstanceName` 同一条纪律:**候选不唯一就不采用**。
124 个候选 → 收录 117,剔掉 7。

**顺带修掉 3 个真 bug**:

1. 顶栏「实体」跳 `/entity/农业农村部` —— 该实体生产命中 **0 条**,点进去直接 404。
2. **SQLite 的 `LIKE` 对中文无效** —— 实测 `?q=维生素` → 0 条。改用 `instr()` → **15 条**。
   **换回 LIKE 不会报错,只是永远搜不到东西。**
3. `description` 为 null 时返回 undefined → 归一化成空串。

**新增入口**:`GET /api/entities`(分页 + 类型过滤 + 名称搜索)+ 前端 `/entities` 列表页。

**浏览器实测**:`/entities` 渲染 50 张真实实体卡 · 中文搜索 15 条 ·
点进实体详情 2 条关联条文 + 关系图谱 · **0 崩溃**。

**仍未做(刻意)**:实体↔实体关系。ADR-004 决策「保持空壳直到有真实用例」——
当前所有已上线功能都不消费实体间关系,故不排期。

### ⑤ 法规监测 —— 未开工(M4,4-6 周)

ADR-004 的领域事件契约已定义好(`domain/shared/domain-event.ts`),流水线不需要重新设计架构,只需填实现。

---

## 五、架构状态(ADR-004 DDD 重构)

### 5.1 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| **M1** | 抽离领域层(不改变行为) | ✅ 2026-10-28 · index.ts 1059 → 265 行 |
| **M2** | 建合规规则上下文 | ✅ 代码完成 · 灌库待解 |
| **M3** | 领域层与基础设施层彻底分离 | ✅ 2026-10-31 · index.ts → **40 行** |
| **M4** | ⑤ 监测上下文 | ⏳ 未开工 |

### 5.2 目标态 vs 现状

```
index.ts (40 行)                    —— 只做「把 Request 交给路由层」
  interfaces/http/
    router.ts                       —— 路由分发(按上下文分组,静态路径在前)
    http-utils.ts                   —— json / errorJson / CORS / decodeParam
    routes/regulation.routes.ts     —— ① 法规库
    routes/inquiry.routes.ts        —— ③ 问答(含 SSE 响应组装)
    routes/compliance.routes.ts     —— ② 合规规则
    routes/retrieval.routes.ts      —— 检索 + ④ 图谱
  interfaces/acl/
    llm-stream.acl.ts               —— 流式 LLM 调用 + SSE 帧解析
  application/inquiry/
    qa-stream.service.ts            —— 流式问答的业务编排
```

**五条强制依赖规则**(违反即 code review 打回),由 **19 条架构测试**自动守护:

| 规则 | 说明 |
|---|---|
| R1 | 上下文间只经 ACL 通信,禁止跨上下文直接 JOIN 对方表 |
| R2 | 依赖方向单一:③ → ①②④;⑤ --事件--> ① |
| R3 | 外部系统一律 ACL(LLM / bge / 政府网站) |
| R4 | 只读核心域,写入只经各自仓储 |
| R5 | 领域服务不依赖框架(不 import Workers/D1 类型) |

### 5.3 ⚠️ 架构测试没有覆盖到的一层

19 条架构测试守住了**目录与 import 方向**,但**没有一条守住「路由层必须 await handler」**。
这就是 P0 回归能溜过去的原因 —— 它不是分层问题,是**同一层内的控制流问题**。

已补 `router.error-handling.test.ts` 锁死这个契约。

---

## 六、质量门禁现状

| 门禁 | 状态 |
|---|---|
| worker 单测 | ✅ **227/227**(原 220 + 新增 7 条错误处理回归) |
| worker typecheck | ✅ 干净 |
| 架构测试 | ✅ 19 条(已实测能捕获新上下文的违规) |
| 响应契约测试 | ✅ 13 条(`response-contract.test.ts`) |
| 真实数据集成 | ✅ 20/20(跑真实抽取产物 + 生产链路) |
| web 单测 | ✅ 34/34 |
| 检索 eval | ✅ recall@10 76.0% / MRR 0.647 —— 与基线一致 |
| 引用准确率 eval | ✅ 实测 100%(阈值 95%) |
| 生产响应契约比对 | ✅ `api-contract.yml`(手动触发,8 端点逐字段) |
| `deploy/c-b-hybrid` CI | ✅ 全绿(2026-11-01) |
| `main` 分支 CI | ❌ **失败**(2026-10-28 起,`npm ci` + eval 失败) |
| Dependabot PR CI | ❌ 2 个失败(`npm ci` 失败,依赖升级分支) |

> ⚠️ `main` 分支的 CI 失败与 Dependabot 的 `npm ci` 失败**都指向同一现象**:
> runner 上 `npm ci` 装不上依赖。这不影响当前生产分支(走 `deploy/c-b-hybrid`),
> 但意味着**依赖升级 PR 无法自动验证**,需要人工本地跑。

---

## 七、已修 · 已部署 · 已验证

| 提交 | 内容 | 状态 |
|---|---|---|
| `e73a4c4` | 路由层 try/catch 失效 → 生产 1101 回归 | ✅ **已 push + 已部署生产 + 已验证** |
| `6c2b358` | 项目状态报告 + P0 复盘进 c1-status | ✅ 已 push |

**部署后生产全端点复测(2026-11-02 09:1x UTC,12 个端点)**:

| 端点 | 结果 |
|---|---|
| `GET /api/documents` | ✅ 200 |
| `GET /api/catalog` | ✅ 200 |
| `GET /api/search` | ✅ 200 |
| `GET /api/article/:id`(不存在) | ✅ 200 `article_not_found` |
| `GET /api/entity/:name` | ✅ 200 `entity_not_found` |
| `POST /api/qa` | ✅ 200 |
| `POST /api/qa`(缺 q) | ✅ 400 `missing_query` |
| `POST /api/compliance/usage`(参数错) | ✅ 400 `invalid_request` |
| `POST /api/compliance/usage`(正常) | ✅ **500 JSON** `no such table: substance_catalog` |
| `POST /api/qa/conversation` | ✅ **500 JSON** `no such table: qa_sessions` |
| `DELETE /api/qa/conversation` | ✅ **500 JSON** `no such table: qa_messages` |
| `GET /api/nonexistent` | ✅ 404 `not_found` |

**零 1101**。最后三条的 500 是**如实反映 D1 表未建**(§三 的唯一阻塞),
不再是 Worker 崩溃 —— 现在「缺哪张表」一眼可见,灌库前置检查也不必再靠猜。

> 建议后续用 `api-contract.yml` 手动触发一次,把「错误响应形状」也纳入基线。
> 当前基线只覆盖 200 与 400,**没有覆盖 500** —— 这正是这个 bug 能长期潜伏的原因之一。

---

## 八、下一步(按优先级)

### P0 · 立刻需要你做(约 3 分钟)

```
新建带 Account → D1 → Edit 权限、TTL 留空的 Cloudflare API Token
→ gh secret set CLOUDFLARE_D1_TOKEN
```

**解锁**:C1 合规规则灌库 + C1.5 会话表建表 → 合规速查与多轮会话两个模块同时上线。

### P1 · 我可以做(拿到 token 后立即执行)

```
① 改 seed-compliance.yml(3 处)用 CLOUDFLARE_D1_TOKEN
② 跑 migrate_c15.sql 建 qa_sessions / qa_messages
③ 触发 seed-compliance workflow 灌 C1 数据
④ 回读校验 + 生产三态实测(compliant / exceeded / not_covered)
```

### P2 · 排期项(需你拍板)

| 项 | 周期 | 决策点 |
|---|---|---|
| C2 · 配方批量审查 | 5-8 天 | 依赖 C1 灌库完成 |
| C3 · 标签审查(GB 10648) | 5-8 天 | 独立,可与 C2 并行 |
| M4 · ⑤ 变更监控 + 预警 | 4-6 周 | 爬虫脆弱性是主要风险 |
| 合规日历(标准生效日) | 2-3 天 | 只做标准生效日,不含企业证件 |
| `main` 分支 CI 修复 | — | npm ci 失败根因未查 |

### 明确**不做**的(数据源不存在)

| 项 | 原因 |
|---|---|
| 企业资质审查 | 语料里只有许可证**条款**,没有企业**实际证件数据** |
| 抽检结果「同类产品风险提示」 | 抽检数据无 API,粒度是产品批次,没有企业配方数据 |
| 合规日历·换证年检提醒 | 需企业侧证件到期日 |
| 真正的历史版本回溯 | 农业农村部不提供结构化历史,只能积累上线后的变更 |
| 跨模块 Planner | 低频场景,v1 不建;真实复杂提问日志出来再决定 |

---

## 九、已踩过的坑(别重蹈)

1. **`return promise` 不会进 try/catch** —— JS 里 `return` 一个 Promise 时 try 块已正常返回。
   必须 `return await promise`。这是本次 P0 的根因。
2. **`.gitignore` 行内注释不生效** —— `Images/   # 说明` 整行都是匹配模式,
   曾导致提交 510 张扫描图(3.2GB)。注释必须单独占一行。
3. **不能重跑 `schema.sql`** —— 生产库 3145 条条文,wrangler 4.127+ 对「schema 变了」的库
   报 `D1_RESET_DO`,**会清空远端表**。`migrate_c1.sql` / `migrate_c15.sql` 必须单独跑。
4. **不要用 wrangler OAuth token 跑 CI** —— 1 小时过期,且 Cloudflare 每次刷新都轮换
   refresh_token,旧的立刻失效。正解:Dashboard 建 TTL 留空的 API Token。
5. **依赖升级 PR 的 CI 现在是坏的** —— `npm ci` 失败,升级无法自动验证,需人工本地跑。

---

## 关联文档

| 文档 | 关系 |
|---|---|
| `docs/functional-design.md` | 功能设计(C1 验收标准来源) |
| `docs/c1-status.md` | C1 交付状态(**本次发现的两处需同步更新**) |
| `docs/adr/0004-ddd-bounded-contexts.md` | DDD 限界上下文(M1/M2/M3 记录) |
| `docs/adr/0005-scheme-doc-update-proposal.md` | 方案文档 vs 实现对照 |
| `docs/deployment-info.md` | 生产资源与凭据权限说明 |
| `evals/citation_accuracy_report.md` | 引用准确率 100% 报告 |
| `query/worker/src/interfaces/http/router.error-handling.test.ts` | 本次新增的错误处理回归测试 |
