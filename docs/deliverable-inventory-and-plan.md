# 饲料法规 RAG 平台 · 部署功能清单与下一步计划

**客户**：中国农业质量研究院 · 饲料检测研究所
**报告日期**：2026-11-03
**生产地址**：https://siliao-web.pages.dev
**数据基线**：`articles` 3145 条 / `documents` 196 部 / `chapters` 529 章 / `entities` 481 个

> 本报告的每一条状态都来自**生产实测**（浏览器 + API + D1 直查），不是文档转述。
> 实测方法与证据在文末「实测方法」一节。

---

## 一、已部署功能清单（生产实测可用）

### 1.1 功能总览

| # | 功能 | 状态 | 生产实测证据 |
|---|---|---|---|
| F1 | **法规知识库目录树** | ✅ 可用 | `GET /api/catalog` 200，返回 4 个 scope 树；`GET /api/documents` 200，196 部法规 |
| F2 | **法规全文检索**（FTS5 + bigram 混合） | ✅ 可用 | `GET /api/search?q=维生素C` → 20 hits，字段含 `excerpt`/`chapter_title`/`relevance` |
| F3 | **条文/章节原文查阅** | ✅ 可用 | `GET /api/chapter/:doc/:ch` 200（markdown 266 字符）；`GET /api/article/:id` 200 |
| F4 | **AI 问答（单轮，带引用溯源）** | ✅ 可用 | `POST /api/qa` 200，返回 `answer` + `citations` + `retrieval`，耗时含 `elapsed_ms` |
| F5 | **AI 多轮追问（指代消解）** | ✅ 可用 | `POST /api/qa/conversation` 200，返回 `resolvedQuery`；实测答案「维生素C 在猪…最高限量是 300mg/kg [3]」 |
| F6 | **用量合规速查**（确定性判定） | ⚠️ **代码完成但闸门关闭** | 端点 200，但 37 条规则全 `pending` → 恒返回 `not_covered`。详见 §1.3 |
| F7 | **知识图谱 · 实体列表** | ✅ 可用 | `GET /api/entities` 200；浏览器实测 `/entities` 渲染 50 张实体卡、13 个类型筛选按钮 |
| F8 | **知识图谱 · 实体↔条文关联** | ✅ 可用 | 481 实体 / 1951 条关联 / 117 条别名；`/api/entity/维生素C` → 2 个相关条文 + 关系图谱，0 崩溃 |
| F9 | **实体别名检索** | ✅ 可用 | `维生素C` → `L-抗坏血酸(维生素C)`；`Niacinamide` → `烟酰胺`（method=alias） |

### 1.2 页面走查（真实浏览器，2026-11-03）

| 页面 | 路由 | H1 | 渲染 | 崩溃 |
|---|---|---|---|---|
| 首页 | `/` | 农业饲料法规知识库 | 9914 字符 | ❌ |
| 搜索 | `/search?q=维生素C` | — | 12038 字符 | ❌ |
| AI 问答 | `/qa` | AI 问答 | 174 字符 | ❌ |
| 多轮问答 | `/conversation` | 多轮问答 | 198 字符 | ❌ |
| 合规速查 | `/compliance` | 用量合规速查 | 232 字符 | ❌ |
| 实体列表 | `/entities` | 知识图谱实体 | 1487 字符 | ❌ |

**6/6 页面零崩溃。**

### 1.3 ⚠️ F6 合规速查：唯一的功能性阻塞（已定位根因，24 小时内可解）

**现象**：任何查询都返回 `not_covered`（「规则库未覆盖该物质/动物组合」）。
**实测证据**（探针，生产 D1 直接改 + 回滚）：

| 探针 | 结果 |
|---|---|
| 改前：37 条规则全 `pending` | 任何物质 → `not_covered` |
| 探针 1：只把 1 条规则置 `reviewed` | `L-抗坏血酸(维生素C)/猪/200` → **compliant**；`/5000` → **exceeded** |
| 探针 2：规则 + 物质目录全置 `reviewed` | **13/13 全部命中判定**（下表） |

**根因：有两道闸门，不是一道。** 判定引擎要同时拿到规则**和**物质目录，
任一没放行都恒返回 `not_covered`：

