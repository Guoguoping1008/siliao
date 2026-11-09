# 饲料法规 RAG 项目 · 现状报告

- **报告日期**: 2026-11-09
- **测量方式**: 生产环境实测 + 本地门禁实跑（非文档复述）
- **代码基线**: `deploy/c-b-hybrid` @ `099507d`（已 push，未超生产部署）
- **生产地址**: 前端 https://siliao-web.pages.dev · API https://siliao-api.guoguoping.workers.dev
- **语料**: `minimax/` 1021 页 → 196 文档 / 529 章 / 3145 条文

---

## 一、结论速览

| 维度 | 状态 | 实测依据 |
|---|---|---|
| ① 法规检索 | 🟢 **生产可用** | `/api/search` 200 · `degraded:false` · 20 命中 · 7.2s |
| ③ 知识问答 | 🟢 **生产可用但慢** | `/api/qa` 200 · elapsed 37-63s（基线 11s） |
| ④ 知识图谱 | 🟢 **生产可用** | 481 实体 / 1951 关联 / 117 别名 · 中文搜索正常 |
| ② 合规速查 | 🟡 **表有数据但闸门未开** | 37 规则全 `pending` → 一律返回 `not_covered` |
| ③ 多轮会话 | 🟢 **生产可用** | `/api/qa/conversation` 200 · 55s |
| ⑤ 法规监测 | ⚪ **未开工** | M4 · 4-6 周 |

**一句话**：**检索和图谱这两块完全健康且指标与基线严丝合缝；问答能用但延迟劣化 4-6 倍；
合规速查代码 100% 完成、数据 100% 就绪，唯独卡在「37 条规则的人工校核」——这是唯一挡住业务上线的一项。**

---

## 二、本次实测挖出的真实问题

### 2.1 【P0 · 业务阻断】合规速查全线返回 `not_covered`

D1 实测：

```
compliance_rules: 37 条 | pending 37 | source_article_id 缺失 0
```

生产实测（`POST /api/compliance/usage`，参数齐全）：

```
{"status":"not_covered","matchedSubstance":null,"ruleHits":[],
 "coverageGap":{"reason":"规则库未覆盖该物质/动物组合, 需人工确认"}}
```

**这不是故障，是安全闸门按设计工作** —— 未审核规则不参与判定。但业务效果等价于
「功能不可用」：用户查「猪饲料维生素C限量 200mg/kg」，不论超限还是合规，一律回
`not_covered`。

> ⚠️ 值得肯定的是返回体诚实地附了 `coverageGap.reason` + `relatedArticles`
> （回落到《饲料和饲料添加剂管理条例》第二十五条原文），没有静默失败。
> 但 `matchedSubstance: null` 说明**连物质名都没匹配上** —— 这是规则闸门
> 拦在匹配之前的结果，符合设计。

**校核工具已就绪**：

```bash
python build/export/make_review_checklist.py
# → build/export/review_checklist.csv（人工填 decision 列）
# → build/export/review_checklist.md（查阅用，已补 rule_id 可回写 D1）
```

**建议从这 8 条开始**（自动标记「上下限相等」，需确认是单点还是区间）：

| 物质 | 物种 | 值 |
|---|---|---|
| 维生素D2 | 猪 / 牛 / 马 / 鱼类 | 5000~5000 / 5000~5000 / 4000~4000 / 3000~3000 IU/kg |
| 二甲基嘧啶醇亚硫酸氢钠甲萘醌 | 猪 | 10~10 mg/kg |
| L-肉碱 | 雏鸡 | 150~150 mg/kg |
| L-肉碱酒石酸盐 | 犬 / 猫 | 660~660 / 880~880 mg/kg |

**人工校核工时：1-2 小时（37 条）**。这是让 ② 正式上线的**唯一**剩余动作。

### 2.2 【P1 · 体验劣化】问答延迟从 11s 劣化到 37-63s

生产实测 4 次 `POST /api/qa`：

```
try1: HTTP 200 time 47.2s
try2: HTTP 200 time 63.1s
try3: HTTP 200 time 37.5s
try4: HTTP 200 time 48.4s   (elapsed_ms = 45974)
```

