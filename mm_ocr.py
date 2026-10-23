"""MiniMax API 批量 OCR -> 每页一个 Markdown。

设计要点(实测调出):
1. 图片必须**缩放到 <=1600px 宽**再送 API。
   原图 2330px 宽时 MiniMax-Text-01 会直接拒绝("抱歉，我无法识别图片中的文字内容"),
   缩到 1600px 后正常输出。这是模型的图像 token 上限问题, 不是内容问题。
2. 顶部物理裁掉 13% 页眉带。实测页眉文字带在页高 4%~9%,
   裁 13% 一定不会伤到正文第一行。
3. 缩放后再裁, 避免裁完再放大导致插值模糊。
4. OCR 原始输出 -> 结构化 Markdown:
   - 第N章 / 第N条 / 附录X  -> ###
   - 发文标题(文号行/文件标题) -> #
   - 其余按空行分段
5. 页眉即使漏进来(书脊弯曲导致裁剪线以下), 也有内容级兜底过滤。

用法:
  python mm_ocr.py --sample 20          # 抽样验收
  python mm_ocr.py --all                # 全量
  python mm_ocr.py --resume             # 断点续跑
"""
import os
import re
import sys
import json
import time
import base64
import argparse
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

# ---------------- 路径 ----------------
SRC_ROOT = r"E:/workspace/siliao/Images_split"   # 已拆好的单页图
DST_ROOT = r"E:/workspace/siliao/minimax"
PROGRESS = r"E:/workspace/siliao/.mm_ocr_progress.json"

# ---------------- API ----------------
API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
MAX_TOKENS = 8000
TIMEOUT = 300
MAX_RETRY = 3

# ---------------- 图像参数 ----------------
TARGET_W = 1600        # 超过这个宽度模型会拒识
HEADER_CROP = 0.13     # 顶部页眉带裁掉比例
JPEG_QUALITY = 88

# ---------------- 并发 ----------------
WORKERS = 12

_lock = threading.Lock()