| 表 | 读取处 | 条件 | 生产现状 |
|---|---|---|---|
| `compliance_rules` | `compliance.repository.impl.ts:60` | `review_status='reviewed'` | **37 条全 pending** |
| `substance_catalog` | `compliance.repository.impl.ts:67` | `review_status='reviewed'` | **387 条全 pending** |

> **实测踩到的坑**：只放开规则闸门时，判定**仍然** `not_covered` ——
> 因为规则匹配不到物质（目录是空的）。**两道闸门必须同时开。**

**「未审核规则不参与判定」是刻意的安全闸门**（合规场景不能拿没校核过的规则出结论）。
**这不是 bug，是校核工作没做完。**

**闸门打开后的实测判定结果**：

| 物质 | 动物 | 用量 | 判定 | 匹配方式 |
|---|---|---|---|---|
| 维生素C | 猪 | 200 mg/kg | compliant | alias |
| 维生素C | 猪 | 5000 mg/kg | exceeded | alias |
| L-抗坏血酸(维生素C) | 猪 | 200 mg/kg | compliant | exact |
| 烟酰胺 | 猪 | 30 mg/kg | compliant | exact |
| 烟酰胺 | 肉鸡 | 10 mg/kg | exceeded | exact |
| 维生素D3 | 猪 | 200 IU/kg | compliant | exact |
| 烟酸 | 猪 | 40 mg/kg | compliant | exact |
| 肌醇 | 鲤鱼 | 400 mg/kg | compliant | exact |
| D-生物素 | 猪 | 1 mg/kg | exceeded | exact |
| L-肉碱 | 猪 | 200 mg/kg | exceeded | exact |
| 天然维生素E | 猪 | 200 IU/kg | exceeded | exact |
| 维生素D2 | 牛 | 300 IU/kg | compliant | exact |
| 二甲基嘧啶醇亚硫酸氢钠甲萘醌 | 猪 | 5 mg/kg | exceeded | — |

**13/13 通过。引擎本身完全正常** —— 三级物质匹配（精确/括号别名/英文别名）、动物匹配、
限量上下限判定、超限判定、依据条款回溯，全部工作正常。

> **两个探针都已完整回滚**，生产库现状：`compliance_rules` 37 pending / `substance_catalog` 387 pending，
> `articles` 3145 条未动。

**⚠️ 现状的真实风险**：检测所人员如果直接使用，**看到的是「查不到」而不是「不合规」**。
系统在 `not_covered` 时明确提示「本系统不判定未覆盖的情形，请由合规人员核对相关条款后决定」
并附上相关条款原文 —— **行为是正确的**，但如果没人知道要去开闸门，
这个功能会被误认为「没做」。

---

## 二、下一步功能计划

### 2.1 优先级判定原则

按**「检测所日常业务的出现频次 × 数据是否已就位」**排序，不按技术难度排。

检测所的核心工作流是：**来样 → 确定检测项目 → 找检测方法标准 → 判定限量/禁限 → 出报告**。
本平台当前覆盖的是最后两步的**一半**，最缺的是中间两步。

---

### 2.2 P0 · 解除合规速查闸门（0.5 天工程 + 人工校核）

**做什么**：
1. 人工校核 37 条规则（CSV 工作表已备：`build/export/review_checklist.csv`，
   **rule_id 已对齐生产 D1，37/37 校验通过**），
   把确认无误的置 `reviewed`，有误的先修再置。
2. 人工校核 `substance_catalog` 387 条的 `name_cn` / `name_en` / `substance_alias`
   （决定能否被搜到 —— 72 条有 `substance_alias`、74 条有 `name_en`）。
3. **两道闸门都要开** —— 见 §1.3。只开规则不开目录，判定仍是 `not_covered`。
4. 顺带修一条抽取器缺陷：`extract_compliance_rules.py:382` 把 `rule_type` 硬编码成 `"limit"`，
   导致 `status=prohibited` **永远不可能返回**。

**操作入口**（本次新增，端到端已实测）：

```bash
# 生成校核工作表(rule_id 自动从生产 D1 反查)
python build/export/make_review_checklist.py

# 填完 decision 列后 —— 先 dry-run 看要做什么
python build/export/apply_review_checklist.py --reviewed-by "张三(检测所)"

# 确认后写库 + 同时放行目录
python build/export/apply_review_checklist.py --reviewed-by "张三" --apply --also-release-catalog
```