**根因**（11-09 三个提交引入）：旧模型 `MiniMax-Text-01` 被 provider 下线，
换成 `MiniMax-M3.1-Flash` —— 这是 **reasoning 模型**，响应分两段：

- `reasoning_content` —— 思考过程
- `content` —— 最终答案

**两者共用 `max_tokens` 配额**。`max_tokens=1000` 时 reasoning 吃掉全部预算导致
答案整段变空，于是提到 16000 —— 预算够了，代价是**推理段本身就要花 20-40 秒**。

`query/worker/src/interfaces/acl/llm.acl.ts:98-127` 有完整的实测记录：

```
| max_tokens | 正确 | 空答案 | reasoning 实际长度 |
```

**权衡**：这是「换活模型」换来的延迟成本，不是 bug。当前**可以接受**（40-60s 对
法规问答这类重推理场景尚可），但**没有 P95 指标、没有超时告警**，一旦用户量上来
或 provider 再变，会静默劣化。

**建议（择一）**：
- **快档**：保留 reasoning 模型，但加 `reasoning_content` 长度上限/超时熔断，
  超过阈值降级到非 reasoning 模型。改动小（~半天），保住正确性。
- **对档**：换非 reasoning 模型（如 MiniMax-M 系列非 thinking 版），
  延迟回 10-15s，但需重跑引用准确率 eval 确认质量不降。

### 2.3 【P2 · 卫生问题】根目录有未跟踪的重复 docx

```
?? 饲料法规智能体架构方案(2).docx     (18781 字节，与已跟踪的同名文件 byte 级相同)
```

已跟踪的是 `饲料法规智能体架构方案.docx`（18781 字节）。这是 10-28 的重复副本，
要么删掉，要么加进 `.gitignore`（`.gitignore` **行内注释不生效**，注释要单独占一行）。

---

## 三、生产实测明细（2026-11-09 16:0x-16:2x）

### 3.1 端点探测

| 端点 | 方法 | 结果 |
|---|---|---|
| `/api/documents` | GET | 🟢 200 · 36975 字节 |
| `/api/catalog` | GET | 🟢 200 · 38411 字节 |
| `/api/search?q=维生素C 限量` | GET | 🟢 200 · 20 命中 · `degraded:false` · 7.2s |
| `/api/qa` | POST | 🟢 200 · 37-63s · 1 citation · 答案含真实限量数据 |
| `/api/qa/conversation` | POST | 🟢 200 · 54.9s |
| `/api/entities?q=维生素` | GET | 🟢 200 · 返回 L-抗坏血酸(维生素C) 等物质实体 |
| `/api/entity/维生素C` | GET | 🟢 200 · 命中 `sub_80ec845b1197` + 关联条文 |
| `/api/entity/Niacinamide` | GET | 🟢 200 · 命中 `sub_18b9148b1021` |
| `/api/entity/L-抗坏血酸(维生素C)` | GET | 🟢 200（**需标准 URL 编码**，裸括号会被截断） |
| `/api/compliance/usage` | POST | 🟡 200 `not_covered`（闸门未开） |
| `/api/compliance/recipe` | POST | ⚪ 404（C2 未实现） |
| `/api/compliance/label` | POST | ⚪ 404（C3 未实现） |
| `/api/monitoring/releases` | POST | ⚪ 404（⑤ 未实现） |
| `/api/calendar` | POST | ⚪ 404（未实现） |
| `/api/documents/:id/status` | POST | ⚪ 404（版本追溯未实现） |

前端页面：`/` `/compliance` `/entities` `/qa` 全部 200。

### 3.2 D1 数据实测

```
articles          3145
entities           481   (387 物质 + 94 概念)
entity_articles   1951
entity_aliases     117
substance_catalog  387
qa_sessions          3
qa_messages          6
compliance_rules    37   (pending 37, 无溯源 0)
```

### 3.3 基础设施