def _api_key():
    env = r"C:/Users/Administrator/AppData/Local/hermes/profiles/qingmang/.env"
    with open(env, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MINIMAX_CN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("MINIMAX_CN_API_KEY not found")


API_KEY = _api_key()


# ---------------- 图像预处理 ----------------
def prep_image(path, target_w=TARGET_W, header_crop=HEADER_CROP):
    """读图 -> 裁页眉 -> 缩放 -> JPEG bytes。"""
    im = Image.open(path)
    im = im.convert("RGB")
    W, H = im.size
    top = int(H * header_crop)
    im = im.crop((0, top, W, H))
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    import io
    o = io.BytesIO()
    im.save(o, "JPEG", quality=JPEG_QUALITY)
    return o.getvalue()


def page_stats(path, header_crop=HEADER_CROP):
    """页面墨迹特征量, 用于快速识别空白页(避免白烧 API)。

    实测(500px 宽缩略图, 灰度):
      空白页 0002/0014 : ink=0.002  gx=2.4
      文字页 0003/0104  : ink=0.11+  gx=13+
    gx = 水平方向平均梯度 = 文字笔画密度, 区分度最好。
    ink = 暗像素(<110)占比。
    """
    import numpy as np
    im = Image.open(path).convert("L")
    W, H = im.size
    c = im.crop((0, int(H * header_crop), W, H))
    c = c.resize((500, max(1, int(500 * (H * (1 - header_crop)) / W))), Image.LANCZOS)
    a = np.asarray(c).astype(float)
    ink = float((a < 110).mean())
    gx = float(np.abs(np.diff(a, axis=1)).mean())
    return ink, gx


BLANK_GX = 2.8      # gx 低于此值 -> 判为空白页
BLANK_INK = 0.01    # ink 低于此值 -> 判为空白页


def is_blank_page(path):
    """空白页判定: 梯度极低 且 几乎无墨迹。两个条件同时满足才算空白。"""
    try:
        ink, gx = page_stats(path)
    except Exception:
        return False
    return gx < BLANK_GX and ink < BLANK_INK


# ---------------- API 调用 ----------------
PREAMBLE_RE = re.compile(
    r"^\s*(?:"
    r"(?:图像|图片|影像|照片|扫描件|扫描页|这张图|该图|本图)[^。\n]{0,12}?"
    r"(?:文字|文本|内容|字符)[^。\n]{0,8}?(?:如下|为|是)?[：:]?"
    r"|(?:以下|如下)(?:是|为)?(?:图片|图像|扫描页)[^。\n]{0,10}?"
    r"(?:中)?(?:的)?(?:文字|内容|文本)?[：:]?"
    r"|(?:OCR|识别|转写|提取)(?:结果|内容)?[：:]?"
    r"|(?:识别|转写|提取)出(?:的)?(?:文字|内容)?[：:]?"
    r")\s*", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?", re.M)
# M3 模型的思维链块
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S | re.IGNORECASE)
THINK_OPEN_RE = re.compile(r"^.*?<think>.*?</think>\s*", re.S | re.IGNORECASE)
# 模型拒识/空页的元话术
META_RE = re.compile(
    r"(无法识别|无法进行\s*OCR|没有任何文字|没有文字内容|一片空白|不包含任何文字|"
    r"无法提供|抱歉|请上传|请提供图片|没有检测到|未检测到|图片模糊|无法读取)")


def clean_raw(txt):
    """清掉模型的前言/代码围栏/思维链, 只留正文。"""
    if not txt:
        return ""
    t = txt.strip()
    # 思维链 (M3)
    if "</think>" in t:
        t = THINK_RE.sub("", t)
        t = re.sub(r"<think>.*$", "", t, flags=re.S | re.IGNORECASE)
    # 代码围栏: 取第一对围栏内的内容
    if t.startswith("```"):
        t = FENCE_RE.sub("", t)
        t = t.strip()
        if t.endswith("```"):
            t = t[:-3].strip()
    # 前言行 (可能多行, 逐行剥)
    for _ in range(3):
        t2 = PREAMBLE_RE.sub("", t, count=1).lstrip()
        if t2 == t:
            break
        t = t2
    if t.startswith("```"):
        t = FENCE_RE.sub("", t).strip()
        if t.endswith("```"):
            t = t[:-3].strip()
    return t.strip()


def is_meta_response(t):
    """模型返回的是元话术而不是 OCR 正文 -> 需要重试。

    注意: 短内容不等于元话术。某些页正文极少(如版权页上的"上海译文出版社"),
    只要不含元话术关键词就算有效 OCR 结果。
    判据只看**整段**: 若整段都是元话术 -> 拒识; 若元话术只出现在开头
    且后面还有正文, 视为"前言+正文", 剥掉前言后接受。
    """
    if not t or not t.strip():
        return True
    stripped = t.strip()
    # 整段都是元话术 -> 拒识
    if META_RE.search(stripped) and len(stripped) < 300:
        # 若剥掉元话术句子后还剩实质内容, 不算拒识
        rest = META_SENT_RE.sub("", stripped).strip()
        if len(rest) < 8:
            return True
    # 剥掉前言后没剩下东西 -> 前言式空响应
    if PREAMBLE_RE.match(t) and not PREAMBLE_RE.sub("", t, count=1).strip():
        return True
    return False


# 含元话术的整句
META_SENT_RE = re.compile(
    r"[^\n。！？]*"
    r"(无法识别|无法进行\s*OCR|没有任何文字|没有文字内容|一片空白|不包含任何文字|"
    r"无法提供|抱歉|请上传|请提供图片|没有检测到|未检测到|图片模糊|无法读取)"
    r"[^\n。！？]*[。！？]?")


def ocr_bytes(img_bytes, model=MODEL, prompt=None, max_tokens=MAX_TOKENS):
    if prompt is None:
        prompt = (
            "请对这张中文书籍扫描页做逐字OCR转写，直接输出识别到的文字内容，不要任何解释。"
            "保留原有的段落划分。表格请用Markdown表格格式输出。"
            "页眉、页码、装饰性符号（>>> <<< 等）不要输出。"
        )
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()}},
            ],
        }],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