**为什么先做**：判定引擎已实测正常，**只差两道人工闸门**。这是投入产出比最高的一项 ——
0.5 天工程量换来检测所最常用的「这个用量合不合规」功能可用。

**⚠️ 必须人工，不能自动放开**：37 条规则里 `stage` 字段全空、`rule_type` 全是 `limit`，
说明抽取器**没有区分生长期**（育肥猪/雏鸡/乳猪的限量不同）。自动置 `reviewed` 会让错误规则直接出结论。

---

### 2.3 P1 · 检测项目矩阵 + 检测方法标准检索（3-5 天）★ 检测所最高价值

**这是语料里已经存在、但平台完全没用上的最高价值数据。**

**实测数据**：

- 《饲料质量安全监督抽查检测工作要求》含 **检测项目 × 产品类型** 矩阵表
  （检测项目 15 行 × 产品类型 12 列，含 ✓ 勾选）—— 实测已能解析出表格结构。
- 《饲料产品标准和检测方法标准目录》含 **422 个标准编号**（GB/T、GB、NY/T、JB/T）+ 标准名称 + 类别，
  实测正则可稳定抽出 **554 个标准编号**（全语料）。
- 关键词命中：**检验 438 条文 / 检测 317 条文 / 标签 171 条文 / 抽样 90 条文 / 判定 35 条文 /
  复检 23 条文 / 标准物质 13 条文 / 仲裁 4 条文**。

**做什么**：
1. **检测项目矩阵 → 抽成结构化表**：`detection_matrix(detection_item, product_type, required)`
2. **标准目录 → 抽成结构化表**：`standards(standard_no, title, category, scope)`
3. **新端点**：
   - `GET /api/detection/items?product_type=水产饲料` → 该产品必检项目清单
   - `GET /api/detection/standards?q=维生素` → 相关标准编号 + 名称 + 适用类别
4. **前端页**「检测方法查询」：输入产品类型 → 必检项目 + 对应标准编号，一键跳原文

**为什么是 P1 第一位**：检测所人员每天的问题就是「这个产品要检哪些项目？按哪个标准检？」
现在这个问题需要人去翻 20 页标准目录。这个功能做完，平台才从「法规检索工具」变成「检测工作台」。

**技术可行性已验证**：表格是标准 HTML `<table>`，不是碎片化 OCR —— 用现有的
`ocr_corpus_filter` / 列感知抽取思路可直接解析。

---

### 2.4 P2 · 禁用规则 + 组合约束规则（2-3 天）

**做什么**：
1. 抽 `rule_type='prohibited'`（禁用物质 → 直接不合格）
2. 抽组合约束类型（`同时使用时总量不得超过 X mg/kg`）
3. 修抽取器硬编码 `rule_type="limit"` 的缺陷

**数据已就位**：**禁用 38 条文 / 禁止使用 27 条文 / 不得使用 16 条文 / 严禁使用 4 条文**。
当前 37 条规则**全是 limit**，一条禁用规则都没有 —— 检测所出具「不合格」结论时，
禁用物质是最硬的理由，却恰恰缺失。

---

### 2.5 P3 · C2 配方批量审查（5-8 天）

**做什么**：`POST /api/compliance/recipe` —— 上传配方成分表（多行）→ 逐成分风险报告，
禁用成分标红 + 依据条款。

**依赖**：P0 + P2。缺 P2 的话「禁用成分标红」做不出来。

**⚠️ 约束（写在方案文档里的硬要求）**：配方是企业敏感信息，
**C2 上线前必须完成 LLM 私有化评估**。当前 LLM 走公网（DeepSeek/MiniMax）。

---

### 2.6 P4 · C3 标签审查（5-8 天，可与 P3 并行）

**做什么**：`POST /api/compliance/label` —— 输入标签文案 → 输出缺失项 / 违规宣称清单，每项带条款出处。

**数据已就位**：`04标准及标准目录/01_饲料标签/` 实测 31 条文 + `兽药标签和说明书管理办法` 27 条文，
GB 10648 系列编号已抽出。

