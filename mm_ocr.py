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
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

# ---------------- 路径 ----------------
# 源图目录: 拆好的单页图。
# 这个目录被挪过位置(Images_split/ -> back/Images_split/), 所以自动探测,
# 别写死路径。
_SRC_CANDIDATES = (
    r"E:/workspace/siliao/Images_split",
    r"E:/workspace/siliao/back/Images_split",
)


def _find_src_root():
    for p in _SRC_CANDIDATES:
        if os.path.isdir(p) and any(
                f.lower().endswith(".jpg") for _, _, fs in os.walk(p) for f in fs):
            return p
    return _SRC_CANDIDATES[0]


SRC_ROOT = _find_src_root()
DST_ROOT = r"E:/workspace/siliao/minimax"
PROGRESS = r"E:/workspace/siliao/.mm_ocr_progress.json"

# ---------------- API ----------------
API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
# 兜底模型: Text-01 的内容审核更严, 少数页被判 sensitive 时 M3 能过。
FALLBACK_MODEL = "MiniMax-M3"
MAX_TOKENS = 8000
TIMEOUT = 300
MAX_RETRY = 3

# ---------------- 图像参数 ----------------
TARGET_W = 1600        # 超过这个宽度模型会拒识
# 顶部页眉带裁掉比例。
# 实测(30 页抽样, 行墨迹剖面): 页眉行占页高 0.2%~5.4%, 正文最早在 6% 之后。
# 文件大标题(居中大字)在 9%~11%, 所以裁 13% 会把标题切掉 -> 必须用 6%。
HEADER_CROP = 0.06
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
# 局部对比度: 页面文字与背景的残差绝对值均值。
# 实测: 正常页 8.9~26, 幻觉页(扫描发白) 4.3~6.5。
LOW_CONTRAST = 7.0


def local_contrast(path, header_crop=HEADER_CROP):
    """局部对比度 = 页面图 减去 高斯模糊背景 的残差绝对值均值。

    扫描发白/褪色的页面, 文字几乎看不见, 模型会**编造**内容。
    这个指标把这种页筛出来, 走交叉校验流程。
    """
    import numpy as np
    from PIL import ImageFilter
    im = Image.open(path).convert("L")
    W, H = im.size
    c = im.crop((0, int(H * header_crop), W, H))
    c = c.resize((400, max(1, int(400 * (H * (1 - header_crop)) / W))), Image.LANCZOS)
    bg = c.filter(ImageFilter.GaussianBlur(10))
    r = np.asarray(c).astype(float) - np.asarray(bg).astype(float)
    return float(np.abs(r).mean())


def is_low_contrast(path):
    try:
        return local_contrast(path) < LOW_CONTRAST
    except Exception:
        return False


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
    # 退化输出: 模型在表单/密集表格页上会吐一长串空单元格("|  |  |  | ...")
    # 撞满 max_tokens 后截断, 结果是一堆 "|", 没有任何文字。
    if is_degenerate(t):
        return True
    return False


# 退化输出判定: 表格单元格占比过高 & 实质文字极少
DEGENERATE_MIN_LEN = 400