# 备用提示词: 主提示词被拒识时换一个问法
ALT_PROMPTS = [
    "把图片里的中文内容逐字转写出来。只输出文字本身，不要写“图像中的文字如下”这类开场白，不要用代码块。",
    "请阅读这张扫描页并输出页面上的全部文字内容（纯文本，按原版面换行）。不要任何说明。",
]


def ocr_with_retry(path, model=MODEL):
    """带质量门的 OCR: 空响应/元话术/拒识 -> 换提示词重试, 最后降级换模型。"""
    last = ""
    img = None
    for attempt in range(MAX_RETRY):
        try:
            if img is None:
                img = prep_image(path)
            prompt = None if attempt == 0 else ALT_PROMPTS[(attempt - 1) % len(ALT_PROMPTS)]
            txt = clean_raw(ocr_bytes(img, model=model, prompt=prompt))
            if not is_meta_response(txt):
                return txt, None
            last = "meta_response:" + txt[:80]
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            # 422/413 等与图片体积相关 -> 换更小的尺寸重试
            img = None
        time.sleep(1.5 * (attempt + 1))
    # 全部失败 -> 换模型 M3 再试一轮
    try:
        img = prep_image(path, target_w=1400)
        txt = clean_raw(ocr_bytes(img, model="MiniMax-M3", prompt=ALT_PROMPTS[0]))
        if not is_meta_response(txt):
            return txt, None
        last = "m3_meta:" + txt[:80]
    except Exception as e:  # noqa: BLE001
        last = f"m3 {type(e).__name__}: {e}"
    return None, last


# ---------------- 页眉兜底过滤 ----------------
HEADER_MARK = re.compile(r"(>>>|<<<)")
BOOK_WORDS = "饲料法规文件相关法律法规制度标准目录"


def is_header_line(t):
    """内容级页眉判定: 页眉带 <<< / >>> 或纯页码。"""
    s = t.strip().strip("|").strip()
    if not s:
        return False
    if HEADER_MARK.search(s):
        return True
    core = re.sub(r"[\s　|]", "", s)
    if re.fullmatch(r"[\d\-—―]{1,6}", core):
        return True
    # 形如 "300 | 饲料法规文件 (2023)" / "<<< 二、制度文件 | 301"
    if len(core) <= 45 and any(w in core for w in BOOK_WORDS) and re.search(r"\d{1,4}", core):
        return True
    return False


def strip_headers(lines):
    out = []
    for ln in lines:
        if is_header_line(ln):
            continue
        out.append(ln)
    return out


# ---------------- 结构化 -> Markdown ----------------
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+[章篇]\s*[、.]?\s*(.*)$")
ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+条\s*[、.]?\s*(.*)$")
APPENDIX_RE = re.compile(r"^附\s*录\s*([A-Za-z\d一二三四五六七八九十]+)?\s*[、.]?\s*(.*)$")
DOCNO_RE = re.compile(
    r"^[\u4e00-\u9fa5]{2,14}(令|公告|发|函|号|部令|部公告|办公厅)?\s*"
    r"[\[\〔（(【]?\s*[\d]{4}\s*年?\s*第?\s*[\d]+\s*号?\s*[\]〕）)】]?$")
# 文号形态二: 农办牧〔2019〕32号 / 农办牧[2019]32号 / 国发〔2019〕6号
DOCNO_RE2 = re.compile(
    r"^[\u4e00-\u9fa5]{2,10}\s*[\[\〔（(【]\s*[\d]{4}\s*[\]〕）)】]\s*第?\s*[\d]+\s*号?$")
# 文号形态三: 中华人民共和国农业部令2012年第4号
DOCNO_RE3 = re.compile(
    r"^[\u4e00-\u9fa5]{6,20}(令|公告|令第|公告第)\s*[\d]{4}\s*年\s*第\s*[\d]+\s*号"
    r"(\s*[（(][^）)]{0,120}[)）])?$")
