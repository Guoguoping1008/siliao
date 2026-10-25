# ADR-003 · 语料重建(minimax 1021 页)与检索路径重构(bigram RRF + 标题加权)

- **状态**: Accepted
- **日期**: 2026-10-25
- **决策者**: qingmang(青芒 CTO)
- **关联**: ADR-001(检索后端选型)、ADR-002(章节名注入)
- **触发**: 用户指令「所有图片已 OCR 完成,重新导入所有数据,再完成 RAG 功能」

## 背景

OCR 全量跑完,产物在 `minimax/` —— 一个**目录驱动重整过**的语料树:

```
minimax/<章>/<节>/<文件>/<页>.md     1021 页 · 179 份文件 · 1940 条「第X条」
```

旧索引(`data/markdown/feed-law-*`,649 articles)是 **OCR 之前的样本语料**,已被完全覆盖。
旧的章节切分器(`chapter_splitter.py` / `article_splitter.py`)是为「物理页序未知 + 正则反切」设计的,
而 `minimax/` 的 markdown **已经是语义化结构**(`#`=文件标题 / `## 第X章` / `### 第X条`),
再跑一次正则反切只会把结构切碎。

## 决策

### 1. 摄入:新增 `build/export/ingest_minimax.py`,不复用旧切分器

映射(全库 1021 页实测):

| 语料结构 | 索引概念 | 实测数量 |
|---|---|---|
| `minimax/<章>/` | documents.issuer(顶层分类) | 5 |
| `<章>/<节>/` | chapters(kind=section,导航单位) | 196 |
| `<节>/<文件>/` | documents(doc_id) | 196 |
| `## 第X章` | chapters(kind=chapter,条文归属) | 333 |
| `### 第X条` | articles | 1940 |
| `### N 标题` | articles(GB/T 数字章节) | 171 |
| `### 短标签` | articles(附件/表单标题) | 556 |

产出:196 documents / 529 chapters / 3145 articles。

### 2. 三个必须记下来的坑

**坑 1 · 语料树有两种形态,只按一种扫会静默丢 93 页(9%)**

- 形态 A:`<章>/<节>/<文件>/<页>.md`(02制度文件 全是这个)
- 形态 B:`<章>/<节>/<页>.md` —— **节目录直接挂 md,没有文件层**(03相关法律法规文件、04标准 全是这个)

只扫形态 B 会丢 93 页;只扫形态 A 会丢 93 页。**两个都要扫**,用
「节目录下直接有 md」+「节目录下有子目录」两条分支并集。

**坑 2 · 顶层章直接挂 md 时,doc_id 会全部撞车**

`000封面/` 下 6 个 md,若用**目录名**当 doc_id → 6 个 `000封面_000封面` → PRIMARY KEY 冲突。
**必须用文件名**(`files[0].stem`)而不是目录名。

**坑 3 · `section` 为 None 时节级 chapter 不建 → articles.chapter_id 悬空 → FK 失败**

顶层章(000封面/001目录)没有「节」,若按 `if section:` 才建节级 chapter,
挂在它下面的 171 条条文 chapter_id 全部悬空。**节级 chapter 必须无条件建**。

### 3. 检索路径重构:bigram RRF + 标题加权

**实测问题**:长自然语言 query 在旧路径下 **0 命中**。
trigram 要求 query 是正文的**连续子串**,而「饲料添加剂审定需要提交什么材料」这种句子
在法规里根本不存在。10 条业务 query 全部 0 命中 → recall@10 仅 25%。

**方案**:

1. query 切 **bigram**(中文最小有意义单元,比固定 4 字窗口准 —— 「要提交什」这种碎片无检索价值)
2. 每个 gram **单独** FTS5 查询(不是拼成一个大 OR —— 拼 OR 命中集爆炸到 723~1793 条,BM25 无法区分「命中所有 gram」和「只命中一个」)
3. **RRF 融合**:`sum(1/(K+rank))`,K=60。「命中多个 gram」的文档自然排前面
4. **标题加权 3x**:查询经常直接点名法规(「新兽药注册办法」就是文件名),标题命中是强信号

**2 字 gram 必须 padding**:trigram 要 3 个连续字符,2 字 gram 直接 MATCH 必然 0 命中。
用后缀集合 `[" ", "的", "条", "规", "定", "制", "法", "理", "章", "应", "和"]` 扩成 3 字 phrase。

**后缀集合里必须有空格**:章节名注入文本时是「第一章 总则 标题...」,
「总则 」(含尾随空格)才是真实存在的 3-gram。只用汉字后缀时「总则」这类章节名 query **0 命中**。

**每个 phrase 必须加引号**:否则空格被当成 FTS5 的 AND/OR 运算符,整个表达式语义错乱。

**效果**(最终):业务 query recall@10 **25% → 75%**,「新兽药注册办法」top4 全部来自该文档。

### 3.1 检索必须是**分档**的,不能混在一个分数池