def is_degenerate(t):
    """是不是"一长串空表格单元格"的退化输出。

    实测: 表单页(试验概述表)模型会吐 "|  |  |  | ..." 直到撞满 max_tokens,
    结果 12000 字符全是 "|" 和空格, 只有开头一两句有字。

    判据: 拆成单元格后, 空单元格占比 > 70% 且文本量远小于表格规模 -> 退化。
    比"竖线字符占比"更准(实测退化样本竖线占比只有 0.33, 用字符数判会漏)。
    """
    s = t.strip()
    if len(s) < DEGENERATE_MIN_LEN:
        return False
    # 按竖线拆单元格(保留空单元格, 它们才是退化信号)
    cells = [c.strip() for c in re.split(r"[|｜]", s)]
    nonempty = [c for c in cells if c]
    # 单元格总数多, 而空单元格占绝大多数 -> 退化
    if len(cells) >= 20 and len(nonempty) < len(cells) * 0.3:
        return True
    # 实质文字极少
    real = re.sub(r"[\s|｜\-:：]", "", s)
    if len(real) < 20:
        return True
    # 竖线占比过高
    if s.count("|") / max(1, len(s)) > 0.35:
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
# 表单/密集表格页专用: 不要表格, 只要文字, 按"标签: 值"逐行列出
FORM_PROMPT = (
    "这是一页中文表单或表格。请把页面上所有能看清的文字标签逐行列出来, "
    "格式为「标签 内容」, 一行一个, 不要输出表格竖线, 不要输出空单元格, "
    "不要任何解释说明。"
)


def ocr_with_retry(path, model=MODEL):
    """带质量门的 OCR。

    关键: MiniMax-Text-01 的内容审核比 M3 严格。
    少数页面(政策文件里提到"形式主义/官僚主义"等词的)会被 Text-01 判为
    `input new_sensitive (1026)` 返回 422, 但 M3 可以正常识别。
    所以遇到 422 要**立刻换模型**, 不要在同一个模型上死磕。

    M3 的输出是非确定的(同一张图可能这次给正文、下次给"请上传图片"),
    所以换到 M3 后要多试几次。
    """
    last = ""
    img = None
    m3_tries = 0
    form_tried = False
    for attempt in range(MAX_RETRY + 3):
        try:
            if img is None:
                img = prep_image(path)
            if model == FALLBACK_MODEL:
                m3_tries += 1
                # M3 用强指令提示词, 它默认会反问"请上传图片"
                prompt = ALT_PROMPTS[(m3_tries - 1) % len(ALT_PROMPTS)]
            elif attempt == 0:
                prompt = None
            elif not form_tried:
                # 第二次尝试: 用"只要文字不要表格"的表单提示词
                form_tried = True
                prompt = FORM_PROMPT
            else:
                prompt = ALT_PROMPTS[(attempt - 1) % len(ALT_PROMPTS)]
            txt = clean_raw(ocr_bytes(img, model=model, prompt=prompt))
            if not is_meta_response(txt):
                return txt, None
            last = "meta_response:" + txt[:80]
            img = None   # 重试时换个尺寸, 增加多样性
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            last = f"HTTP{e.code}:{body}"
            img = None
            # 审核拦截 -> 立刻换模型(Text-01 更严, M3 能过)
            if e.code in (400, 413, 422) and model != FALLBACK_MODEL:
                model = FALLBACK_MODEL
            elif e.code not in (400, 413, 422):
                pass
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            img = None
        time.sleep(1.5 * (attempt + 1))
    return None, last


# ---------------- 页眉兜底过滤 ----------------
HEADER_MARK = re.compile(r"(>>>|<<<)")
BOOK_WORDS = (
    "饲料法规文件", "相关法律法规", "法律法规文件", "制度文件",
    "标准及标准目录", "标准目录", "法规文件",
)


def is_header_line(t):
    """内容级页眉判定。

    页眉形态(实测):
      "116 | 饲料法规文件 (2023) >>>"
      "<<< 二、制度文件 | 301"
      "300 | 饲料法规文件（2023）"
    判据(从严):
      1. 含 >>> / <<<
      2. 整行就是纯页码
      3. 行首是纯页码, 且行内含书名关键词
    坑: 不要用"整行含书名关键词 + 含数字"这种宽松判据 ——
    正文里 "2.2 产品是否符合相关法律法规、产业政策的要求。" 会被误判成页眉
    (含"相关法律法规" + 含数字"2.2"), 导致整行被丢弃。
    """
    s = t.strip().strip("|").strip("｜").strip()
    if not s:
        return False
    if HEADER_MARK.search(s):
        return True
    core = re.sub(r"[\s　|｜]", "", s)
    if re.fullmatch(r"[\d\-—―]{1,6}", core):
        return True
    # 行首是页码 + 行内含书名关键词 -> 页眉
    m = re.match(r"^(\d{1,4})(?=[\s　|｜（(])", s)
    if m and any(w in core for w in BOOK_WORDS):
        return True
    return False