# 文号形态四: 中华人民共和国国务院令2011年第609号 (无"年")
DOCNO_RE4 = re.compile(
    r"^[\u4e00-\u9fa5]{6,20}(令|公告|令第|公告第)\s*[\d]{4}\s*年?\s*第?\s*[\d]+\s*号"
    r"(\s*[（(][^）)]{0,120}[)）])?$")
STDLIST_RE = re.compile(r"^(GB|NY/T|NY|DB\d*|C\s?\d{3,}|SB|T)\s?[\d\.\-—]+$")
BRACKET_TITLE_RE = re.compile(r"^[（(]\s*[一-龥\d]{1,12}\s*[)）]\s*\S")
# 编号条款标题: 4.4.3 外观与物理性状 / 4.5 产品功能 / 4.6.2 产品稳定性试验报告
CLAUSE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\s+(\S.*)$")

# 发文标题特征: 以「的公告/令/通知/办法/规定/方案/意见/公告」等公文尾词结尾,
# 或含书名号/引号的主标题; 不以句读结尾; 长度 6~60。
DOC_TAIL = re.compile(
    r"(公告|通告|令|通知|办法|规定|条例|规程|规则|方案|意见|决定|批复|函|"
    r"细则|规范|目录|说明书|标准|指南|目录)$")


def is_doc_title(s):
    """判断一行是否是发文标题(文件主标题)。"""
    t = s.strip().strip("|").strip()
    if not t or len(t) < 6 or len(t) > 70:
        return False
    if t.endswith(("。", "，", "；", "：", "、", "，")):
        return False
    # 编号项不是标题
    if is_numbered_item(t):
        return False
    if CHAPTER_RE.match(t) or ARTICLE_RE.match(t) or APPENDIX_RE.match(t):
        return False
    if DOC_TAIL.search(t):
        return True
    # 含书名号且较短, 形如《饲料和饲料添加剂管理条例》
    if "《" in t and "》" in t and len(t) <= 40:
        return True
    return False


def is_numbered_item(t):
    return bool(re.match(r"^\s*([(（【\[]\s*[一二三四五六七八九十\d]+\s*[)）】\]]|"
                         r"[一二三四五六七八九十]+\s*[、．.]|"
                         r"\d+\s*[、．.]|"
                         r"[（(][一二三四五六七八九十\d]+[)）])", t))


def is_clause_title(title):
    """判断编号后面跟的文字是不是条款标题(而不是正文)。

    条款标题特征: 短(<=30字)、不以句读结尾、无顿号。
    正文如 "4.4.3 固态产品应提供颜色、气味、粒径分布..." 会含顿号/逗号 -> 排除。
    """
    t = title.strip()
    if not t or len(t) > 30:
        return False
    if t.endswith(("。", "，", "、", "；", "：", ")", "）")):
        return False
    if re.search(r"[，、；：。]", t):
        return False
    return True


def is_standalone_line(s):
    """判断一行是否是独立成段的短行(落款机构名 / 日期 / 短小标题)。

    特征: 长度短、无句读结尾、不是编号项、不是章节条。
    """
    t = s.strip().strip("|").strip()
    if not t or len(t) > 25:
        return False
    if t.endswith(("。", "，", "、", "；", "：", "）", "）", "？", "！", "!", "?")):
        return False
    if is_numbered_item(t):
        return False
    if CHAPTER_RE.match(t) or ARTICLE_RE.match(t) or APPENDIX_RE.match(t):
        return False
    # 机构落款: 以「厅/局/部/委/办公室/中心/司」结尾
    if re.search(r"(厅|局|部|委|办公室|中心|公司|司|所|院|署|办)$", t):
        return True
    # 日期: 2019年3月29日
    if re.fullmatch(r"[\d]{4}\s*年\s*[\d]{1,2}\s*月\s*[\d]{1,2}\s*日", t):
        return True
    return False