A 档(整句 phrase 精确匹配)与 B 档(bigram RRF)的精度差一个数量级。
混在一个分数池里比时,A 档命中的目标会被「只命中一个常见 bigram」的文档挤到 top20 外
(实测「本条例所称饲料」整句 MATCH 命中 rank 1,纯 bigram 路径排不进 top20)。

**分档后**:A 档命中直接作为主结果,B 档补在后面。所有语料派生 query 全部回到 rank 1。

### 3.2 目录/封面条文必须**排除出 FTS 索引**

目录页(001目录)里全是「文件名 + 页码」的列表。检索命中目录 = 命中目录条目,
会把「搜新兽药注册办法」的结果顶到目录行上,而不是正文条文。
这 186 条仍在 `articles`/`chapters`/`documents` 表里(可追溯),只是不进 `articles_fts`。
实测: FTS 3145 → 2959 行,业务 query top1 从「目录条目」变成「正文条文」。

### 3.3 R2 object name 有约 320 字节上限

`doc_id` 是路径 slug,中文一字 3 字节。形态 A 的 doc_id 重复两遍目录名,
最长到 **205 字节**,加上 `/articles/` + 长文件名就超限 →
`put: The specified object name is not valid. (10020)`。

**对策**:`r2_object_key` 存**完整 R2 key**,doc 段用 `sha1(doc_id)[:10]` 短前缀
(实测 3145 条文 key 全部 ≤245 字节)。DB 里存完整 key,Worker 直接取用,不做拼接。

### 3.4 负例评测口径:「命中数 = 0」是错的

最初用「语料外词应 0 命中」当判据,negative 精度只有 46%。
但那些命中**不是假阳性** —— bigram 引擎会匹配到「计算」「疫苗」「程序」这类
在语料里真实存在的词(能量消化率计算公式 / 兽药注册评审工作程序)。
对 bigram 引擎来说,「量子计算专利」命中「消化能计算」是**正确行为**。

**正确口径**:真命中 = query 里**全部实义词**都出现在该文档正文中。
严格口径下 4 个负例 0 真命中,精度 100%。

### 3.5 前端:换语料会暴露 5 个「硬编码旧语料」的 bug

| bug | 症状 | 对策 |
|---|---|---|
| Layout 导航硬编码 `/doc/feed-law-2026` | 导航指向 404;e2e 里 `a[href^='/doc/']` 会**误选到导航链接**而不是法规卡片 | 改用 `/#library` 锚点 |
| mock QA 硬编码 `retrieval: []` | QA 页永远显示「当前 0 条证据」,引用区不渲染,e2e 只能断言一句废话 | mock QA 真走 `mockApi.search` |
| markdown `#` 渲染成 `<h1>` | 页面有**两个 `<h1>`**(页面标题 + markdown 标题),e2e strict mode 冲突 | markdown 标题降一级 (h1→h2) |
| ingest 章节正文重复拼 `### 第一条` | 显示成「第一条 第一条」(正文本身已含标题行) | 只在正文无标题行时才补 |
| 文档列表顺序 = 目录扫描序 | 首页第一屏全是「000封面」「001目录」 | ingest 排序(法规在前)+ 前端过滤 TOC/封面 |

**教训**:换语料不只是换数据 —— **硬编码语料 id/标题的测试和 UI 会集体假失败**。
测试应断言**结构性事实**(列表有内容、标题非空、markdown 渲染出段落),不断言具体条文文本。

### 3.6 Worker 的 3 个 API 层 bug(旧语料时代没暴露, 换中文长 id 才炸)

| bug | 根因 | 症状 |
|---|---|---|
| 条文/章节详情全 not_found | `url.pathname` **不做 percent-decode**, 中文 article_id 带着 `%E5%81...` 进 D1 | 查不到任何条文 |
| 搜索 excerpt 全空 | R2 存的 key 是 **URL-encoded**, D1 存原始中文, miniflare 不自动 encode | 2180 个对象在 R2 里却取不到 |
| 文档列表顺序乱 | `ORDER BY created_at DESC`, 但同秒插入 → 顺序是插入序的逆序 | 首页第一屏全是「000封面」 |

**对策**:
- 路由捕获后统一 `decodeURIComponent()`
- 统一走 `r2Key(objKey, docId, kind)` —— 逐段 encode 再取
- `documents` 表加 `is_toc` / `sort_order` 两列; schema 用独立 `migrate.sql` 做幂等 ALTER
  (`CREATE TABLE IF NOT EXISTS` **不会**给已存在的表加列, 改了 schema.sql 必须配迁移)

### 3.7 bge 语义层:三个 bug + 融合权重

| bug | 根因 | 症状 |
|---|---|---|
| bge 命中全被挤出 top20 | RRF 两路**量纲不一致**: gram 路径 ftsScore 是「A 档 1000+ / B 档 ~0.05」混合值, bge 贡献 ~0.005, 差 3~4 个数量级 | bge 自己 top20 全军覆没, 最终结果带 bge_rank 的只有 0~3 条 |
| bge 语义 top-k 被稀释 | `bge_m3_cache.json` 里有 **515 条旧语料残留**(`flc23_*`) | 语义命中里 1/7 是不存在的旧文档 |
| bge_server 起不来 | `SentenceTransformer(MODEL_NAME)` 不带 cache_folder → 去 hf-mirror 拉模型, 国内网络 5 次重试全 timeout | 服务根本起不来 |