def strip_headers(lines):
    out = []
    for ln in lines:
        if is_header_line(ln):
            continue
        out.append(ln)
    return out


# ---------------- 空格归一化 ----------------
# 模型会把排版上的字间距转写成空格: "编 委 会" "目 录" "前 言" "2014 年 第 1 号"。
# 中文之间的空格一律去掉; 中英文/数字之间的空格保留(有意义)。
CJK = r"一-鿿㐀-䶿　-〿＀-￯"
SPACE_BETWEEN_CJK_RE = re.compile(r"(?<=[%s])[ \t　]+(?=[%s])" % (CJK, CJK))
SPACE_CJK_DIGIT_RE = re.compile(r"(?<=[%s])[ \t　]+(?=[0-9])" % CJK)
SPACE_DIGIT_CJK_RE = re.compile(r"(?<=[0-9])[ \t　]+(?=[%s])" % CJK)


MARK_SP_RE = re.compile(r"(?<![0-9])(第[一二三四五六七八九十百零〇\d]+[章节条])"
                        r"(\s*)")
# 编号条款: "4.4.3 外观与物理性状" —— 编号后保留一个空格
# 两侧都不能是数字/字母: 否则 "2014 年第1号" 里的 "20" 会被误当编号条款。
CLAUSE_SP_RE = re.compile(r"(?<![\w.．。])(\d{1,2}(?:\.\d{1,2}){0,3})(?!\d)(?!\.\d)\s*(\S)")


def normalize_spaces(text):
    """去掉中文排版字间距, 保留中英文/数字间有意义的空格。

    章节条标记后保留一个空格("第一章 总则"), 编号条款后保留一个空格
    ("4.4.3 外观与物理性状"), 否则标题和正文会粘在一起。
    角空格(U+3000)也算字间距, 一并归一。
    """
    t = text.replace("　", " ")
    t = SPACE_BETWEEN_CJK_RE.sub("", t)
    t = SPACE_CJK_DIGIT_RE.sub("", t)
    t = SPACE_DIGIT_CJK_RE.sub("", t)
    # 章节条标记后补一个空格
    t = MARK_SP_RE.sub(lambda m: m.group(1) + " ", t)
    # 编号条款后补一个空格
    t = CLAUSE_SP_RE.sub(lambda m: m.group(1) + " " + m.group(2), t)
    return t


# 模型偶尔把整页返回成**一行**(无换行), 用双空格/全角空格当分隔。
# 这时不能靠换行切段, 必须**按标题标记切**:
#   "...第九条规定...第十三条 国家对...第三章 生产、经营和使用  第十四条 设立..."
# -> 在 "第十三条"/"第三章"/"第十四条" 前面补换行。
#
# 注意: 不用 lookbehind+lookahead 组合(实测 Python re 在这种嵌套下解析异常),
# 改成"捕获组 + 回调"的方式替换。
FLAT_MARK_RE = re.compile(
    r"(第[一二三四五六七八九十百零〇\d]+[章节条]"
    r"|附\s*录\s*[A-Za-z\d一二三四五六七八九十]"
    r"|[（(]\s*[一-鿿\d]{1,4}\s*[)）])"
)
FLAT_HEAD_RE = re.compile(r"[。；;：:！!？?）\)\s]")
# 标记**后面**跟的角空格(U+3000) 是最可靠的标题信号:
#   "第十三条\u3000国家对..."  -> 第十三条 是标题
#   "依照本条例第九条规定"     -> 第九条 是交叉引用, 不是标题
# 角空格在公文排版里只出现在"条/款/项"的编号后面。
FLAT_MARK_IDEO_RE = re.compile(
    r"(第[一二三四五六七八九十百零〇\d]+[章节条]"
    r"|附\s*录\s*[A-Za-z\d一二三四五六七八九十]"
    r"|[（(]\s*[一-鿿\d]{1,4}\s*[)）])"
    r"\s*　"
)


