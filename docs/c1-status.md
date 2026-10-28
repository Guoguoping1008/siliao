# C1 · 用量合规速查 —— 交付状态

- **日期**: 2026-10-28
- **对应**: `docs/functional-design.md` §4.10 C1 阶段 / ADR-004 M2
- **基线**: `v1.0.0-production` (b4645d7)
- **状态**: **代码完成, 生产待灌库(被 token 权限挡住)**

---

## 一、结论速览

| 项 | 状态 |
|---|---|
| 限量规则抽取器 | ✅ **37 条 / 11 种物质**, 溯源 100% |
| 物质目录抽取 | ✅ **74 条** |
| ② 合规规则领域层 | ✅ 聚合根 + 判定器 + 三级命名匹配 |
| D1 schema (3 张表) | ✅ `migrate_c1.sql` |
| `POST /api/compliance/usage` | ✅ 已部署生产 |
| 前端 `/compliance` 页 | ✅ 已部署生产 |
| 灌库进 D1 | ⏳ **被 token 权限挡住 —— 需你新建一个带 D1 Edit 的 token** |
| 规则审核(reviewed) | ⏳ 待人工逐条校核 |

---

## 二、已完成的部分

### 2.1 抽取器 —— `build/export/extract_compliance_rules.py`

**为什么从 `articles.json` 抽而不是 `minimax/*.md`**

`ingest_minimax.py` 里 `source_file` 只记 `files[0].name` —— 一个文档下所有 md 都记成第一个文件名。
实测《饲料添加剂安全使用规范》29 个 md 全部映射到 `0319.md`，无法区分。
而 `articles.json` 里 text 保留完整表格 HTML、article_id 天然正确，与 D1 的 `articles` 表一一对应。

**抽取结果**

```
限量规则候选 : 37 条 / 11 种物质
物质目录候选 : 74 条
溯源完整性   : 100%（无 source_article_id 一律拒绝入库 —— 不变量 2）
```

**实测校验（全部通过）**

| 校验项 | 结果 |
|---|---|
| 维生素C 正确性 | 猪 150~300 / 家禽 50~200 / 犊牛 125~500 mg/kg ✅ |
| 组合约束误抽 | **0**（「同时使用时总量不得超过150mg/kg」正确跳过）✅ |
| 质量指标误抽 | **0**（单位白名单排除「粗蛋白质≥50%」）✅ |
| 括号内例外 | 2 条（L-肉碱 乳猪300~500 是独立上限）✅ |

**踩的三个坑**（都写进代码注释了）

1. **OCR 把表头和数据行合并** —— 表0 第 0 行是「通用名称/L-抗坏血酸(维生素C) | ... | 适用动物/猪150～300mg/kg ...」
   丢掉它就丢了第一条规则。`parse_tables` 改成保留全部行。
2. **限量值可能不在「适用动物」列** —— 维生素D3 的「最高限量」列也有独立值。改成扫描所有列，靠单位白名单排除「含量规格」列。
3. **必须列感知** —— 朴素正则会把「粗蛋白质≥50%」误判成限量。

### 2.2 领域层 —— `query/worker/src/domain/compliance/`

| 文件 | 职责 |
|---|---|
| `compliance-rule-set.aggregate.ts` | 聚合根 `ComplianceRuleSet` + 规则/用法/判定 值对象 |
| `compliance-evaluator.service.ts` | 领域服务 `evaluateUsage` —— **判定逻辑全在这** |
| `substance-matcher.service.ts` | 三级物质名匹配 |
| `substance-catalog.vo.ts` | 物质目录值对象 |
| `compliance-request.vo.ts` | 入参校验（纯逻辑，脱离 HTTP 层可测） |

**两条不可协商的不变量**

1. **规则未覆盖必须返回 `not_covered`，绝不能返回 `compliant`**
   测试用**故意构造的未覆盖物质**锁死这个分支 —— 它极容易在后续重构里被"优化"掉。
2. **每条规则必绑 `source_article_id`，无出处不允许入库**
   这条同时落在 D1 表结构上（`source_article_id TEXT NOT NULL`），**不依赖应用层自觉**。

**命名匹配：三级，不做模糊匹配**

```
1 精确   2 括号别名(维生素C → L-抗坏血酸(维生素C))   3 别名表(英文名)
```

向量相似度匹配出的「维生素C ≈ 抗坏血酸钙」在合规判定里是**危险**的 —— 两者限量完全不同。
**宁可说「未覆盖，需人工确认」，不可猜。**

### 2.3 API 与前端

```
POST /api/compliance/usage
  入参 { substance, species, stage?, value, unit }
  出参 { status, matchedSubstance, ruleHits[], suggestion, coverageGap, ruleSetVersion, notice }
  status ∈ compliant | exceeded | prohibited | not_covered
```

**入参校验在 domain 层** —— 用量判定是确定性的，参数错必须明确报错（400），
不能像 LLM 抽取那样静默给个错结论（「200 是 mg/kg 还是 g/kg？」LLM 会猜）。

**前端 `/compliance` 页三个必须体现在 UI 上的决策**

1. **「未覆盖」是一等公民** —— 琥珀色 + 「需人工确认」+ 附检索到的相关条文，
   不用绿色显示「合规」蒙混过去
2. **依据条款原文必须可见** —— 每个结论带 `sourceExcerpt`，用户能自己核对
3. **免责标注常驻** —— 「辅助意见，不构成监管结论」+ 规则集版本

