# ADR-004 · 系统架构按 DDD 重构 —— 限界上下文与分层

- **状态**: Proposed(待业务方确认后转 Accepted)
- **日期**: 2026-10-28
- **决策者**: qingmang(青芒 CTO)
- **关联**: ADR-001(检索后端选型)、ADR-002(章节名注入)、ADR-003(语料重建 + bigram RRF)、ADR-005(Word 方案文档 vs 实现对照)
- **基线**: `v1.0.0-production` (b4645d7)
- **触发**: 用户指令「输出新的系统架构，调整为按照 DDD 方式」

---

## 背景

当前系统是一个 **1059 行的单文件 Worker**(`query/worker/src/index.ts`),内含 26 个函数、5 类数据访问、9 条路由,加上一个 440 行的前端 API 客户端。

现状能跑、指标达标( recall@10 76.0% / MRR 0.647 ),但存在三个结构性负债:

| 负债 | 具体表现 | 触发场景 |
|---|---|---|
| **L1 · 关注点混杂** | 路由分发、检索算法、LLM 调用、引用校验、D1 SQL 全部平铺在一个文件,无模块边界 | 改检索逻辑要读懂 RAG 逻辑;改 prompt 怕碰坏检索 |
| **L2 · 语义无边界** | `documents/chapters/articles/entities/catalog/index_meta` 6 组表 + `articles_fts` 共处一个 schema,没有"这是哪个领域的模型"的概念 | 无法界定"规则库该放哪张表""案例库归谁" |
| **L3 · 能力扩展无落点** | 方案文档里的规则引擎 / 变更监控 / 审核预审 / 案例库,**加任何一项都只能继续往 `index.ts` 塞函数** | 对档方案(4-6 周)开工即失控 |

**关键判断**: L1/L2 是代码组织问题,**值得现在修**;L3 是架构容量问题,**必须现在修**,否则对档方案开工就是第二遍同样的混乱。

**但**: DDD 在这个项目有一个真实的风险 —— 当前技术栈是 Cloudflare 全 Serverless(Workers + D1 + Pages),**没有 JVM、没有应用服务器、没有 DI 容器**。经典 DDD 的"聚合根 / 仓储 / 领域服务 / 防腐层"如果照搬成目录结构,会变成**换皮**:目录分了,依赖还是乱的。

因此本 ADR 的核心主张是:**按 DDD 的"领域划分"来重构,而不是按 DDD 的"技术分层"来重构**。

---

## 决策

### 1. 限界上下文划分(核心)

按**业务语义**而非技术分层切分为 5 个上下文。切分依据是「法规的什么性质决定它归谁管」。