**依赖**：独立，可与 P2/P3 并行，不依赖 P0。

---

### 2.7 暂不排期（并说明为什么）

| 项 | 原因 |
|---|---|
| **实体↔实体关系**（GraphRAG） | 数据基础已就位（481 实体），但当前所有已上线功能都不消费实体间关系，**场景收益不明**。ADR-004 决策「保持空壳直到有真实用例」。 |
| **⑤ 法规监测 / 变更预警** | 4-6 周。检测所更关心「标准换版了吗」而非「法规改了吗」—— **可降级为 P1 的标准目录版本号监控**，成本远低于全量法规爬虫。 |
| **企业资质审查 / 抽检结果风险提示** | 数据源不存在。语料是法规不是证件库；抽检结果由农业农村部以公告 PDF 发布，**无 API**。 |
| **合规日历** | 需企业侧证件到期日，语料里没有。 |

---

## 三、检测所视角的场景覆盖度

| 检测所日常任务 | 当前平台支持度 | 缺什么 |
|---|---|---|
| 「这个产品要检哪些项目？」 | ❌ **不支持** | 检测项目矩阵未抽（P1） |
| 「按哪个标准检？」 | ⚠️ **半支持** —— 能搜到 GB 编号，但不是结构化查询 | 标准目录未抽（P1） |
| 「这个用量合不合规？」 | ⚠️ **代码就绪，闸门关闭** | 人工校核（P0） |
| 「这物质禁用吗？」 | ❌ **不支持** | 禁用规则未抽（P2） |
| 「配方里有没有违规成分？」 | ❌ 未开工 | C2（P3） |
| 「这标签缺什么？」 | ❌ 未开工 | C3（P4） |
| 「这个限量的依据条款是哪条？」 | ✅ **支持** | — 合规速查返回 `ruleHits` 带 `source_article_id` |
| 「这个法规/标准说了什么？」 | ✅ **支持** | 检索 + 问答 + 原文查阅 |
| 「哪些物质超标过？」 | ❌ 不支持 | 无抽检结果数据（数据源不存在） |

**结论**：检索与溯源两类需求**已完全满足**；**判定类需求差一道人工闸门**；
**检测作业类需求（检什么、按什么标准检）是当前最大的空白**，且数据已在语料里躺着。

---

## 四、执行顺序建议

```
第 1 周   P0 人工校核 37 规则 + 387 目录  →  合规速查真正可用
          (工程 0.5 天，人工校核 1-2 天)

第 2-3 周 P1 检测项目矩阵 + 标准目录结构化  →  检测方法查询页
          (工程 3-5 天，与 P0 并行)

第 4 周   P2 禁用规则 + 组合约束  →  禁用物质可判定
          (工程 2-3 天)

第 5-8 周 P3 C2 配方审查 ‖ P4 C3 标签审查（并行）
          (各 5-8 天，P3 前须完成 LLM 私有化评估)
```

**快档 / 对档**：

| | 快档 | 对档 |
|---|---|---|
| 范围 | P0 + P1（4-8 周） | 快档 + P2 + P3 + P4（10-16 周） |
| 交付 | 检索 + 判定 + 检测方法查询 | + 配方审查 + 标签审查（检测所全流程） |
| 风险 | 检测所仍需人工查禁用物质与标签 | P3 需 LLM 私有化评估（企业配方敏感） |

**建议走快档**。理由：P0+P1 覆盖了「查什么、按什么标准检、合不合规」这条主线，
是检测所最高频的三个问题；P3/P4 依赖的企业数据流尚未确定（谁上传配方？送检方还是企业？）
需求形态可能还会变 —— **等真实用法出来再定，比现在猜着做更省**。

---

## 五、风险与诚实说明