def split_flat_text(text):
    """把一行到底的 OCR 文本按标题标记切开, 补上换行。

    优先用**角空格**(U+3000)信号 —— 公文排版里角空格只跟在"条/款/项"编号后,
    是最可靠的标题标志。没有角空格时才退回"标记前是句读"的弱规则。
    """
    if "\n" in text.strip():
        return text
    # 双空格是模型给的分隔符
    text = re.sub(r"[ \t]{2,}", "\n", text)
    if "\n" in text:
        return text
    # 还是一行 -> 先按"标记 + 角空格"切(强信号)
    out = []
    last = 0
    for m in FLAT_MARK_IDEO_RE.finditer(text):
        if m.start() == 0:
            continue
        out.append(text[last:m.start()])
        out.append("\n")
        last = m.start()
    out.append(text[last:])
    text = "".join(out)
    if "\n" in text.strip():
        return text
    # 兜底: 按标记切, 但要求标记前是句读/空白(避免切坏交叉引用)
    out = []
    last = 0
    for m in FLAT_MARK_RE.finditer(text):
        if m.start() == 0:
            continue
        prev = text[m.start() - 1]
        if not FLAT_HEAD_RE.fullmatch(prev):
            continue
        out.append(text[last:m.start()])
        out.append("\n")
        last = m.start()
    out.append(text[last:])
    return "".join(out)


# ---------------- 结构化 -> Markdown ----------------
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+[章篇]\s*[、.]?\s*(.*)$")
ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百零〇\d]+条\s*[、.]?\s*(.*)$")
APPENDIX_RE = re.compile(r"^附\s*录\s*([A-Za-z\d一二三四五六七八九十]+)?\s*[、.]?\s*(.*)$")
# 层级(用户指定): 第N章 -> ##, 第N条 -> ###, 附录X -> ###
# 编号条款 4.4.3 -> ####  (比 章/条 更细)
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
BRACKET_TITLE_RE = re.compile(r"^[（(]\s*[一-鿿\d]{1,12}\s*[)）]\s*\S")
# 「（一）xxx」当标题的前提: 短 + 不以句读结尾。
# 否则 "（一）有与经营饲料相适应的经营场所和仓储设施；" 这种列表项会被误标成标题。
BRACKET_MAX_LEN = 24
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