```
┌─────────────────────────────────────────────────────────────────┐
│                    Feed-Reg Agent 顶层                          │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐      │
│  │ ① 法规知识库  │   │ ② 合规规则   │   │ ③ 问答       │      │
│  │  Regulation  │   │  Compliance  │   │  Inquiry     │      │
│  │  (核心域)     │   │  (核心域)    │   │  (支撑域)    │      │
│  │              │   │              │   │              │      │
│  │ 只读 · 事实源 │   │ 只读 · 判定源 │   │ 无状态 · 编排 │      │
│  └──────────────┘   └──────────────┘   └──────────────┘      │
│         │                   │                   │                │
│  ┌──────────────┐   ┌──────────────────────────────────┐       │
│  │ ④ 知识图谱    │   │ ⑤ 法规监测  Monitoring            │       │
│  │  Graph       │   │  (支撑域)                        │       │
│  │  (支撑域)     │   │                                  │       │
│  │ 当前为空表    │   │ 爬虫 → 差异 → 影响分析            │       │
│  └──────────────┘   └──────────────────────────────────┘       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2. 五个上下文的详细定义

#### ① 法规知识库 Regulation —— 核心域,只读

**通用语言**: 法规文档(Document)、章节(Chapter)、条文(Article)、目录(Catalog)、版本(Version)

**聚合根**:`RegulationDocument`
- 聚合内部:`Document` → `Chapter` → `Article`(严格层级,一致性边界清晰)
- 不变量:一个 Article 必属一个 Chapter,一个 Chapter 必属一个 Document
- 边界外暴露:`RegulationDocumentId`、`ArticleId`

**领域服务**:`RegulationQueryService` —— 只读查询,无状态

**当前实现映射**:
| DDD 概念 | 现有代码 |
|---|---|
| 聚合根 `RegulationDocument` | `documents` + `chapters` + `articles` 三表 JOIN |
| 仓储 `RegulationRepository` | `listDocuments` / `listChapters` / `getChapter` / `getArticle`(`index.ts:695-790`) |
| 领域服务 `CatalogService` | `getCatalog`(`index.ts:717`)+ `catalog` 表 |
| 防腐层 ACL | `r2Key()`(`index.ts:221`)+ `plainExcerpt()`(`index.ts:169`) |

**关键约束**: 此上下文**只读**。任何写入都发生在 ⑤ 监测上下文(新版本入库)。这条约束保证"法规是事实,不是可编辑对象"。

#### ② 合规规则 Compliance —— 核心域,只读(待建)

**通用语言**: 物质(Substance)、动物种类(TargetSpecies)、限量(Limit)、禁用(Prohibition)、使用条件(Condition)、规则(Rule)、规则版本(RuleVersion)

**聚合根**:`ComplianceRuleSet`(规则集)
- 聚合内部:`LimitRule` / `ProhibitionRule` / `ConditionRule`
- 不变量:
  - 一个 LimitRule 必绑定 `sourceArticleId`(**没有依据条款的规则不允许存在** —— 对应方案文档「合规优先」原则)
  - 同 `substance + species + effectiveDate` 不得有两条冲突 LimitRule
  - 每条规则必属一个 `RuleVersion`
- 边界外暴露:`ComplianceVerdict`(判定结果: 合规/超限/禁用/未覆盖)

**领域服务**:`ComplianceEvaluator`
- 输入:`UsageDeclaration`(物质 + 动物 + 数量 + 单位)
- 输出:`ComplianceVerdict` + `RuleHit[]`(每条命中带 sourceArticleId 原文)
- **核心不变量**:规则未覆盖时**必须**返回 `未覆盖` 状态,**禁止**返回"合规"

**这是快档方案(1-2 周)的落点**。当前代码里**完全不存在**。

**仓储**:`ComplianceRuleRepository`(待建,表 `compliance_rules` / `rule_versions`)

**外部依赖**:通过 **ACL** 读 ① 的条文原文(只读,不反向依赖)

#### ③ 问答 Inquiry —— 支撑域,无状态编排

**通用语言**: 问题(Question)、检索证据(Evidence)、答案(Answer)、引用(Citation)

**聚合根**: 无。**领域服务**:`InquiryService` —— 一次问答 = 检索 → 组装证据 → LLM 生成 → 引用校验

**当前实现映射**:
| DDD 概念 | 现有代码 |
|---|---|
| 领域服务 `InquiryService` | `ragQA`(`index.ts:855`)+ `ragQAStream`(`index.ts:902`) |
| Prompt 组装 | `buildRagPrompt`(`index.ts:822`) |
| **领域服务 `CitationValidator`** | `validateCitations`(`index.ts:1023`)—— 这是**合规性保证**,不是工具函数 |
| 防腐层 ACL | `llmConfig()`(`index.ts:204`)+ `fetchWithRetry()`(`index.ts:141`) |

**关键约束**:`CitationValidator` 属于**领域服务**而非工具函数 —— 因为"引用必须可溯源"是**业务规则**(方案文档「合规优先」),不是技术细节。它决定了答案能不能对外发布。

#### ④ 知识图谱 Graph —— 支撑域(当前空表)

**通用语言**: 实体(Entity)、关系(Relation)、社区(Community)

**聚合根**:`Entity`
- 不变量:实体名在同一 type 下唯一

**当前状态**:`entities` / `entity_articles` 表**已建但为空**,`/api/entity/:name` 路由实测返回 `entity_not_found`。`EntityPage.tsx` / `EntityGraph.tsx` 前端组件已就位,等数据。

**防腐层 ACL**:`GraphRAG 索引`(`build/graphrag/` —— 仅 prompts + settings.yaml,从未跑过)

**决策**:此上下文**保持空壳直到有真实用例**。方案文档的图谱能力(关系推理)对当前"找条款"场景收益不明,而运维成本(GraphRAG 索引重建 + 增量维护)不低。**先留接口,不投实现**。

#### ⑤ 法规监测 Monitoring —— 支撑域(待建)

**通用语言**: 发布源(Source)、公告(Announcement)、版本差异(VersionDiff)、影响面(ImpactScope)、订阅(Subscription)

**聚合根**:`RegulationRelease`(一次法规发布)
- 聚合内部:`Announcement` + `VersionDiff` + `ImpactAssessment`
- 不变量:一个发布必须能算出「影响哪些物质/品类/标签声明」,算不出则标记 `影响面未知`,**不推送给用户**

**与 ① 的关系**:通过**领域事件**解耦 —— 监测上下文发出 `RegulationReleaseDetected`,① 上下文消费它并入库新版本。

**为什么用事件而不是直接调用**:① 是只读核心域,它的"写入"只能由外部版本变更驱动。用事件表达,① 不知道谁在监测,监测上下文不需要知道 ① 的表结构。

### 3. 依赖规则(严格)

```
        ┌──────────────────────────────────────┐
        │  ③ Inquiry (应用编排)                 │
        │  依赖 ① ② ④,通过 ACL 依赖外部 LLM     │
        └───────┬──────────┬──────────┬────────┘
                │          │          │
                ▼          ▼          ▼
        ┌────────────┐ ┌────────┐ ┌────────┐
        │①Regulation │ │②Compl. │ │④Graph  │   ← 核心域/支撑域,互不直接依赖
        └────────────┘ └────────┘ └────────┘
                ▲
                │ 领域事件 RegulationReleaseDetected
        ┌────────────┐
        │⑤Monitoring │  ← 仅通过事件影响 ①,不直接写 ① 的表
        └────────────┘