| 项 | 状态 |
|---|---|
| bge 服务 `https://ns.hbnongfengyuan.cn` | 🟢 HTTP 200 · 126ms |
| bge 降级标记 | 🟢 `degraded:false`（语义召回在生效） |
| Worker 生产部署 | 🟢 2026-11-09 02:20 UTC（与代码基线同步） |
| git 同步 | 🟢 `HEAD == origin/deploy/c-b-hybrid` = `099507d` |

---

## 四、门禁现状（本地实跑）

| 门禁 | 结果 | 对比文档记录 |
|---|---|---|
| worker 单测 | 🟢 **254/254** | 227 → **+27**（新增降级可观测等） |
| worker typecheck | 🟢 干净 | 持平 |
| web 单测 | 🟢 **34/34** | 持平 |
| 检索 eval（带 bge，公网） | 🟢 recall@10 **76.0%** / MRR **0.647** | **与基线完全吻合** |
| ├ 业务 query | 🟢 recall@10 80.0% / MRR **0.717** | 持平 |
| ├ 语料派生 | 🟢 recall@10 73.3% / MRR 0.600 | 持平 |
| └ negative 严格精度 | 🟢 100%（0/4 真命中） | 持平 |
| 引用准确率 eval | 🟢 **100%**（阈值 95%） | 持平 |
| 架构测试 | 🟢 19 条 | 持平 |

> ⚠️ 检索 eval **必须指定 `BGE_SERVER_URL=https://ns.hbnongfengyuan.cn`**。
> 脚本默认指向 `127.0.0.1:8080`，本地没起 bge 时会**静默退化为纯 FTS5**
> （MRR 0.544），看起来像指标掉了，实际是没测到 hybrid。

---

## 五、代码结构（ADR-004 DDD 落地态）

```
query/worker/src/
├── index.ts                        (40 行 · 只做「Request 交给路由层」)
├── interfaces/
│   ├── http/
│   │   ├── router.ts               (路由分发)
│   │   ├── http-utils.ts
│   │   └── routes/
│   │       ├── regulation.routes.ts    ① 法规库
│   │       ├── inquiry.routes.ts       ③ 问答（含 SSE 组装）
│   │       ├── compliance.routes.ts    ② 合规规则
│   │       └── retrieval.routes.ts     检索 + ④ 图谱
│   ├── acl/
│   │   ├── llm.acl.ts              (LLM 调用 + DEFAULT_MAX_TOKENS)
│   │   └── llm-stream.acl.ts       (流式 + SSE 帧解析)
│   └── composition-root.ts
├── application/inquiry/
│   ├── qa-stream.service.ts
│   └── conversation.service.ts
└── domain/                         (①-⑤ 五个限界上下文)
```

**五条强制依赖规则**由 19 条架构测试守护：上下文间只经 ACL、依赖方向单一、
外部系统一律 ACL、只读核心域、领域服务不依赖框架。

---

## 六、未完成功能（11 项，2 项已完成）

| # | 功能 | 状态 | 阻塞 | 工作量 |
|---|---|---|---|---|
| 1 | D1 灌库（C1 合规规则） | ✅ 已完成 11-02 | — | 37 规则 + 387 目录 |
| 2 | C1.5 会话表建表 | ✅ 已完成 11-02 | — | 生产实测 200 |
| 11 | ④ 知识图谱 | ✅ 已补齐 11-03 | — | 481 实体 / 1951 关联 |
| **3** | **37 条规则人工校核** | ⏳ **等人** | **等人** | **1-2 小时** |
| 5 | 组合/条件规则抽取 | 🚧 未开工 | 可做 | 1-2 天 |
| 4 | 禁用规则抽取 | 🚧 未开工 | 可做 | 2-3 天 |
| 9 | 合规日历 | 🚧 未开工 | 可做 | 2-3 天 |
| 10 | 版本追溯 + 领域标记 | 🚧 未开工 | 可做 | 2-3 天 |
| 6 | C2 配方批量审查 | 🚧 未开工 | 可做 | 5-8 天 |
| 7 | C3 标签审查（GB 10648） | 🚧 未开工 | 可做 | 5-8 天 |
| 8 | ⑤ 法规监测 + 预警 | 🚧 未开工 | 可做 | 4-6 周 |