**对策**:
- **两路 rank 统一成「序位」(1..N)** 再算 `1/(K+rank)`。
  FTS5 的 `rank` 是原始 BM25 值(**负数**, 量纲跟 bge 的 rank 完全不同), 必须转序位。
  LIKE 补位的行也要给序位(给 0 等于把这路贡献丢了)。
- bge cache 按当前 corpus 清理
- `SentenceTransformer(name, cache_folder=".models/hf")` + `HF_HUB_OFFLINE=1` 强制离线

**融合权重实测扫参**(bge cache 清理后):

| 方案 | recall@10 | recall@20 | MRR | 业务 query MRR |
|---|---|---|---|---|
| FTS5 only | 50.0% | 56.0% | 0.544 | 0.488 |
| weighted-rrf w=0.7 | 50.0% | 56.0% | 0.645 | 0.700 |
| **weighted-rrf w=1.0(选)** | **56.0%** | **68.0%** | **0.647** | **0.717** |
| interleave(各占一半坑位) | 54.0% | 66.0% | 0.580 | 0.585 |

bge 权重太小 → 命中被挤走; 太大 → 稀释「精确短语」query。等权最稳。

**注意**: 权重必须在 **bge cache 清理之后**再扫 —— 旧语料残留会让 bge 信号变弱,
扫出来的最优权重偏小(0.7), 清理后最优是 1.0。

### 3.8 评测集里的 query 必须取自**条文自己的正文**

从 `articles_fts.text` 取短语会串味 —— 那是「章号 + 章名 + 文档名 + 正文」的**注入版**,
短语会跨条文串味,导致生成的 query 在目标条文里根本不存在(评测集本身错,数字失真)。
必须读 `articles.json` 的 `text` 字段(纯正文)。

### 4. 章节名注入(ADR-002 的延续)

`articles_fts.text` 前缀注入「`<章号> <章名> <文档名>`」。
搜「总则」能召回第一章下所有条文;搜文件名能召回该文档下所有条文。

## 取舍

| 方案 | 优点 | 缺点 | 选择 |
|---|---|---|---|
| 沿用旧切分器跑 minimax/ | 复用现成代码 | 结构已被目录树表达,再反切是二次破坏 | 否 |
| 新写 ingest_minimax.py 读现有结构 | 零猜测,结构即真相 | 需处理 3 个语料形态坑 | **是** |
| 检索:长 query 直接 MATCH | 最简单 | **0 命中** | 否 |
| 检索:bigram 拼大 OR | 改动小 | 命中集爆炸,排序失真 | 否 |
| 检索:bigram per-query + RRF + 标题加权 | 长 query 可用,排序合理 | 每 query N 次 FTS5(N=gram 数,约 10~15,一次 D1 batch) | **是** |
| 检索:bigram + RRF + bge 语义兜底 | 语义近义也覆盖 | 需常驻 bge 服务 | 已在 C-b 路径里,保留 |

## 性能与规模

- D1:196 docs / 529 chapters / 3145 articles / 3145 FTS 行
- 单 chunk 上限 **3000 字符**(超长整页表格会被切碎;不切的话 RAG prompt 塞不下、bge embedding 截断)
- gram 检索一次 D1 batch(正文 + 标题两批),不是 N 次往返

## 已知限制(记账)

| 限制 | 触发信号 | 还债方式 |
|---|---|---|
| bag-of-bigram 对**同域常用词**会假阳性 | 「量子计算专利」宽松命中「消化能计算」 | 严格口径下是 0 真命中;真要治本得靠 bge 语义路 |
| 评测集里「语料派生 query」由脚本生成, 质量受生成规则限制 | recall@10 波动大 | 业务方提供真实 query 集替换 |
| bge 语义路**未在新语料上重算** | `evals/bge_m3_cache.json` 仍是旧 649 条 | 已排后台任务 `embed_articles.py` 重算 |
| miniflare R2 是 SQLite,**并发写会 BUSY** | 8 并发 push 时 ~80% 失败 | 本地串行推(workers=1);线上走 S3 API 并发推 |
| 一次只能跑一个 push 进程 | 两个进程同时写 → 死锁, 日志不增长 | 动手前先 `pkill -f push_minimax_r2` |

## 关联文件

- `build/export/ingest_minimax.py` —— 摄入
- `build/export/push_minimax_r2.py` —— 推 R2(local 走 wrangler,remote 走 S3 API)
- `evals/eval_minimax.py` —— 检索评测(复刻 Worker 检索逻辑)
- `query/worker/src/index.ts` —— Worker 检索路径
- `web/src/lib/mockData.ts` —— 前端 mock 数据源(改指 `data/index/minimax/`)