def classify(line, first_block=False):
    """返回 (kind, rest_text)。kind ∈ {h1, h3, tbl, None}

    h1 = 发文标题(文件标题 / 文号)
    h3 = 第N章 / 第N条 / 附录X
    tbl = 表格行
    None = 普通段落
    """
    s = line.strip()
    s = re.sub(r"^\s*\|", "", s) if s.startswith("|") else s
    s = s.strip().strip("|").strip()
    if not s:
        return None, ""
    if is_header_line(s):
        return None, ""
    # 表格行原样保留
    if line.strip().startswith("|"):
        return "tbl", line.strip()
    if APPENDIX_RE.match(s):
        return "h3", s
    if CHAPTER_RE.match(s):
        return "h3", s
    if ARTICLE_RE.match(s):
        return "h3", s
    if STDLIST_RE.match(s):
        return "h1", s
    # 编号条款标题 (4.4.3 外观与物理性状) -> ##
    m = CLAUSE_RE.match(s)
    if m and is_clause_title(m.group(2)):
        return "h2", s
    # 文号: 不单独成标题, 归入前面的发文标题块(后处理合并)
    if (DOCNO_RE.match(s) or DOCNO_RE2.match(s)
            or DOCNO_RE3.match(s) or DOCNO_RE4.match(s)):
        return "docno", s
    # 页面首行: 无句读、长度适中 -> 发文标题
    if first_block and is_doc_title(s):
        return "h1", s
    # 页面首行的「（一）xxx」子标题 -> h1 (参考 Markdown_v2 格式)
    if first_block and BRACKET_TITLE_RE.match(s) and len(s) <= 40:
        return "h1", s
    if BRACKET_TITLE_RE.match(s) and len(s) <= 40:
        return "h3", s
    return None, s


def to_markdown(raw):
    """把 OCR 原始文本转成结构化 Markdown。

    段落切分规则(中文公文/法规排版):
    - 空行 -> 硬断段
    - 行首是编号项(第N条 / 一、 / （一） / 1. / 1、) -> 硬断段
    - 上一行以句末标点收尾(。！？；) -> 断段
    - 其余情况(行尾无句读) -> 视为上一段的换行续接
    """
    lines = [l.rstrip() for l in raw.replace("\r\n", "\n").split("\n")]
    lines = strip_headers(lines)

    blocks = []      # (kind, text)
    buf = []

    def flush():
        if buf:
            blocks.append(("p", "".join(x.strip() for x in buf if x.strip())))
            buf.clear()

    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            flush()
            continue
        kind, rest = classify(ln, first_block=not blocks and not buf)

        if kind == "h1":
            flush()
            blocks.append(("h1", rest))
        elif kind == "h3":
            flush()
            blocks.append(("h3", rest))
        elif kind == "h2":
            flush()
            blocks.append(("h2", rest))
        elif kind == "docno":
            # 文号单独成段(不并入标题), 与 Markdown_v2 参考格式一致
            flush()
            blocks.append(("p", rest))
        elif kind == "tbl":
            if blocks and blocks[-1][0] == "tbl":
                blocks[-1] = ("tbl", blocks[-1][1] + "\n" + rest)
            else:
                flush()
                blocks.append(("tbl", rest))
        else:
            # 断段判定
            if buf:
                prev = buf[-1].rstrip()
                standalone = is_standalone_line(s)
                starts_new = (
                    standalone                          # 短独立行(落款/日期/机构)
                    or is_numbered_item(s)               # 行首编号项
                    or prev.endswith(("。", "！", "？", "；", "!", "?", ";"))
                    or prev.endswith("：")               # 冒号后通常是新段
                )
                if starts_new:
                    flush()
            buf.append(rest)
            # 落款/日期这类独立行: 自己成一个段, 后面的行另起
            if is_standalone_line(rest):
                flush()
    flush()

    out = []
    for kind, txt in blocks:
        if kind == "h1":
            out.append("# " + txt)
            out.append("")
        elif kind == "h3":
            out.append("### " + txt)
            out.append("")
        elif kind == "h2":
            out.append("## " + txt)
            out.append("")
        elif kind == "tbl":
            rows = [r for r in txt.split("\n") if r.strip()]
            # 补齐列数, 保证 Markdown 表格合法
            if len(rows) >= 2:
                ncol = rows[0].count("|") - 1
                fixed = []
                for i, r in enumerate(rows):
                    c = r.count("|") - 1
                    if c < ncol:
                        r = r.rstrip().rstrip("|") + " |" * (ncol - c)
                    fixed.append(r)
                if not re.fullmatch(r"[\s\|:\-]+", fixed[1]):
                    fixed.insert(1, "|" + "---|" * ncol)
                out.extend(fixed)
                out.append("")
            else:
                out.extend(rows)
                out.append("")
        else:
            out.append(txt)
            out.append("")
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