def is_bracket_title(s):
    """「（一）xxx」是不是标题(而不是列表项)。

    标题: 短(<=24字)、不以句读结尾。
    列表项: "（一）有与经营饲料相适应的经营场所和仓储设施；" -> 以分号结尾, 不是标题。
    """
    t = s.strip().strip("|｜").strip()
    if not t or len(t) > BRACKET_MAX_LEN:
        return False
    if t.endswith(("。", "，", "、", "；", "：", "）", "）", "?", "？", "!", "！")):
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
    """返回 (kind, rest_text)。kind ∈ {h1, h2, h3, h4, tbl, docno, None}

    层级(用户指定):
      h1 = 发文标题(文件主标题)
      h2 = 第N章
      h3 = 第N条 / 附录X
      h4 = 编号条款 (4.4.3 外观与物理性状)
      tbl = 表格行
      docno = 文号(单独成段)
      None = 普通段落
    """
    raw = line.strip()
    # 表格行必须最先判定: 否则 "| 28 | 甘肃... |" 去掉竖线后
    # 会被 CLAUSE_RE 误认成 "28 甘肃..." 条款标题, 变成 "## 28 | 甘肃..."
    if raw.startswith("|"):
        return "tbl", raw
    s = raw.strip()
    if not s:
        return None, ""
    if is_header_line(s):
        return None, ""
    # 模型偶尔自己吐 "#### xxx" / "**xxx**" -> 去掉标记再判定
    s = re.sub(r"^#{1,6}\s+", "", s)
    s = s.strip().strip("|｜").strip()
    if not s:
        return None, ""
    if APPENDIX_RE.match(s):
        return "h3", s
    if CHAPTER_RE.match(s):
        return "h2", s
    if ARTICLE_RE.match(s):
        return "h3", s
    if STDLIST_RE.match(s):
        return "h1", s
    # 编号条款标题 (4.4.3 外观与物理性状) -> ####
    m = CLAUSE_RE.match(s)
    if m and is_clause_title(m.group(2)):
        return "h4", s
    # 文号: 不单独成标题, 归入前面的发文标题块(后处理合并)
    if (DOCNO_RE.match(s) or DOCNO_RE2.match(s)
            or DOCNO_RE3.match(s) or DOCNO_RE4.match(s)):
        return "docno", s
    # 页面首行: 无句读、长度适中 -> 发文标题
    if first_block and is_doc_title(s):
        return "h1", s
    # 「（一）xxx」子标题: 只在页面首行 或 确实是短标题时
    if BRACKET_TITLE_RE.match(s) and is_bracket_title(s):
        return ("h1" if first_block else "h3"), s
    return None, s


def split_heading_text(txt):
    """把标题文本拆成 (标记, 正文)。

    "第一条 为了加强……" -> ("第一条", "为了加强……")
    "第一章 总则"          -> ("第一章", "总则")
    "第三章 生产、经营和使用" -> ("第三章", "生产、经营和使用")
    "（一）新产品审定"      -> ("（一）新产品审定", "")   # 整体是标题
    """
    s = txt.strip()
    m = re.match(
        r"^(第[一二三四五六七八九十百零〇\d]+[章节条]"
        r"|附\s*录\s*[A-Za-z\d一二三四五六七八九十]*)"
        r"\s*(.*)$", s)
    if m:
        head = m.group(1)
        body = m.group(2).strip()
        if body:
            return head, body
        return s, ""
    return s, ""


def out_heading(out, level, txt):
    """输出一个标题。标题标记单独一行, 正文另起一段。"""
    head, body = split_heading_text(txt)
    out.append("#" * level + " " + head)
    out.append("")
    if body:
        out.append(body)
        out.append("")


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
    # 表单提示词会带出一行表头"标签 内容" -> 去掉
    lines = [l for l in lines if l.strip() not in ("标签 内容", "标签 内容：")]
    # 顺序很重要: 先按"标记 + 角空格"切分, 再做空格归一化。
    # 反过来的话, 归一化会把角空格换成 ASCII 空格, 标题信号就丢了。
    lines = split_flat_text("\n".join(lines))
    lines = [normalize_spaces(l) for l in lines.split("\n")]

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
        elif kind == "h4":
            flush()
            blocks.append(("h4", rest))
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
            out_heading(out, 1, txt)
        elif kind == "h2":
            out_heading(out, 2, txt)
        elif kind == "h3":
            out_heading(out, 3, txt)
        elif kind == "h4":
            out_heading(out, 4, txt)
        elif kind == "tbl":
            rows = [r for r in txt.split("\n") if r.strip()]
            # 补齐列数, 保证 Markdown 表格合法
            if len(rows) >= 2:
                # 列数取众数(不是第一行), 第一行可能是空的
                counts = [r.count("|") - 1 for r in rows]
                ncol = Counter(c for c in counts if c > 0).most_common(1)[0][0] if any(
                    c > 0 for c in counts) else 0
                ncol = min(ncol, 30)          # 防列数爆炸
                fixed = []
                for r in rows:
                    c = r.count("|") - 1
                    if c < ncol and c >= 0:
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
    md = re.sub(r"\n{3,}", "\n\n", md)
    # 模型偶尔吐出的残留标记: 5 级以上的标题号 / 代码围栏
    # 注意: 只清 5 级及以上, #### 是我们自己用的合法层级(编号条款)
    md = re.sub(r"^#{5,6}\s+", "", md, flags=re.M)
    md = md.replace("```", "")
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# ---------------- 目录页处理 ----------------
# 目录模型返回有两种形态(实测):
# A) 按行: "(三) 进口登记和出口服务 ....... 208\n"
#          "进口饲料和饲料添加剂登记管理办法\n"
#          "中华人民共和国农业部令 2014年第2号 ....... 208\n"
# B) 扁平一行: "标题A 文号A 页码A 标题B 文号B 页码B ..."
# 统一用**文号锚点**切条目: 每个目录项必有一个文号, 文号前面的文字就是标题。
# 先去掉点引导线。
DOTS_RE = re.compile(r"[.．·…]{2,}\s*")