| 项 | 说明 |
|---|---|
| **37 条规则的 `stage` 全空** | 抽取器没区分生长期。育肥猪/雏鸡/乳猪限量不同 —— 人工校核时**必须逐条核对生长期**，不能批量点「通过」。 |
| **37 条规则的 `rule_type` 全是 `limit`** | 抽取器硬编码，禁用规则一条都没抽。P2 之前，系统给不出「禁用」结论。 |
| **11 种物质 / 37 条规则** | 覆盖的是《安全使用规范》里的维生素与氨基酸类。**不是全部添加剂** —— 判定为 `not_covered` 时系统会提示转人工，不会假装有结论。 |
| **`stage` 参数前端有「阶段(可选)」输入框** | 但规则表 `stage` 全空 → **阶段筛选目前无效**。P0 校核时若不补 stage，这个输入框是摆设。 |
| **合规速查的 `not_covered` 提示** | 系统明确写「本系统不判定未覆盖的情形，请由合规人员核对相关条款后决定」—— 这是**设计如此**，不是缺陷。但检测所人员可能误读为「功能没做」，**需要一次培训/说明**。 |
| **校核工作表的 rule_id 已修** | 原 `make_review_checklist.py` 在 CSV 里编 `r_001` 这类序号，与生产 D1 的哈希 ID **37/37 全对不上** —— 人工填完根本没法回写。本次已改为从生产 D1 反查真实 ID，**37/37 校验通过**。 |
| **CI 自动灌库仍缺专用 token** | GitHub Actions 不能交互式 OAuth。需要另建 TTL 留空、带 D1 Edit 权限的 API Token 存为 `CLOUDFLARE_D1_TOKEN`。**不影响本地开发**，但 CI 一键灌库目前不可用。 |
| **检索结果 `article_number` 常为空** | 非「第X条」型条文（表格、目录、申报指南）本身就没有条号。前端已归一化为空串，不会崩。 |
| **本报告未覆盖** | 未做多用户/权限（当前无鉴权）、未做并发压测、未做移动端专项验收。 |

---

## 六、实测方法（可复现）

```bash
# 1. 端点清点
curl -s https://siliao-web.pages.dev/api/documents | jq '.documents|length'      # 196
curl -s https://siliao-web.pages.dev/api/entities?limit=5 | jq '.count'          # 5
curl -s "https://siliao-web.pages.dev/api/entities?q=维生素" | jq '.count'      # 15

# 2. 合规判定（当前闸门关闭）
curl -s -X POST https://siliao-web.pages.dev/api/compliance/usage \
  -H 'Content-Type: application/json' \
  -d '{"species":"猪","substance":"维生素C","value":200,"unit":"mg/kg"}' | jq '.status'
# → "not_covered"

# 3. 闸门探针（D1 REST 直查 → 改 → 测 → 回滚）
#    scripts: build/export/refresh_cf_token.py --check
#    UPDATE compliance_rules SET review_status='reviewed' WHERE rule_id='r_0272c3e2d348'
#    → 实测 compliant / exceeded
#    UPDATE compliance_rules SET review_status='pending' WHERE rule_id='r_0272c3e2d348'
```

**探针纪律**：任何生产数据探针**必须**在 `finally` 块里无条件回滚。
本次两个探针已验证回滚到位（`compliance_rules` 37 pending / `substance_catalog` 387 pending）。

---

## 附：本次新增资产

| 文件 | 用途 |
|---|---|
| **`docs/deliverable-inventory-and-plan.md`** | **本报告**（部署功能清单 + 下一步计划） |
| **`build/export/apply_review_checklist.py`** | **校核结果回写 D1**（ok/fix/reject 三态 + `--also-release-catalog` 开第二道闸门）。端到端已实测，dry-run 默认开启 |
| `build/export/make_review_checklist.py` | 校核工作表生成 —— **本次修好 rule_id 对齐**（原用 `r_001` 序号，与生产 D1 **37/37 全对不上**；现按 substance+species+min+max+unit 反查真实哈希 ID） |
| `build/export/seed_substance_entities.py` | 物质实体 + 关联 + 别名灌库（幂等，`--dry-run` / `--remote`） |
| `query/worker/migrate_graph.sql` | `entity_aliases` 表迁移（与 schema.sql 分开，避免 D1_RESET_DO） |
| `build/export/refresh_cf_token.py` | Cloudflare OAuth token 自动续期（`--check` / `--force`） |
| `build/export/review_checklist.csv` | **37 条规则人工校核工作表**（P0 的操作入口） |
| `docs/unfinished-features.md` + `.html` | 11 项未完成功能清单（含本次实测证据） |
| `docs/project-status.md` + `.html` | 项目总体状态 |