# ---------------- 目录页处理 ----------------
# 目录条目边界: 页码后紧跟新的中文标题 -> 下一条目开始
TOC_BOUND_RE = re.compile(r"(?<=\s)(\d{1,4})(?=\s+[一-鿿（(])")


def split_toc_entries(text):
    """把目录页的扁平文本切成一条条目录项。

    目录模型返回的是一整行: "标题A 文号A 页码A 标题B 文号B 页码B ..."。
    靠"页码 + 空格 + 中文"这个模式切边界。
    """
    cuts = [m.end(1) for m in TOC_BOUND_RE.finditer(text)]
    parts = []
    prev = 0
    for c in cuts:
        p = text[prev:c].strip()
        if p:
            parts.append(p)
        prev = c
    tail = text[prev:].strip()
    if tail:
        parts.append(tail)
    return parts


def toc_entry_to_md(entry):
    """目录项 -> Markdown。标题与文号拆开, 页码保留在末尾。

    目录项形态: "标题 文号 页码"。文号可能在标题后、文号后紧跟页码。
    """
    s = entry.strip()
    if not s:
        return ""
    # 末尾页码
    m = re.search(r"\s(\d{1,4})$", s)
    page = m.group(1) if m else ""
    if m:
        s = s[:m.start()].strip()
    # 抽文号(可在标题后任意位置)。用 finditer 找最长的合法文号, 且不能跨过句读。
    docno = ""
    docno_re = re.compile(
            # 前缀: 机关名 + 令/公告/发/函/号
            r"[一-鿿]{2,12}?(?:令|公告|发|函|号|部令|部公告)"
            # 形态A: 2011年第609号 / 2014年第2号
            r"\s*[\[\〔（(【]?\s*\d{4}\s*年?\s*第\s*\d+\s*号"
            # 形态B: 第2109号 (无年份)
            r"|"
            r"[一-鿿]{2,12}?(?:令|公告|发|函|号|部令|部公告)"
            r"\s*第\s*\d{2,5}\s*号"
            # 形态C: 〔2015〕第144号 / [2015]144号
            r"|"
            r"[一-鿿]{2,12}?(?:令|公告|发|函|号|部令|部公告)"
            r"\s*[\[\〔（(【]\s*\d{4}\s*[\]〕）)】]\s*第?\s*\d{2,5}\s*号"
            r"\s*[\]〕）)】]?")
    best = None
    for cand in docno_re.finditer(s):
        # 前面不能有明显的标题分隔符(逗号/冒号)
        if best is None or (cand.end() - cand.start()) > (best.end() - best.start()):
            best = cand
    if best:
        docno = best.group(0).strip()
        s = (s[:best.start()] + " " + s[best.end():]).strip()
    title = re.sub(r"\s{2,}", " ", s).strip()
    if not title:
        return ""
    out = []
    out.append("### " + title)
    out.append("")
    bits = " ".join(x for x in (docno, page) if x)
    if bits:
        out.append(bits)
        out.append("")
    return "\n".join(out)


def is_toc_page(rel_path):
    """目录页判定: 路径里含 '001目录'。"""
    return "001目录" in rel_path.replace("\\", "/")


# ---------------- 任务枚举 ----------------
def enumerate_tasks(src_root):
    tasks = []
    for dp, _, fs in os.walk(src_root):
        for f in sorted(fs):
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                tasks.append((dp, f))
    tasks.sort(key=lambda t: (t[0], t[1]))
    return tasks


def load_progress():
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_progress(d):
    tmp = PROGRESS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PROGRESS)


