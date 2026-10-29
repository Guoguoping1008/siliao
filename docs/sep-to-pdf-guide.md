# 书生 SEP → PDF 转换方案

> **日期**: 2026-10-29
> **结论先行**: 书生 SEP **不能**用开源工具直接转 PDF —— 它是带 DRM 的私有版式容器，
> 唯一可靠路径是**书生官方阅读器**（书生 SEP Reader / 书生阅读器 V2.0）。
> 但如果你的实际数据是 **OFD**（书生新版产品线的国标格式），则有**纯开源路径**。

---

## 一、先搞清楚：SEP 到底是什么

北京书生电子技术有限公司（书生电子，1998 年成立）是**版式文档**领域的头部厂商，
与方正 CEB 并称「版式文档双雄」。

**SEP = Sursen e-Paper（书生数字纸张）**，是书生公司的第一代/第二代版式文档格式。
它的技术底座是 **UOML**（Unstructured Operation Markup Language，非结构化操作置标语言）——
由书生公司推出、被原信息产业部立项的文档接口标准，2005 年前后与中电标协
「文档库技术标准工作委员会」一起推动，UOML 联盟有 40 多家成员企业。

关键特性：

| 特性 | 说明 |
|---|---|
| **固定版式（数字纸张）** | 渲染结果与打印完全一致，字体/坐标已固化 |
| **私有容器 + DRM** | SUREXML 二进制 XML，**带加密保护**，没有公开渲染引擎 |
| **基于二进制 XML** | 不是 PDF 那种可解析的结构 |
| **国标路线** | 2016 年后主线转向 **OFD**（GB/T 33190-2016），SEP 是历史格式 |

---

## 二、⚠️ 第一步必须做的：识别你的 .sep 到底是什么

**`.sep` 扩展名被 10+ 个毫不相干的应用复用**：

| 来源 | 实际内容 | 能否直接转 PDF |
|---|---|---|
| **书生电子 SEP / SUREXML** | 版式文档（DRM 加密） | ❌ **需书生软件** |
| IGE+XAO SEE Electrical | 电气工程原理图（JetDB） | ❌ 需 SEE Electrical |
| SynthEdit | 音频插件 | ❌ |
| **印刷分色位图** | 单通道 TIFF（印版） | ✅ **可以** |
| 司法档案 | ZIP 压缩的诉讼卷宗 | ✅ 可以 |
| 方正/其他 | — | 视情况 |

网上那些「SEP 转 PDF 在线工具」**基本只认印刷分色 TIFF 和 CAD 原理图**，
对书生 SEP **完全无效** —— 书生 SEP 是加密私有容器，没有渲染引擎可用。

### 我已经写好了识别工具

```
E:\workspace\siliao\build\tools\sep_inspect.py
```

用法：

```bash
python build/tools/sep_inspect.py 文件.sep          # 单文件
python build/tools/sep_inspect.py --dir 目录          # 批量扫描
```

它做四件事：魔数匹配（TIFF/PDF/ZIP/OLE2…）→ 标识串搜索
（SUREXML/ShuSheng/UOML…）→ 熵值分析（加密数据熵 > 7.5）→ ZIP 内含物探测。

**已实测**（用构造样本验证）：

```
sample_separation.sep  → 印刷分色位图  (90%)  ✅ 可直接转 PDF
sample_ofd.sep         → ZIP 容器/OFD  (80%)  ✅ 可直接转 PDF
sample_pdf.sep         → PDF(改名)     (99%)  ✅ 可直接转 PDF
sample_encrypted.sep   → 高熵数据     (60%)  ❌ 需书生软件
```

---

## 三、方案双档

### 🟢 快档 —— 书生官方阅读器（推荐，1 小时内可跑通）

**唯一受支持的路径。** 书生官方产品线里有两个相关工具：

#### 3.1 书生 SEP Reader（免费版，v7.x / v8.0）

**下载**：书生电子官网 `sursenelec.com` → 书生阅读器 → 免费体验
（第三方站 3322/下载家/ZOL 也可下，但**建议官网拿最新版**）

**支持格式**：SEP、GW、GD、IFR、S2/S72/S92、MPS、PDF、JPG/TIF/GIF/BMP

**转 PDF 的三种方式**（按推荐度排）：

**方式 A — 打印到 PDF 打印机（最稳，版式 100% 保真）**

```
1. Windows 设置 → 打印机 → 添加 → "Microsoft Print to PDF"
   （或装 "Microsoft XPS Document Writer" 再转 PDF）
2. 书生阅读器打开 .sep
3. Ctrl+P → 打印机选 "Microsoft Print to PDF"
4. 纸张/边距按需调整 → 保存 → 输出 .pdf
```