# 文号锚点(3 类写法)。
# 机关名前缀用**非贪婪**: 长度不定, 贪婪会一路吞到上一个文号, 把整段目录并成一条。
# 编号部分 3 种:
#   2011年第609号 / 2014年第2号   (带年份)
#   第1519号 / 第20号             (只有序号)
#   〔2023〕1号 / 〔2015〕144号    (年份在括号里)
DOCNO_ANCHOR_RE = re.compile(
    r"[\u4e00-\u9fa5]{1,14}?(?:令|公告|发|函|号|部令|部公告)"
    r"\s*(?:"
    r"[\[\〔（(【]?\s*\d{4}\s*年?\s*第\s*\d{1,5}\s*号"          # 2011年第609号
    r"|"
    r"第\s*\d{1,5}\s*号"                                        # 第1519号
    r"|"
    r"[\[\〔（(【]\s*\d{4}\s*[\]〕）)】]\s*第?\s*\d{1,5}\s*号"   # 〔2023〕1号
    r")\s*[\]〕）)】]?"
    r"|"
    r"[\u4e00-\u9fa5]{1,8}?\s*〔\s*\d{4}\s*〕\s*第?\s*\d{1,4}\s*号"  # 农办牧〔2023〕1号
)


def _split_docno_anchors(text):
    """按文号锚点切目录条目。

    返回 [{"title":..., "docno":..., "page":...}, ...]
    文号锚点之前的那段文字是标题; 之后紧跟的数字是页码。
    标题段里如果嵌着「（一）xxx 250」这种章节标题, 拆成独立的章节条目。
    """
    ms = list(DOCNO_ANCHOR_RE.finditer(text))
    entries = []

    def emit_title_chunk(chunk):
        """把标题段里的章节标题拆出来。

        形态: "（五）宠物饲料管理 363 关于宠物饲料管理的公告"
              -> 章节条目「（五）宠物饲料管理 363」+ 文件标题「关于宠物饲料管理的公告」
        """
        chunk = chunk.strip()
        if not chunk:
            return
        # 章节标题: 「（一）xxx <页码>」, 可能出现在标题段任意位置
        m = re.search(r"[（(]\s*([一-鿿\d]{1,4})\s*[)）]\s*(.+?)\s+(\d{1,4})(?=\s|$)", chunk)
        if m:
            head = chunk[:m.start()].strip()
            rest = chunk[m.end():].strip()
            if head:
                entries.append({"title": head, "docno": "", "page": ""})
            entries.append({"title": f"（{m.group(1)}）{m.group(2)}".strip(),
                            "docno": "", "page": m.group(3)})
            if rest:
                emit_title_chunk(rest)
            return
        entries.append({"title": chunk, "docno": "", "page": ""})

    for i, m in enumerate(ms):
        docno = m.group(0).strip()
        # 标题 = 上一个文号之后的页码之后(到本文号之前)
        start = ms[i - 1].end() if i > 0 else 0
        head = text[start:m.start()].strip()
        # 页码: 文号之后紧跟的数字
        after = text[m.end():]
        pm = re.match(r"\s*(\d{1,4})", after)
        page = pm.group(1) if pm else ""
        # 去掉上一页码
        head = re.sub(r"^\s*\d{1,4}\s*", "", head).strip()
        if head:
            emit_title_chunk(head)
        entries.append({"title": "", "docno": docno, "page": page})
    # 尾部(没有文号的残留): 一般是章节标题+页码
    if ms:
        tail = text[ms[-1].end():].strip()
        tail = re.sub(r"^\s*\d{1,4}\s*", "", tail).strip()
        tm = re.search(r"^(.*?)\s*(\d{1,4})$", tail)
        if tm and tm.group(1).strip():
            emit_title_chunk(tm.group(1).strip())
            # 页码挂在最后那个章节条目上
            for e in reversed(entries):
                if not e["page"]:
                    e["page"] = tm.group(2)
                    break
    return entries