---

## 三、验证结果

| 项 | 结果 |
|---|---|
| worker 单测 | **153/153**（新增 44 个：判定 30 + 匹配 14） |
| worker typecheck | 干净 |
| 架构测试 | 13 个，**已实测能捕获新上下文的违规**（往 domain/compliance 塞 fetch → 立即变红） |
| web 单测 | 34/34 不变 |
| web e2e | **17/17**（新增 6 个合规速查用例） |
| 检索 eval | recall@10 **76.0%** / MRR 0.544 —— 与基线**完全一致** |
| CI / Deploy | 全绿 |

**e2e 的核心断言**：未覆盖时**绝不**显示成「合规」
（用 `exact: true` 避免匹配到页面标题「用量合规速查」里的「合规」）。

---

## 四、⚠️ 唯一阻塞项：灌库需要 D1 写权限

### 4.1 现象

CI 的 `seed-compliance` workflow 跑起来了，但**两条灌库路径都失败**：

```
D1 REST API 失败, 回退到 wrangler d1 execute
建表失败 —— 需要有 D1 编辑权限的 token
```

### 4.2 已排除的可能

| 可能 | 排除依据 |
|---|---|
| API 路径写错 | 本地实测 `/d1/database/{id}/query` 用无效 token 返回 **401 Authentication error**（不是 404 / No route） |
| SQL 语法错 | 建表拆成 10 条独立 `CREATE TABLE IF NOT EXISTS`；且探测步骤的**读查询成功** |
| Python 依赖问题 | 抽取步骤成功，脚本能跑 |
| workflow 没注册 | 已修（GitHub 只从默认分支读 workflow）；push 触发器已验证生效 |

### 4.3 唯一原因

**`CLOUDFLARE_API_TOKEN` secret 没有 D1 编辑权限。**

这与项目文档 `docs/deployment-info.md` 的记录完全一致：

> `/d1/database` → ⚠️ 401 —— 部署不需要，D1 数据是一次性灌的
> **没给 D1 权限是有意的** —— 最小权限原则

那个 token 是**故意**做成最小权限的（部署只需写 Worker/Pages）。而灌 D1 是另一类操作。

### 4.4 需要你做的（约 3 分钟）

**新建一个带 D1 权限的 token**：

1. Cloudflare Dashboard → 你的账户 → **API Tokens** → Create Token
2. 权限选 **Account → D1 → Edit**（Account Resources 选你的账户）
3. ⚠️ **不要设过期时间**（TTL 留空）—— 参见 `docs/cloudflare-token-setup-guide.html`
   里记录的 OAuth token 1 小时就过期、refresh_token 每次刷新都轮换的坑
4. 把它加到 GitHub secret：
   ```
   gh secret set CLOUDFLARE_D1_TOKEN
   ```
   （或网页端 Settings → Secrets and variables → Actions → New repository secret）
5. 告诉我一声，我改 workflow 用新 secret 名，再触发灌库

> **本地 wrangler token 也已过期**（9109 Invalid access token）——
> 刷新失败（`invalid_grant`，Cloudflare 会轮换 refresh_token）。
> 所以本地也走不通，只能靠 CI + 一个有 D1 权限的永久 token。

---

## 五、灌库之后的流程

```
① 灌库(pending)  → 规则进 D1, 但**不参与判定**
② 人工逐条校核    → 37 条规则逐个核对原文, 改 review_status
③ 提升为 reviewed → 规则开始参与判定
④ 生产验证        → POST /api/compliance/usage 实测三态
```

**② 人工校核是必须的，不是可选的。**

理由：自动抽取已经证明会把「质量指标」和「组合约束」误判
（虽然当前版本用单位白名单和组合检测挡住了，但**下一个新法规的表格格式
可能又是另一种写法**）。`review_status` 闸门就是为此存在的。

校核清单（37 条）：
- 物质名是否准确（尤其是英文名那几条：`Menadionedimethylpyrimid`、`Nicotinicacid` 看起来是 OCR 掉了空格）
- 动物种类是否正确
- 上下限是否完整（`5000~5000` 那种单值是否真的该是区间）
- 单位是否正确

---

## 六、提交记录

| 提交 | 内容 |
|---|---|
| `efe4df8` | feat(c1): 限量规则抽取器 |
| `cd2bf32` | feat(c1): ② 合规规则上下文 —— 领域层 |
| `12e6fc5` | feat(c1): 合规校验 API —— 仓储 + Use Case + 端点 |
| `a2176ea` | feat(c1): 前端「用量合规速查」页 + 灌库脚本 + CI workflow |
| `f8e03b4` | ci: seed-compliance 加 push 触发器 |
| `0ade729` | fix(ci): 去掉 paths 过滤器 + push 支持 mark-reviewed |
| `134d306` | feat(c1): 权限探测 + 双路径回退 + 失败诊断 |

---

## 七、关联文档

| 文档 | 关系 |
|---|---|
| `docs/functional-design.md` | 功能设计（C1 的验收标准来源） |
| `docs/adr/0004-ddd-bounded-contexts.md` | DDD 限界上下文（M2 = C1） |
| `query/worker/migrate_c1.sql` | D1 schema（3 张表） |
| `build/export/extract_compliance_rules.py` | 抽取器 |
| `build/export/seed_compliance.py` | 灌库脚本 |
| `.github/workflows/seed-compliance.yml` | 灌库 CI |