```

**强制规则**(违反即 code review 打回):

| 规则 | 说明 |
|---|---|
| **R1 · 上下文间只经 ACL 通信** | 禁止跨上下文直接 JOIN 对方表。② 要读条文原文,必须经 `RegulationRepository` + ACL,不得 `SELECT ... FROM articles` |
| **R2 · 依赖方向单一** | ③ → ①②④;⑤ --事件--> ①。**禁止** ① → ③(核心域不知道被谁调用) |
| **R3 · 外部系统一律 ACL** | LLM / bge / 政府网站 全部经防腐层。领域层不出现 `fetch()` |
| **R4 · 只读核心域** | ① ② 的表只允许经由各自仓储写入,禁止跨上下文写 |
| **R5 · 领域服务不依赖框架** | `ComplianceEvaluator` / `CitationValidator` 不得 import Workers/D1 类型 |

### 4. 分层(按 DDD 经典分层,但适配 Serverless)

```
┌─────────────────────────────────────────────────────────┐
│ 接口层 Interface (Controllers / DTO / ACL)             │
│  HTTP 路由 · 请求校验 · 响应组装 · 外部系统防腐层        │
├─────────────────────────────────────────────────────────┤
│ 应用层 Application (Use Cases / Orchestration)          │
│  InquiryService · ComplianceCheckUseCase                │
│  UseCase = 编排,不写业务规则                            │
├─────────────────────────────────────────────────────────┤
│ 领域层 Domain (Entities / ValueObjects / Services)      │
│  ★ 纯 TS,零框架依赖,零 I/O,100% 可单测               │
│  RegulationDocument · ComplianceRuleSet · Entity        │
│  ComplianceEvaluator · CitationValidator               │
├─────────────────────────────────────────────────────────┤
│ 基础设施层 Infrastructure (Repositories / Adapters)     │
│  D1Repository 实现 · bgeClient · llmClient · 爬虫适配器 │
└─────────────────────────────────────────────────────────┘
```

**Serverless 适配说明**:

| 经典 DDD | 本项目适配 | 理由 |
|---|---|---|
| Spring DI 容器 | **手写 Composition Root**(`index.ts` 顶层 new 出所有仓储/服务) | Workers 无 DI 容器;手写反而更透明,依赖关系一眼可见 |
| Repository 接口 + 实现分离 | **接口放 domain 层,实现放 infrastructure** | 领域层可 mock,测试不碰 D1 |
| 领域事件总线 | **Workers `ctx.waitUntil()` + 简单事件分发** | 不引入外部 MQ;事件量小 |
| 数据库事务 | **D1 单库 + 单次 batch** | D1 不支持跨表事务,领域边界设计已规避此需求 |

### 5. 目录结构(目标)

```
query/worker/src/
├── interfaces/                    # 接口层
│   ├── http/
│   │   ├── router.ts              # 路由分发(从 index.ts 抽出)
│   │   ├── routes/
│   │   │   ├── inquiry.routes.ts       # /api/qa
│   │   │   ├── regulation.routes.ts    # /api/documents, /api/catalog, /api/chapter, /api/article
│   │   │   ├── retrieval.routes.ts    # /api/search
│   │   │   └── graph.routes.ts         # /api/entity
│   │   └── dto.ts
│   ├── acl/                       # 防腐层
│   │   ├── llm.acl.ts             # provider 无关的 LLM 调用
│   │   ├── embedding.acl.ts       # bge-m3 客户端
│   │   └── regulation.acl.ts      # 外部法规源(未来 ⑤ 用)
│   └── composition-root.ts        # 组装所有依赖
│
├── application/                   # 应用层
│   ├── inquiry/
│   │   ├── inquiry.service.ts     # 检索→生成→校验
│   │   └── prompt-builder.ts
│   ├── compliance/
│   │   └── compliance-check.usecase.ts   # 快档新增
│   └── monitoring/
│       └── release-detect.usecase.ts     # 对档新增
│
├── domain/                        # ★ 领域层(纯 TS,零依赖)
│   ├── regulation/
│   │   ├── regulation-document.aggregate.ts
│   │   ├── article.vo.ts
│   │   └── regulation-query.service.ts
│   ├── compliance/
│   │   ├── compliance-rule-set.aggregate.ts
│   │   ├── limit-rule.vo.ts
│   │   ├── usage-declaration.vo.ts
│   │   └── compliance-evaluator.service.ts   # ★ 核心
│   ├── inquiry/
│   │   ├── evidence.vo.ts
│   │   ├── citation.vo.ts
│   │   └── citation-validator.service.ts     # ★ 核心
│   ├── graph/
│   │   └── entity.aggregate.ts
│   └── shared/
│       ├── domain-event.ts
│       └── rule-version.vo.ts
│
└── infrastructure/                # 基础设施层
    ├── persistence/
    │   ├── d1/
    │   │   ├── regulation.repository.impl.ts
    │   │   ├── compliance.repository.impl.ts
    │   │   └── graph.repository.impl.ts
    │   └── retrieval/
    │       └── hybrid-retriever.adapter.ts    # FTS5 + bge + RRF
    ├── llm/
    │   └── openai-compatible.client.ts
    └── embedding/
        └── bge.client.ts