def split_toc_entries(text):
    """把目录页文本切成一条条目录项。兼容"按行"和"扁平一行"两种形态。"""
    text = DOTS_RE.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [l.strip() for l in re.split(r"[\n\r]+", text) if l.strip()]
    # 形态A: 有多行 -> 按行处理, 标题行与文号行配对
    if len(lines) > 2:
        out = []
        pending = ""
        for ln in lines:
            m = re.search(r"(?:^|\s)(\d{1,4})$", ln)
            if m and DOCNO_ANCHOR_RE.fullmatch(ln[:m.start()].strip()):
                page = m.group(1)
                docno = ln[:m.start()].strip()
                if pending:
                    out.append({"title": pending, "docno": docno, "page": page})
                    pending = ""
                else:
                    out.append({"title": "", "docno": docno, "page": page})
            elif m and not DOCNO_ANCHOR_RE.search(ln):
                # 章节标题 + 页码
                title = ln[:m.start()].strip()
                page = m.group(1)
                if pending:
                    out.append({"title": pending, "docno": "", "page": ""})
                    pending = ""
                out.append({"title": title, "docno": "", "page": page})
            else:
                if pending:
                    out.append({"title": pending, "docno": "", "page": ""})
                pending = ln
        if pending:
            out.append({"title": pending, "docno": "", "page": ""})
        if out:
            return out
    # 形态B: 扁平一行 -> 按文号锚点切
    return _split_docno_anchors(text)


def toc_entry_to_md(entry):
    """目录项 dict -> Markdown。标题 / 文号 / 页码 分行。

    条目序列里, 标题条目后面可能跟着一个只有文号的条目 —— 它们是一组,
    合并渲染成 "### 标题\\n\\n文号 页码"。
    """
    if isinstance(entry, dict):
        title = normalize_spaces(entry.get("title", "")).strip()
        docno = normalize_spaces(entry.get("docno", "")).strip()
        page = entry.get("page", "")
    else:
        s = entry.strip()
        if not s:
            return ""
        m = re.search(r"(?:^|\s)(\d{1,4})$", s)
        page = m.group(1) if m else ""
        if m:
            s = s[:m.start()].strip()
        s = normalize_spaces(s)
        title, docno = s, ""
    if not title and not docno:
        return ""
    out = []
    if title:
        out.append("### " + title)
        out.append("")
    bits = " ".join(x for x in (docno, page) if x)
    if bits:
        out.append(bits)
        out.append("")
    return "\n".join(out)