**依赖链**：#4 禁用规则 → #6 C2 配方审查（缺禁用规则做不出「禁用成分标红」）

**明确不做（数据源不存在，不是没排期）**：

| 项 | 原因 |
|---|---|
| 企业资质审查 | 语料是法规条文，不是企业实际证件库 |
| 抽检「同类产品风险提示」 | 抽检公告无 API，粒度是批次，无企业配方数据 |
| 合规日历·换证年检提醒 | 需企业侧证件到期日 |
| 真正的历史版本回溯 | 农业农村部不提供结构化历史 |
| 「物质 → 可用替代品」映射 | 这是新产品审定知识，语料是法规不是审定结论库 |
| 跨模块 Planner | 法规问答多单跳，复杂场景走确定性接口 |

---

## 七、下一步（按优先级）

### 立刻 · 需要你（1-2 小时）

```
37 条规则人工校核 → 回写 D1 review_status
   → 灌库 → 生产三态实测(compliant / exceeded / not_covered)
   → C1 用量合规速查正式上线 ✅
```

### 我可以立刻做（无阻塞）

| 项 | 周期 | 说明 |
|---|---|---|
| 问答延迟治理 | 0.5-1 天 | reasoning 熔断 + 超时告警 + P95 指标 |
| #10 版本追溯 + 领域标记 | 2-3 天 | 独立、见效快，改 schema 加过滤加端点 |
| #9 合规日历 | 2-3 天 | 独立，只做标准生效日 |
| #5 组合/条件规则抽取 | 1-2 天 | 依赖 #1 有数据（已满足） |
| 文档同步 | 0.5 天 | README / project-status 停在 11-02/11-03，需同步 |

### 建议

**#8 法规监测周期最长（4-6 周，爬虫脆弱性是主风险），如果只挑一件长周期现在开工，选它** ——
它决定「知识时效可审计」这条原则能不能落地。

---

## 八、已踩过的坑（别重蹈）

1. **`return promise` 不会进 try/catch** —— 必须 `return await promise`。
   M3 抽路由层时丢了 await，生产报 1101，根因是 D1 报错被掩盖成 Worker 崩溃。
2. **`.gitignore` 行内注释不生效** —— `Images/   # 说明` 整行都是匹配模式，
   曾提交 510 张扫描图（3.2GB）。注释必须单独占一行。
3. **不能重跑 `schema.sql`** —— 生产库 3145 条条文，wrangler 4.127+ 对「schema 变了」
   的库报 `D1_RESET_DO`，**会清空远端表**。用 `migrate_c1.sql` / `migrate_c15.sql` 单独跑。
4. **不要用 wrangler OAuth token 跑 CI** —— 1 小时过期且 refresh_token 每次轮换。
5. **SQLite 的 `LIKE` 对中文无效** —— 实测 `?q=维生素` → 0 条。改用 `instr()` → 15 条。
   **换回 LIKE 不会报错，只是永远搜不到东西。**
6. **eval 不指定公网 BGE 地址会静默退化** —— 看着像指标掉了，实际没测到 hybrid。
7. **reasoning 模型 `max_tokens` 与 `content` 共用配额** —— 给太小答案整段变空，
   给太大延迟劣化到 40-60s。

---

## 关联文档

| 文档 | 关系 |
|---|---|
| `docs/functional-design.md` | 功能设计（C1 验收标准来源） |
| `docs/unfinished-features.md` | 未完成功能清单（11-02 版） |
| `docs/c1-status.md` | C1 交付状态 |
| `docs/adr/0004-ddd-bounded-contexts.md` | DDD 限界上下文 |
| `docs/adr/0005-scheme-doc-update-proposal.md` | 方案文档 vs 实现对照 |
| `docs/deployment-info.md` | 生产资源与凭据权限 |
| `query/worker/src/interfaces/acl/llm.acl.ts:98-127` | reasoning 模型 max_tokens 实测记录 |