def run_one(src_dir, fname, rel):
    dst_dir = os.path.join(DST_ROOT, os.path.relpath(src_dir, SRC_ROOT))
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.splitext(fname)[0] + ".md")
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return ("SKIP", rel, 0, "")
    src = os.path.join(src_dir, fname)
    t0 = time.time()
    # 空白页: 快速判定, 直接写空文件, 不烧 API
    if is_blank_page(src):
        with open(dst, "w", encoding="utf-8") as f:
            f.write("")
        return ("BLANK", rel, time.time() - t0, "")
    raw, err = ocr_with_retry(src)
    if raw is None:
        return ("ERR", rel, time.time() - t0, err or "")
    if is_toc_page(rel):
        # 目录页: 扁平文本 -> 逐条目录项
        entries = split_toc_entries(raw.replace("\n", " "))
        chunks = [toc_entry_to_md(e) for e in entries]
        md = "\n".join(c for c in chunks if c)
        md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    else:
        md = to_markdown(raw)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(md)
    return ("OK", rel, time.time() - t0, "")


def stratified_sample(tasks, per_dir=8, src_root=SRC_ROOT):
    """分层抽样: 每个目录取首/中/尾共 per_dir 张, 保证样本覆盖所有页型。"""
    from collections import defaultdict
    by_dir = defaultdict(list)
    for dp, f in tasks:
        by_dir[os.path.relpath(dp, src_root).replace("\\", "/")].append((dp, f))
    picked = []
    for d, lst in sorted(by_dir.items()):
        n = min(len(lst), per_dir)
        if len(lst) <= n:
            picked += lst
        else:
            step = len(lst) / n
            picked += [lst[int(i * step)] for i in range(n)]
    return picked


def main():
    global SRC_ROOT, DST_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="只跑前 N 张(验收)")
    ap.add_argument("--stratified", type=int, default=0,
                    help="分层抽样: 每个目录取 N 张(覆盖所有页型)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--src", default=SRC_ROOT)
    ap.add_argument("--dst", default=DST_ROOT)
    args = ap.parse_args()

    SRC_ROOT = args.src
    DST_ROOT = args.dst

    tasks = enumerate_tasks(SRC_ROOT)
    if args.stratified:
        tasks = stratified_sample(tasks, args.stratified, SRC_ROOT)
    elif args.sample:
        # 均匀抽样, 覆盖各目录(不能只取前 N, 前 N 全是封面)
        if len(tasks) <= args.sample:
            pass
        else:
            step = len(tasks) / args.sample
            tasks = [tasks[int(i * step)] for i in range(args.sample)]
    print(f"[scan] {len(tasks)} 张待处理", flush=True)

    prog = load_progress()
    done = 0
    ok = skip = err = blank = 0
    t0 = time.time()
    results = []

    def work(t):
        dp, f = t
        rel = os.path.relpath(os.path.join(dp, f), SRC_ROOT).replace("\\", "/")
        st, rel, dt, e = run_one(dp, f, rel)
        with _lock:
            prog[rel] = {"status": st, "ts": time.time()}
            save_progress(prog)
        return st, rel, dt, e

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, t) for t in tasks]
        for i, fu in enumerate(futs, 1):
            st, rel, dt, e = fu.result()
            done += 1
            if st == "OK":
                ok += 1
            elif st == "SKIP":
                skip += 1
            elif st == "BLANK":
                blank += 1
            else:
                err += 1
                print(f"  ERR {rel}: {e}", flush=True)
            if i % 20 == 0 or i == len(futs):
                el = time.time() - t0
                rate = done / max(el, 1e-6)
                print(f"  {i}/{len(futs)} ok={ok} skip={skip} blank={blank} err={err} "
                      f"{el/60:.1f}min rate={rate*60:.1f}/min "
                      f"eta={(len(futs)-i)/max(rate,1e-6)/60:.0f}min", flush=True)

    print(f"[done] ok={ok} skip={skip} blank={blank} err={err} total={(time.time()-t0)/60:.1f}min -> {DST_ROOT}")


if __name__ == "__main__":
    main()