def toc_entries_to_md(entries):
    """条目序列 -> Markdown 文本。标题条目与其后的文号条目合并成一项。"""
    chunks = []
    pending_title = ""
    for e in entries:
        if isinstance(e, dict) and e.get("docno") and not e.get("title"):
            # 文号条目 -> 并到上一个标题
            bits = " ".join(x for x in (normalize_spaces(e["docno"]).strip(), e.get("page", "")) if x)
            if pending_title:
                chunks.append("### " + pending_title + "\n\n" + bits + "\n")
                pending_title = ""
            else:
                chunks.append(bits + "\n")
        else:
            if pending_title:
                chunks.append("### " + pending_title + "\n")
            t = normalize_spaces(e.get("title", "")).strip() if isinstance(e, dict) else str(e)
            p = e.get("page", "") if isinstance(e, dict) else ""
            pending_title = (t + " " + p).strip() if p else t
    if pending_title:
        chunks.append("### " + pending_title + "\n")
    return "\n".join(chunks)


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


RAW_CACHE = r"E:/workspace/siliao/.mm_raw_cache"


def raw_cache_path(rel):
    """原始 OCR 文本的本地缓存(按相对路径)。改格式时不用重烧 API。"""
    return os.path.join(RAW_CACHE, os.path.splitext(rel.replace("/", os.sep))[0] + ".txt")


def cross_check_low_contrast(path, text01):
    """低对比度页的幻觉防护。

    背景: 扫描发白的页面文字几乎看不见, MiniMax-Text-01 会**编造**内容
    (实测同一张图两次跑出两篇完全不同的"新闻通稿"), 而 MiniMax-M3
    在同样的图上会返回空 —— M3 更保守, 读不出来就说读不出来。

    策略: 对低对比度页, 用 M3 独立跑一遍:
      - M3 也有内容 -> 两边都有, 用 M3 的(更保守的模型, 更可能是真读出来的)
      - M3 为空     -> Text-01 那份很可能是幻觉, 不输出正文, 标注为待人工复核
      - M3 报错     -> 保留 Text-01 的, 但标注低置信
    """
    if not is_low_contrast(path):
        return text01, None
    try:
        img = prep_image(path, target_w=1400)
        m3 = clean_raw(ocr_bytes(img, model=FALLBACK_MODEL, prompt=ALT_PROMPTS[0]))
    except Exception as e:  # noqa: BLE001
        return text01, f"low_contrast_m3_error:{type(e).__name__}"
    if m3 and m3.strip():
        return m3, "low_contrast_m3_used"
    if not text01 or not text01.strip():
        return "", "low_contrast_both_empty"
    # Text-01 有内容而 M3 读不出来 -> 高度怀疑幻觉
    return "", "low_contrast_hallucination_suspected"


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
    # 低对比度页: 用 M3 交叉校验, 防幻觉
    raw, xflag = cross_check_low_contrast(src, raw)
    # 缓存原始 OCR, 以后改格式不用重烧 API
    cp = raw_cache_path(rel)
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    with open(cp, "w", encoding="utf-8") as f:
        f.write(raw)
    if is_toc_page(rel):
        # 目录页: 扁平文本 -> 逐条目录项
        entries = split_toc_entries(raw.replace("\n", " "))
        md = toc_entries_to_md(entries)
        md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
        # 目录解析不出条目(比如前言页/只有章节标题页) -> 回退到正文管线
        if not md.strip():
            md = to_markdown(raw)
    else:
        md = to_markdown(raw)
    md = md.replace("```", "")
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    if xflag and "hallucination" in xflag:
        # 疑似幻觉: 不落正文, 只留标记供人工复核
        md = (f"<!-- OCR 低置信: {xflag} -->\n"
              f"<!-- 原始图: {rel.replace('/', ' / ')} -->\n"
              f"<!-- 扫描对比度过低({local_contrast(src):.2f} < {LOW_CONTRAST}), "
              f"模型输出被判定为幻觉, 已丢弃, 需人工复核或重新扫描 -->\n")
    with open(dst, "w", encoding="utf-8") as f:
        f.write(md)
    return ("OK", rel, time.time() - t0, xflag or "")


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