**为什么这是首选**：SEP 是固定版式，打印管线是唯一**不损失版式**的导出方式。
阅读器自己转 PDF 有时会掉字体、表格错位。

**方式 B — 阅读器内「另存为」/ 版式互换**

书生阅读器 V2.0 的功能清单里明确列了：
「**输出PDF格式**」「**流版转换**」「**版式互换**」。

```
文件 → 另存为 → 输出格式选 PDF
或
文件 → 打印 → 目标选 PDF
```

> ⚠️ 注意区分「另存为副本」和「另存为文本」——
> **「另存为文本」会丢版式**，那不是你要的。

**方式 C — 批量脚本化（如果要转很多文件）**

书生 SEP Reader 是 **ActiveX/COM 组件**（早期是 IE 插件），
所以可以脚本驱动：

```powershell
# 需要装 "书生阅读器" + 注册 ActiveX 组件后
# PowerShell / VBScript 调用阅读器的转换接口
$sep = New-Object -ComObject "SureSense.Reader.Application"
$sep.Open("C:\data\a.sep")
$sep.SaveAs("C:\out\a.pdf", <PDF格式常量>)
$sep.Close()
```

**这条我没有实测**（本机没装书生阅读器，COM 类名和接口需要按实际安装版本核对）。
如果你的量很大，**先用方式 A 手工验证一批，再决定要不要走 COM 自动化**。

#### 3.2 书生阅读器 V2.0（商业版，￥520 永久授权）

**V2.0 才是支持 OFD 的那个**，功能比免费版全：

- 支持 **GB/T 33190-2016** 版式文档（OFD）
- 支持党政机关电子公文系列标准（GB/T 33478 / 33481）
- 「**输出PDF格式**」「**流版转换**」
- 可作为浏览器组件嵌入 B/S 系统
- 支持信创环境（中标麒麟 / 银河麒麟 / 统信 UOS，龙芯/兆芯/鲲鹏/飞腾）
- 公文语义树、签章验章、水印、脱红

> **选型建议**：
> - 只有 SEP 历史数据 → **免费 SEP Reader 足够**
> - 有 OFD + 需要批量/服务化 → 考虑 V2.0 或直接找书生做转换服务

---

### 🔵 对档 —— 绕开书生：先转 OFD，再用开源链

**适用场景**：你的数据其实是 **OFD**，或者对方愿意给 OFD 版本。

#### 4.1 OFD → PDF 的开源路径

**本机实测结论**（重要）：

| 工具 | 版本 | OFD 支持 | 说明 |
|---|---|---|---|
| **PyMuPDF** | 1.24.14 / MuPDF 1.24.11 | ❌ **不支持** | 实测 `fitz.open('*.ofd')` 抛 `FileDataError`。OFD 支持是后来才进 MuPDF 的，本机版本没有 |
| `ofdparser` | 0.0.8 | ✅ | 需 `reportlab`；纯解析，**排版保真度一般** |
| `ofdrw` (Java) | — | ✅ | Apache 许可，**java 渲染服务**最成熟，但对版式还原一般 |
| MuPDF 1.25+/1.26 | — | ✅ | 若可升级 PyMuPDF，OFD 支持可用 |

**推荐的两种做法**：

**做法 1 — 升级 PyMuPDF（最省事）**

```bash
pip install -U pymupdf        # 升到 1.26+ 才有 OFD
python -c "
import fitz
d = fitz.open('x.ofd')
d.convert_to_pdf()             # PyMuPDF 1.26+ 提供
"
```

**做法 2 — ofdrw 渲染服务（Java，最可控）**

```bash
# Apache OFDRW —— 支持 .ofd -> .pdf 转换
java -jar ofdrw-convert.jar -i input.ofd -o output.pdf
```

**做法 3 — 最好的办法：让源端直接出 PDF**

书生阅读器 V2.0 的「**版式互换**」就是干这个的。
如果是长期数据管道，让数据生产方**直接导出 PDF**，省掉全部转换环节。

---

### 🟣 兜底档 —— 只能拿到 PDF 截图/打印稿时

如果 SEP 加密 DRM 导致连书生阅读器都打不开（权限文件缺失、设备绑定）：

```
书生阅读器 → 打印 → Microsoft Print to PDF → 得到 PDF
再走 OCR 管线补文本层
```