```

### 6. 数据所有权(表 → 上下文)

| 表 | 归属上下文 | 写权限 |
|---|---|---|
| `documents` / `chapters` / `articles` | ① 法规知识库 | 仅 ① 的仓储(经 ⑤ 事件触发) |
| `articles_fts` | ① 法规知识库 | 同上(FTS 影子表) |
| `catalog` | ① 法规知识库 | 同上 |
| `compliance_rules` / `rule_versions` | ② 合规规则 | 仅 ② 的仓储 |
| `entities` / `entity_articles` | ④ 知识图谱 | 仅 ④ 的仓储 |
| `index_meta` | ④ 知识图谱 | 仅 ④ 的仓储 |
| `regulation_releases` / `subscriptions` | ⑤ 法规监测 | 仅 ⑤ 的仓储 |
| `catalog` — 修正:目录树属 ① 法规知识库(书籍原版层级) | | |

> **表共享禁令**:`entities` 当前被 `entity_articles` 外键引用 `articles`,这是**跨上下文外键**,违反 R1。
> 修正方案:图谱上下文改为存 `article_ref`(逻辑引用,不带 FK),由 ACL 在读取时解析。这样 ④ 可以独立演进,且将来 ① 换存储不影响 ④。

### 7. 领域事件

| 事件 | 发布者 | 消费者 | 载荷 |
|---|---|---|---|
| `RegulationReleaseDetected` | ⑤ 监测 | ① 知识库 | 新版本文档 id + 差异摘要 |
| `RegulationVersionIngested` | ① 知识库 | ② 合规规则 | 需要重算规则的条文 id 列表 |
| `RulesRecalculated` | ② 合规规则 | ⑤ 监测 | 受影响物质/品类集合 → 推送影响面 |
| `EntityRelationsExtracted` | ④ 图谱 | ③ 问答 | 实体 id 列表(供图谱增强检索) |

事件用 Workers `ctx.waitUntil()` 异步派发,**失败不阻塞主流程**,但必须记录到 `index_meta` 或日志。

---

## 现状到目标的映射(可执行)

### 阶段 M1 · 抽离领域层(不改变任何行为)—— 1 天 ✅ 已完成

**目标**:把纯逻辑从 `index.ts` 抽到 `domain/`,建立第一批单测。

| 现在 | 目标 |
|---|---|
| `validateCitations`(`index.ts:1023`) | `domain/inquiry/citation-validator.service.ts` |
| `buildRagPrompt`(`index.ts:822`) | `application/inquiry/prompt-builder.ts` |
| `llmConfig` + `fetchWithRetry`(`index.ts:141,204`) | `interfaces/acl/llm.acl.ts` |
| `plainExcerpt`(`index.ts:169`) | `interfaces/acl/regulation.acl.ts` |
| `r2Key`(`index.ts:221`) | `infrastructure/persistence/d1/mappers.ts` |

#### M1 交付结果(2026-10-28)

| 项 | 计划 | 实际 |
|---|---|---|
| `index.ts` 行数 | < 150 | **265**(M3 再压) |
| 领域层单测 | ≥ 20 | **109**(含 13 个架构测试) |
| Worker 测试基础设施 | 需要 | **从零建立**(此前 Worker 完全没有测试) |
| 架构规则守护 | 需要 | **13 个架构测试,已实测能捕获违规** |
| CI 门禁 | 需要 | 新增 `worker-test` job |

**验证结果**:
- worker 单测 109/109 · typecheck 干净
- web 单测 34/34 不变 · e2e 11/11 不变
- eval recall@10 **76.0%** / MRR 0.544 / 业务 MRR 0.488 —— 与基线**完全一致**
- 14 条 SQL 逐条比对一致 · 9 条路由逐条比对一致
- 生产 API 响应与重构前基线**逐字段全量比对一致**

#### ⚠️ M1 抓到的两个回归(重要教训)

| 回归 | 症状 | 根因 |
|---|---|---|
| `chapter_number` 从 `""` 变 `null` | 搜索结果字段类型变化 | 映射层用了 `String(x)`,把 D1 的 null 变成字符串 `"null"` |
| `is_toc` 字段凭空多出 | 文档列表每个对象多一个字段 | 映射层多映射了一列(原 SELECT 里没有) |

**两个都逃过了所有本地测试** —— 类型系统不报错、单测不失败、eval 门禁照样绿
(eval 是 Python 复刻, e2e 走 mock 模式, 都不碰真实 Worker 的映射层)。

**只有拿生产 API 的实际响应做前后比对才抓到。**

> **流程固化**:任何影响 Worker 响应的重构,必须
> ① 重构前抓生产基线 → ② 重构后逐字段比对 → ③ 不一致就修。
> 已补 `response-contract.test.ts`(13 个)把响应字段集合锁死。

### 阶段 M2 · 建合规规则上下文(快档核心)—— 3-5 天

**交付**:
- `compliance_rules` 表 + 仓储 + ACL
- `ComplianceEvaluator` 领域服务(纯函数,100% 单测覆盖)
- `POST /api/compliance/usage` 端点
- 前端「用量合规速查」输入框

**验收**:50 条真实限量规则入库 → 输入「维生素C + 猪 + 200mg/kg」返回「合规 + 依据条款原文」;输入超限量返回「超限 + 超出量 + 依据条款」;输入未覆盖物质返回「**规则未覆盖，需人工确认**」(**不允许返回合规**)

### 阶段 M3 · 领域层与基础设施层彻底分离 —— 3-4 天

**交付**:
- `index.ts` 从 1059 行 → < 150 行(仅剩 composition root + 路由挂载)
- 全部 D1 SQL 移入 `infrastructure/persistence/`
- 领域层引入 `domain/` 后单测覆盖率门禁

### 阶段 M4 · 拆上下文(对档)—— 按需

⑤ 监测(爬虫 + 差异检测)落地时,才建 `monitoring/` 上下文与事件机制。**不提前造**。

---

## 取舍

| 方案 | 优点 | 缺点 | 选择 |
|---|---|---|---|
| **按领域划分上下文 + DDD 分层(本方案)** | 边界对齐业务语义;规则引擎/监测有明确落点;领域层纯函数可单测 | 1059 行拆成 ~40 文件,短期可读性下降,需靠目录约定与 barrel 导出缓解 | **是** |
| 继续单文件 + 加注释分区 | 零迁移成本 | L3 必然失控,对档方案开工即第二遍混乱 | 否 |
| 照搬经典 DDD(仓储/工厂/规格 全套) | 教条完整 | Workers 无 DI 容器,大量样板代码换不来可测性收益 | 否 |
| 全面迁移到 FastAPI + PostgreSQL + Milvus(方案文档原选型) | 匹配 DDD 成熟范式;支持事务/向量库 | 放弃 Serverless 零运维优势;需服务器 + 迁移 3145 条文 + 重建索引;**违规本项目最大优势** | 否 |
| 只做分层不做上下文划分 | 改动小 | 规则库/监测归属仍不清,L3 未解决 | 否 |

**被否决的方案值得记录的原因**:方案文档的技术选型表(第 7 章)假设 FastAPI + Redis + PostgreSQL。实际落地用了 Cloudflare 全 Serverless,这是**受约束下的正确偏离**(零运维、零付费产品开通、CI 推代码即上线)。DDD 重构**不改变这个技术栈** —— 它是在现有栈内调整代码组织,不动运行时形态。

---

## 风险与应对

| 风险 | 等级 | 应对 |
|---|---|---|
| **DDD 换皮**:目录分了,依赖还是乱的 | 高 | R1-R5 五条强制规则写进 code review checklist;用依赖方向测试(架构测试)自动校验 |
| 拆文件引入行为回归 | 中 | M1 阶段**严格零行为变更**,用现有 34 个单测 + 9 个 e2e + CI eval 门禁三重护栏 |
| 领域层被基础设施污染(偷偷 import D1) | 中 | 架构测试:扫描 `domain/` 目录的 import,发现 `D1Database` 等即失败 |
| 只读核心域与"新增法规"流程冲突 | 低 | 写入统一走 ⑤ 的领域事件;① 的仓储提供 `ingestRelease()` 内部方法 |
| 过度设计:为不存在的需求建上下文 | 中 | ④ 图谱保持空壳不实现;⑤ 监测不到需求不建。**按需展开** |
| 团队不熟悉 DDD | 中 | 通用语言表放进代码注释与本文档;context 划分先用 3 周验证再推广 |

---

## 预期产出

1. **5 个限界上下文**,每个有明确的通用语言、聚合根、不变量与依赖规则
2. **领域层纯 TS 零依赖**,100% 可单测,不碰网络不碰数据库
3. **规则引擎有了确定的归属**(② 合规规则),快档方案可直接开工
4. **`index.ts` 从 1059 行瘦身到 <150 行**,新人可读
5. **架构测试自动守护依赖方向**,DDD 不靠人的自觉维持

---

## 关联文件

- `docs/architecture-analysis.html` —— 方案 vs 已实现对照(本文档的前置分析)
- `docs/adr/0003-minimax-corpus-rebuild-and-bigram-retrieval.md` —— 检索路径决策(→ `hybrid-retriever.adapter.ts`)
- `query/worker/src/index.ts` —— 当前单体实现(待拆分)
- `web/src/lib/api.ts` —— 前端 API 客户端(→ 按上下文拆 `api/` 模块)
- `饲料法规智能体架构方案.docx` —— 四子智能体与四期路径,本文档是它的实现侧映射