**这条你已经有现成资产** —— 本仓库的 OCR 流程（`.venv-ocr` + PyMuPDF 1.24.14 +
scanned-book-ocr-md / scanned-table-ocr-md 技能）可以直接复用。

代价：**PDF 只有图像没有文本层**，RAG 检索质量会掉一档。

---

## 四、给 RAG 项目的落地建议

结合 `siliao` 项目的实际情况（`docs/functional-design.md` 的饲料法规语料）：

### 4.1 如果是喂 RAG 系统的法规语料

**不要转 PDF。**

理由：SEP/PDF 都是**固定版式**，文本层质量差、页眉页脚噪声多、表格结构丢失。
而 RAG 需要的是**结构化 Markdown**（带表格语义、可分块、可定位条款）。

本项目已有的路径更好：
```
minimax/*.md  ← 已经是从原始文档结构化出来的成品
  → articles.json (1021 页, 保留表格 HTML)
  → build/export/extract_compliance_rules.py (37 条限量规则)
```

**SEP → PDF 只会让链路倒退一步**：结构化 → 版式 → 再想办法结构化。

**唯一值得转 PDF 的场景**：SEP 里含有 `articles.json` 覆盖不到的**图表/示意图**，
或者需要保留**原始版式作为证据快照**（法务存档、争议时的原始凭据）。

### 4.2 如果是为了"归档原版"（推荐做法）

```bash
# 批量用书生阅读器转 PDF, 按原始目录结构落盘
# 然后在 D1 里加一列 source_pdf_path, 与现有 md/article_id 建立关联
```

**只做归档，不进检索管线。** RAG 检索仍然走 md。

### 4.3 如果确实需要 PDF 参与检索

```
SEP ──[书生阅读器]──> PDF ──[pdftotext/PyMuPDF]──> 文本 + 页码
                                              └──> 切块 + 向量化
```

**关键**：切块必须**带原文页码**，才能让回答溯源到 PDF 页。
本项目已有 `source_article_id` 溯源机制，PDF 页码可以作为二级锚点。

---

## 五、决策清单

**先回答这三个问题，再选路径**：

1. **你的 .sep 到底是什么？**
   → 跑 `python build/tools/sep_inspect.py --dir <目录>`
   → 命中「印刷分色位图」→ 直接转 PDF（ImageMagick / Pillow）
   → 命中「ZIP/OFD」→ 走开源 OFD 链
   → 命中「高熵/书生 SEP」→ 只能走书生软件

2. **数据量多大？**
   → 几十份 → 手工「打印到 PDF」即可
   → 几百份以上 → 评估书生阅读器 COM 自动化，或直接找书生买转换服务

3. **转换后是给 RAG 用，还是存档？**
   → **存档** → 书生阅读器打印到 PDF，最省事
   → **给 RAG 用** → 建议**不要转**，直接用现有 md 管线

---

## 六、我做不到的事（诚实标注）

| 事项 | 为什么 |
|---|---|
| 直接用开源库把**书生 SEP** 转 PDF | SUREXML 是加密私有格式，无公开渲染引擎。**技术上不存在**纯开源路径 |
| 实测书生阅读器 COM 自动化接口 | 本机未安装书生阅读器，COM 类名/接口签名需按实际版本核对 |
| 确认你的 .sep 究竟是哪种 | **需要你提供样本文件** —— 工作区里目前一个 `.sep` 文件都没有 |
| OFD → PDF 的高保真排版复现 | 开源工具（ofdparser/ofdrw）解析能出内容，但**复杂表格/字距还原不如原生渲染** |

---

## 七、产出物

| 文件 | 内容 |
|---|---|
| `E:\workspace\siliao\build\tools\sep_inspect.py` | SEP 文件识别工具（已实测） |
| `E:\workspace\siliao\docs\sep-to-pdf-guide.md` | 本文档 |

---

## 八、相关资料

| 来源 | 关键信息 |
|---|---|
| 书生电子官网 `sursenelec.com` | 书生阅读器 V2.0 官方下载/免费体验入口 |
| 安超云 OFD 版式阅读联合方案 | 确认 V2.0 支持 SEP/OFD/PDF 三格式，「输出PDF格式」「版式互换」「流版转换」 |
| 中电标协文档库技术标准工作委员会报道 | SEP 文档库技术是 UOML 标准的第一个成果，兼容 SEP/PDF/方正排版 |
| convert.guru SEP 分析 | `.sep` 被 10+ 应用复用；书生 SEP 用 SUREXML + DRM |
| 书生阅读器 V8.0 使用说明 | 「另存为副本/另存为文本」的差异；XPS 打印中间路径 |
