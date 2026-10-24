#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格 OCR 修复管线 —— 侧转表格页

【要修的是什么】
minimax 全量重跑后, 204 个表格页里 189 个已是结构完好的 Markdown 表格,
但有 4 个页因为「表格在页面内部被旋转 90 度印刷」(附录D 那种竖排表),
模型读不出来 -> 只吐表头行 -> 后处理补成几千行空单元格。
另有 3 个页是**真正的空白表单**(表4 检验仪器明细表), 输出虽然冗长但内容正确。

【根因与对策】
根因: 模型读不出侧转的表格。
对策: **把图旋正再送一次 API**。同一套 MiniMax 管线在正立页上已经能产出
      结构完好的表格(189/204), 旋正后自然也能。
      旋转方向用本地 RapidOCR 的**文本框宽高比中位数**判定(摆正 w/h>>1, 侧转 w/h<1)。

【为什么不用坐标聚类重建表格】
本地 RapidOCR 能读出侧转页的文本框, 但**全局坐标聚类无法区分
「同一单元格内的换行」与「新记录的开始」** —— 这是方法论天花板, 调参解决不了。
实测重建后「物质名 + 含量数值」同行共现率只有 ~40%, 达不到入库标准。
而 VLM 直接读旋正后的图, 行列关系是它自己看出来的。

【用法】
    python _table_repair.py --scan             # 检测哪些页侧转/退化, 不花钱
    python _table_repair.py --repair           # 旋正后重送 API, 写回 minimax/
    python _table_repair.py --repair --dry-run # 只打印
    python _table_repair.py --repair --local   # 不用 API, 用本地坐标聚类(兜底)
"""
import argparse
import base64
import io
import json
import os
import re
import shutil
import sys
import time

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
SPLIT = os.path.join(REPO, "back", "Images_split")
MINIMAX = os.path.join(REPO, "minimax")
CACHE = os.path.join(REPO, ".mm_raw_cache")

# 语料树会被定期重组(按 章/节/文件 分层), 所以**不能**按固定路径找文件,
# 必须按 stem 递归查。源图同理(Images_split 下面是分类/子目录)。
_INDEX = {}


def _build_index():
    """扫描 minimax/ 与 back/Images_split/, 建 stem -> 路径 索引"""
    global _INDEX
    idx = {"md": {}, "img": {}}
    for dp, dns, fns in os.walk(MINIMAX):
        depth = dp[len(MINIMAX):].count(os.sep)
        for fn in fns:
            if fn.endswith(".md"):
                stem = os.path.splitext(fn)[0]
                path = os.path.join(dp, fn)
                # 同名多份时取**层级最深**的那份 —— 重组后旧路径的残留副本是平铺的,
                # 真正在用的是 深/章/节/文件/ 结构里那份。取最深能避开残留副本。
                prev = idx["md"].get(stem)
                if prev is None or depth > prev[1]:
                    idx["md"][stem] = (path, depth)
    for dp, dns, fns in os.walk(SPLIT):
        for fn in fns:
            if fn.lower().endswith(".jpg"):
                idx["img"].setdefault(os.path.splitext(fn)[0], os.path.join(dp, fn))
    _INDEX = idx
    return idx


def find_md(stem):
    """按 stem 找 md。索引可能因语料树重组而失效, 未命中时重建一次。"""
    if not _INDEX:
        _build_index()
    v = _INDEX["md"].get(stem)
    p = v[0] if isinstance(v, tuple) else v
    if p and os.path.exists(p):
        return p
    _build_index()
    v = _INDEX["md"].get(stem)
    return v[0] if isinstance(v, tuple) else v


def find_img(stem):
    if not _INDEX:
        _build_index()
    p = _INDEX["img"].get(stem)
    if p and os.path.exists(p):
        return p
    _build_index()
    return _INDEX["img"].get(stem)

# 侧转判据: 文本框宽高比中位数
ROTATE_RATIO = 0.85
# 退化页(空单元格撑满)的判定
DEGEN_EMPTY_RATIO = 0.5
# 质量门失败时的重试次数 (MiniMax 输出非确定)
RETRY = 4

TABLE_PROMPT = (
    "请把这张中文表格扫描页转写成 Markdown 表格。"
    "要求:\n"
    "1. 第一行是表头, 第二行是 |---|---| 分隔行\n"
    "2. 每一行一条记录, 单元格内容用 | 分隔, 保持原表列顺序\n"
    "3. 单元格内的换行合并成一个单元格, 不要拆成多行\n"
    "4. 合并单元格(纵向)用空单元格表示, 不要向下填充\n"
    "5. 页眉、页码、书名不要输出\n"
    "6. 只输出表格本身, 不要任何解释文字"
)

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def ocr_boxes(img_path):
    engine = get_engine()
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    scale = 1600.0 / W if W > 1600 else 1.0
    if scale != 1.0:
        img = img.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    res, _ = engine(np.asarray(img))
    out = []
    for box, text, score in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if scale != 1.0:
            x0, y0, x1, y1 = x0 / scale, y0 / scale, x1 / scale, y1 / scale
        out.append((x0, y0, x1, y1, text.strip(), float(score)))
    return out


def box_ratio(boxes):
    rs = [((b[2] - b[0]) / (b[3] - b[1])) for b in boxes
          if b[2] - b[0] > 1 and b[3] - b[1] > 1 and len(b[4]) >= 2]
    return float(np.median(rs)) if rs else None


def loop_ratio(txt, n=8):
    """检测「生成循环」: 某 n-gram 反复出现。

    坑 1: 模型的生成循环不是**连续**重复, 而是 n-gram 高频散布,
          所以要找「最高频 n-gram 的总占比」, 不能找「最长连续重复串」。
          实测 0344: '在配合饲料中的' 出现 1972 次, 占全文 84%。
    坑 2: 相邻 n-gram 会重叠计数, 直接 cnt*n/len 会算出 >1 的值(最大 7.98)。
          对策: 按**不重叠**位置统计, 或把结果 clamp 到 1.0。
          这里用「去重叠后该片段的总覆盖字符数 / 全文长度」。
    """
    if len(txt) < n * 2:
        return 0.0
    from collections import Counter
    c = Counter(txt[i:i + n] for i in range(len(txt) - n))
    # 坑: **表格的对齐填充空格**会让 '| 序号 | 标准编号 |' 这类
    # 纯空白+竖线的 n-gram 高频重复, 把修好的表误判成循环。
    # 对策: 跳过「去空白后几乎没有实义字符」的 n-gram。
    c2 = Counter()
    for gram, cnt in c.items():
        solid = re.sub(r"[\s|\-]", "", gram)
        if len(solid) < max(3, n // 2):
            continue
        c2[gram] = cnt
    if not c2:
        return 0.0
    top, cnt = c2.most_common(1)[0]
    # 该 n-gram 的**出现位置**总数(去重叠) x n / 全文长度
    positions = set()
    start = 0
    while True:
        i = txt.find(top, start)
        if i == -1:
            break
        positions.add(i)
        start = i + 1
    return min(1.0, len(positions) * n / len(txt))


def find_degenerate(root=None):
    """找出退化页(空单元格撑满的表格), 返回 stem 列表。

    扫 **minimax/ 成品目录**(要修的就是它), 不是缓存 —— 缓存是原始输出,
    退化是在后处理补空行时产生的, 缓存里看不出来。

    返回 stem 而不是路径: 语料树会被重组, 路径会变, stem 不会。
    """
    root = root or MINIMAX
    out = []
    for dp, dns, fns in os.walk(root):
        for fn in sorted(fns):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            raw = open(p, encoding="utf-8").read()
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            if not lines:
                continue
            # --- 缺陷 1: 生成循环 (模型卡在某 n-gram 上, 撞满 max_tokens) ---
            # 必须在空表格检测**之前**判: 循环页常常是「1 行巨长表格」,
            # 空行率算出来不高, 但内容全是垃圾。
            if len(raw) >= 2000 and loop_ratio(raw) >= 0.45:
                out.append(os.path.splitext(fn)[0])
                continue
            # --- 缺陷 2: 空单元格撑满 ---
            tbl = [l for l in lines if l.startswith("|")]
            if len(tbl) < 3:
                continue
            empty = sum(1 for l in tbl
                        if all(not c.strip() for c in l.strip().strip("|").split("|")))
            if empty / max(1, len(tbl)) >= DEGEN_EMPTY_RATIO:
                out.append(os.path.splitext(fn)[0])
    return out


def classify_degenerate(rel):
    """区分「真空白表单」与「侧转导致模型失败」

    真空白表单: 框少(只有表头), 框比>1 (正立), 含数字的数据框极少
    侧转失败:  框多, 框比<1 (侧转), 含数字的数据框多
    """
    stem = rel
    img = find_img(stem)
    if not img:
        return None
    boxes = ocr_boxes(img)
    r = box_ratio(boxes)
    md = find_md(stem)
    n_rows = 0
    tbl_head_cols = []
    if md and os.path.exists(md):
        tbl = [l.strip() for l in open(md, encoding="utf-8").read().split("\n")
               if l.strip().startswith("|")]
        n_rows = len(tbl)
        if tbl:
            tbl_head_cols = tbl[0].strip().strip("|").split("|")
    # 判据: 本地 OCR 能读出多少「文本行」
    #   真空白表单(表4 检验仪器明细表): 只有表头 -> 行数少(实测 10~14)
    #   有数据但模型失败:              数据行很多 -> 行数多(实测 31~81)
    # 坑: 早先用「含数字的框数」当判据是错的 —— 侧转页的数字被切碎成
    #     单字符框, 数字框少但内容其实都在, 漏判成 BLANK_FORM。
    body = [b for b in boxes
            if b[4] and not re.fullmatch(r"\d{1,4}", b[4])
            and b[4] not in ("饲料法规文件", "制度文件")]
    line_keys = set()
    for b in body:
        line_keys.add(round((b[1] + b[3]) / 2 / 20))
    n_lines = len(line_keys)
    raw_md = open(md, encoding="utf-8").read() if md and os.path.exists(md) else ""
    lr = loop_ratio(raw_md) if raw_md else 0.0
    # 表格列数: 优先用 md 表头行的列数(可靠),
    # OCR 框的 x 聚类只做兜底(实测 0028 的 md 表头 34 列, OCR 只估出 10 列)
    # 坑: **生成循环页**的 md 表头行是垃圾(循环文本被当成一行, 切出几千个"|"),
    #      这时 md 的列数完全不可信, 必须用 OCR 估计。
    n_cols = n_rows and (len(tbl_head_cols) if tbl_head_cols else 0)
    md_is_garbage = (lr >= 0.45) if raw_md else False
    if md_is_garbage or not n_cols or n_cols > 200:
        n_cols = 0
        xs = sorted(b[0] for b in body)
        if xs:
            clusters = 1
            for i in range(1, len(xs)):
                if xs[i] - xs[i - 1] > 60:
                    clusters += 1
            n_cols = clusters
    rotated = (r is not None and r < ROTATE_RATIO)
    if lr >= 0.45 and len(raw_md) >= 2000:
        # 生成循环: 优先按侧转处理(旋正后重送通常能解)
        kind = "ROTATED_FAIL" if rotated else "MODEL_GAVE_UP"
    elif rotated and n_lines >= 20:
        kind = "ROTATED_FAIL"
    elif n_lines >= 20:
        kind = "MODEL_GAVE_UP"      # 正立但有大量内容, 模型没读出来
    elif n_lines >= 15:
        kind = "SUSPECT"            # 边界, 值得重试
    else:
        kind = "BLANK_FORM"         # 真的是空白表单
    return dict(page=rel, kind=kind, ratio=r, n_boxes=len(boxes),
                n_lines=n_lines, n_cols=n_cols, rotated=rotated, img=img,
                loop_ratio=round(lr, 2),
                cat=os.path.basename(os.path.dirname(md)) if md else "",
                stem=stem, n_rows=n_rows, md=md)


# ---------------------------------------------------------------- API 调用
def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=8000, timeout=120):
    """调用 MiniMax API。

    坑: 默认 300s 超时太长 —— 超宽表(34 列)会稳定超时, 一次卡 5 分钟。
    实测把 timeout 降到 120s + 重试, 整体更快且成功率不降。
    """
    import urllib.request
    sys.path.insert(0, REPO)
    import mm_ocr
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/jpeg;base64," +
                           base64.b64encode(img_bytes).decode()}},
            ],
        }],
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        mm_ocr.API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + mm_ocr.API_KEY,
                 "Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def prep_bytes(img, target_w=1600):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=88)
    return o.getvalue()


def strip_empty_rows(txt):
    """去掉表格里的空行。

    实测: 模型在侧转表格页会吐出大量空行(0324 原始输出 526 行里 520 行是空的),
    这是它试图填满整张表的副产物, 不是内容。保留表头 + 实质行即可。
    判定「空行」: 整行单元格全空。
    """
    lines = [l.rstrip() for l in txt.split("\n")]
    out = []
    for l in lines:
        st = l.strip()
        if st.startswith("|"):
            cells = [c.strip() for c in st.strip("|").split("|")]
            if cells and all(not c for c in cells):
                continue          # 空行直接丢
        out.append(l)
    return "\n".join(out)


def fix_header_col_mismatch(txt):
    """修「表头列数 != 数据列数」。

    实测 0094: 表头是 **两级合并表头**(抗菌药物|氨苄西林类|头孢菌素类|... 共 11 列),
    但第二行(细菌|氨苄西林|万古霉素|...)和数据行是 14 列 —— 表头每格跨了 2 个子列。
    Markdown 表无法表达合并单元格, 直接输出会导致列错位。

    对策: 表头列数不足时, **把数据行的第二行(子表头)提上来当表头**,
    并在首行保留原一级表头(补齐到相同列数)。这样两行列数一致, 语义也完整。
    """
    lines = [l.rstrip() for l in txt.split("\n")]
    tbl_idx = [i for i, l in enumerate(lines) if l.strip().startswith("|")]
    if len(tbl_idx) < 4:
        return txt
    def ncols(i):
        return len(lines[i].strip().strip("|").split("|"))
    def is_sep(i):
        s = lines[i].strip()
        return set(s.replace("|", "").replace("-", "").replace(":", "").strip()) == set()

    h0 = tbl_idx[0]
    # 找第一行非分隔行的表头(两级表头时, 第二行表头紧跟其后)
    rest = [i for i in tbl_idx[1:] if not is_sep(i)]
    if not rest:
        return txt
    h1 = rest[0]
    if ncols(h0) == ncols(h1):
        return txt
    # **只有当第二行的内容明显是「表头性质」时才合并**。
    # 坑: 0324 的第一行是表头(通用名称|英文名称|...8列), 第二行是**第一条数据**
    #       (L-抗坏血酸|...8列), 列数不同 -> 不该合并, 合并会把表头和数据粘一起。
    # 判据: 第二行多数单元格是「短标签」且不含数据型特征(数字/百分号/单位)。
    def looks_like_data(cells):
        for c in cells:
            if re.search(r"\d|%|mg/kg|≥|≤|n\.r\.", c):
                return True
        return False

    def looks_like_header(cells):
        # 短, 无句读, 且多数是名词短语
        short = sum(1 for c in cells if 0 < len(c) <= 12)
        return short >= max(2, len(cells) * 0.6)

    c1_cells = [c.strip() for c in lines[h1].strip().strip("|").split("|")]
    if looks_like_data(c1_cells) or not looks_like_header(c1_cells):
        return txt
    # 数据行的列数当准(取后面所有数据行的众数)
    from collections import Counter
    dc = Counter(ncols(i) for i in tbl_idx if i not in (h0, h1) and not is_sep(i))
    if not dc:
        return txt
    target = dc.most_common(1)[0][0]

    # 两级表头合并成一行: 一级表头 + 二级表头 逐列拼接
    c0 = [c.strip() for c in lines[h0].strip().strip("|").split("|")]
    c1 = [c.strip() for c in lines[h1].strip().strip("|").split("|")]
    merged = []
    for i in range(target):
        a = c0[i] if i < len(c0) else ""
        b = c1[i] if i < len(c1) else ""
        merged.append(f"{a}/{b}" if (a and b) else (a or b))
    header_line = "| " + " | ".join(merged) + " |"
    sep_line = "| " + " | ".join(["---"] * target) + " |"

    # 重建: 表头(合并) + 分隔行 + 其余数据行
    # 跳过: h0(一级表头) h1(二级表头) 以及它们之间的分隔行
    skip = {h0, h1}
    for i in tbl_idx:
        if h0 < i < h1 and is_sep(i):
            skip.add(i)
    out = []
    for i, l in enumerate(lines):
        if i == h0:
            out.append(header_line)
            out.append(sep_line)
        elif i in skip:
            continue
        else:
            out.append(l)
    return "\n".join(out)


def trim_blank_form(txt):
    """把「空白表单」的冗余空行裁掉, 只留表头 + 少量结构行。

    实测 0187/0402/0412 是《检验仪器明细表》这类**真空白模板** ——
    模型正确地识别出表头, 但把表格补成了 500+ 行空网格。
    内容没错, 但 500 行空单元格进索引是纯浪费, 还会稀释向量空间。

    对策: 保留 表头 + 分隔行 + 仍有实质内容的行, 空行全删。
    """
    lines = txt.split("\n")
    out = []
    seen_header = False
    for l in lines:
        st = l.strip()
        if not st.startswith("|"):
            out.append(l)
            continue
        cells = [c.strip() for c in st.strip("|").split("|")]
        # 先判空行: 所有单元格 strip 后为空
        # 坑: **不能**用「去掉竖线和横线后 set 为空」当分隔行判据 ——
        #     `|  |  |  |` 去掉竖线后 strip 出来也是空, 会被误当成分隔行保留,
        #     于是 500 行空网格一行都删不掉。
        if all(not c for c in cells):
            continue          # 空行直接丢
        # 真分隔行: 至少有一个单元格, 且内容全是 - 和 :
        is_sep = all(re.fullmatch(r"[-:]+", c) for c in cells if c) and any(cells)
        if is_sep:
            out.append(l)
            continue
        out.append(l)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 表格重建: 用文本框坐标做行列聚类 (本地兜底路线)
# ---------------------------------------------------------------------------
MD_HEADING = re.compile(r"^#{1,6}\s+\S")
HEADER_NOISE = re.compile(
    r"^(\d{1,4}|饲料法规文件|制度文件|动物防疫法|饲料和饲料添加剂管理条例|"
    r"饲料法|法律法规文件|\(20\d\d\)|（20\d\d）)$")


def strip_header_footer(boxes):
    """剔除页眉(页码/书名/年份) —— 它们不是表格内容。"""
    if not boxes:
        return boxes
    ys = [(b[1] + b[3]) / 2 for b in boxes]
    ymin, ymax = min(ys), max(ys)
    span = max(1.0, ymax - ymin)
    out = []
    for b in boxes:
        yc = (b[1] + b[3]) / 2
        rel = (yc - ymin) / span
        txt = b[4].strip()
        if rel < 0.08 and HEADER_NOISE.match(txt):
            continue
        if rel < 0.12 and re.fullmatch(r"\d{1,4}", txt):
            continue
        out.append(b)
    return out


def cluster_rows(boxes, page_h, tol_ratio=0.012):
    """按 y 中心聚类成行。固定比例容差 —— 实测比自适应稳。"""
    items = [(x0, y0, x1, y1, t) for x0, y0, x1, y1, t, s in boxes if t]
    if not items:
        return []
    tol = page_h * tol_ratio
    items.sort(key=lambda b: (b[1] + b[3]) / 2)
    rows, cur = [], [items[0]]
    cur_y = (items[0][1] + items[0][3]) / 2
    for it in items[1:]:
        y = (it[1] + it[3]) / 2
        if abs(y - cur_y) <= tol:
            cur.append(it)
            cur_y = float(np.median([(b[1] + b[3]) / 2 for b in cur]))
        else:
            rows.append(cur)
            cur, cur_y = [it], y
    if cur:
        rows.append(cur)
    return rows


def cluster_cols(rows, page_w, tol_ratio=0.018):
    """按 x 起点聚类成列, 再合并碎片列。"""
    xs = []
    for r in rows:
        for b in r:
            xs.append(b[0])
    if not xs:
        return []
    xs = sorted(xs)
    tol = page_w * tol_ratio
    groups, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= tol:
            cur.append(x)
        else:
            groups.append(cur)
            cur = [x]
    if cur:
        groups.append(cur)
    if len(groups) > 1:
        maxm = max(len(g) for g in groups)
        merged = [groups[0]]
        for g in groups[1:]:
            prev = merged[-1]
            if len(g) < maxm / 3 and (g[0] - prev[-1]) < tol * 2.5:
                prev.extend(g)
            else:
                merged.append(list(g))
        groups = merged
    return [float(np.mean(g)) for g in groups]


def assign_col(x_center, cols):
    return int(np.argmin([abs(x_center - c) for c in cols]))


def merge_wrapped_rows(grid):
    """把「上一行某列有内容、本行该列为空」的续行并入上一行。"""
    if not grid:
        return grid
    out = [list(grid[0])]
    for row in grid[1:]:
        nonempty = sum(1 for c in row if c.strip())
        prev = out[-1]
        prev_nonempty = sum(1 for c in prev if c.strip())
        if nonempty and nonempty <= 2 and prev_nonempty >= 3:
            if row[0].strip():
                out.append(list(row))
            else:
                for i, c in enumerate(row):
                    if c.strip():
                        prev[i] = (prev[i] + c).strip() if prev[i] else c
        else:
            out.append(list(row))
    return out


def build_table(boxes, page_w, page_h):
    """从文本框重建 Markdown 表格(返回 grid, 列位置)"""
    boxes = strip_header_footer(boxes)
    rows = cluster_rows(boxes, page_h)
    if len(rows) < 2:
        return None, None
    cols = cluster_cols(rows, page_w)
    if not cols:
        return None, None
    grid = []
    for r in rows:
        cells = [""] * len(cols)
        for b in r:
            xc = (b[0] + b[2]) / 2
            ci = assign_col(xc, cols)
            cells[ci] = (cells[ci] + " " + b[4]).strip() if cells[ci] else b[4]
        grid.append(cells)
    return merge_wrapped_rows(grid), cols


def local_reconstruct(img_path, rotated):
    """本地 OCR + 坐标聚类重建表格 (API 不可用时的兜底)。

    实测: API 挂掉时, 本地 RapidOCR 对侧转页能读出 20~130 个框,
    重建出 13~25 行 x 4~15 列, **数据是对的**(机构名/化学式/含量规格
    都对上了), 只是行分组有瑕疵(同格内换行会拆行, 表头会碎)。

    局限(方法论天花板): 全局坐标聚类分不清「同格内换行」与「新记录开始」。
    所以本地重建的结果**必须标注为低置信**, 不能和 API 结果同等对待。
    """
    im = Image.open(img_path).convert("RGB")
    if rotated:
        im = im.rotate(-90, expand=True)
    W, H = im.size
    scale = 1600.0 / W if W > 1600 else 1.0
    if scale != 1.0:
        im = im.resize((int(W * scale), int(H * scale)), Image.LANCZOS)
    res, _ = get_engine()(np.asarray(im))
    boxes = []
    for box, text, score in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if scale != 1.0:
            x0, y0, x1, y1 = x0 / scale, y0 / scale, x1 / scale, y1 / scale
        boxes.append((x0, y0, x1, y1, text.strip(), float(score)))
    grid, cols = build_table(boxes, W, H)
    if not grid or not cols:
        return None, None
    return grid, cols


def local_grid_to_md(grid):
    """把本地重建的 grid 转成 Markdown 表格 (标注低置信)"""
    out = []
    for i, row in enumerate(grid):
        cells = [c.replace("|", "／").replace("\n", " ").strip() for c in row]
        out.append("| " + " | ".join(cells) + " |")
        if i == 0:
            out.append("|" + "|".join(["---"] * len(row)) + "|")
    return "\n".join(out)


def table_stats(txt):
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    tbl = [l for l in lines if l.startswith("|")]
    def isempty(l):
        return all(not c.strip() for c in l.strip().strip("|").split("|"))
    real = [l for l in tbl if not isempty(l)]
    ncols = 0
    data_cols = 0
    if tbl:
        from collections import Counter
        ncols = Counter(len(l.split("|")) - 2 for l in tbl).most_common(1)[0][0]
        # 数据行(跳过表头和分隔行)的众数列数
        dcols = Counter(len(l.split("|")) - 2 for l in tbl[2:]) if len(tbl) > 2 else Counter()
        if dcols:
            data_cols = dcols.most_common(1)[0][0]
    return dict(rows=len(tbl), real_rows=len(real), cols=ncols,
                data_cols=data_cols)


def clean(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = re.sub(r"```[a-zA-Z]*\n?", "", txt)
    txt = re.sub(r"\n```\s*$", "", txt)
    txt = re.sub(r"^(图像中的文字如下[：:]?|图片中识别出的文字如下[：:]?|"
                 r"图片里检测到的文字如下[：:]?)\s*", "", txt.strip())
    return txt.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--local", action="store_true", help="用本地坐标聚类, 不调 API")
    ap.add_argument("--no-api", action="store_true",
                    help="跳过 API 直接本地重建 (API 不可用时用, 省掉重试等待)")
    ap.add_argument("--json", default=os.path.join(REPO, "_table_repair_scan.json"))
    args = ap.parse_args()

    _build_index()
    degen = find_degenerate()
    print(f"退化页(空单元格撑满): {len(degen)}")
    if not (args.scan or args.repair):
        for d in degen:
            print("  ", d)
        return 0

    results = []
    print(f"\n{'页':26} {'框比':>6} {'框数':>5} {'文本行':>6} {'循环':>6} {'判定':>14}")
    for rel in degen:
        info = classify_degenerate(rel)
        if not info:
            print(f"{rel:26} 缺源图")
            continue
        print(f"{rel:26} {info['ratio']:6.2f} {info['n_boxes']:5} "
              f"{info['n_lines']:6} {info.get('loop_ratio', 0):6.2f} {info['kind']:>14}")
        results.append(info)

    if not args.repair:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([{k: v for k, v in r.items() if k != "img"}
                       for r in results], f, ensure_ascii=False, indent=1)
        print(f"\n清单: {args.json}")
        return 0

    print("\n" + "=" * 70)
    for info in results:
        if info["kind"] == "BLANK_FORM":
            # 空白表单: 内容正确但有几百行空单元格 -> 裁掉空行, 保留表头
            md = find_md(info["stem"])
            if md and os.path.exists(md):
                t0 = open(md, encoding="utf-8").read()
                head = "\n".join(l for l in t0.split("\n")
                                  if l.startswith("<!--") or not l.strip())
                body = "\n".join(l for l in t0.split("\n")
                                  if not l.startswith("<!--"))
                before = len(t0)
                t1 = head + "\n" + trim_blank_form(body).lstrip("\n")
                if not args.dry_run:
                    shutil.copy2(md, md + ".bak") if os.path.exists(md) else None
                    with open(md, "w", encoding="utf-8") as f:
                        f.write(t1)
                n_before = len([l for l in t0.split("\n") if l.strip().startswith("|")])
                n_after = len([l for l in t1.split("\n") if l.strip().startswith("|")])
                print(f"裁剪 {info['page']}  空白表单 表格行 {n_before} -> {n_after}")
            continue
        # 超宽表(>=25 列)模型稳定超时, 不值得反复重试
        if info.get("n_cols", 0) >= 25:
            print(f"跳过 {info['page']}  超宽表({info['n_cols']}列), 模型读不动")
            continue
        if info["kind"] not in ("ROTATED_FAIL", "MODEL_GAVE_UP", "SUSPECT"):
            print(f"跳过 {info['page']}  ({info['kind']})")
            continue
        img = Image.open(info["img"])
        # -90 是实测正确方向(0324 重建 12 列 vs +90 的 6 列)
        # SINGLE_ROW_FAIL 可能是正立页被模型漏读, 原样重送即可
        rot = img.rotate(-90, expand=True) if info["rotated"] else img
        data = prep_bytes(rot)
        print(f"\n修复 {info['page']}  旋正 {rot.size[0]}x{rot.size[1]}")
        # 质量门: 必须像表格, 有实质数据行, 且表头/数据列数一致
        # 坑: MiniMax 输出**非确定** —— 同一张图这次给完整表、下次只给表头。
        #   所以门禁失败要**重试**, 不能一次不过就放弃。
        txt = None
        st = None
        local_used = False
        attempts = 1 if args.no_api else RETRY
        for attempt in range(1, attempts + 1):
            try:
                raw = clean(api_ocr(data, TABLE_PROMPT, max_tokens=16000, timeout=120))
            except Exception as e:
                print(f"  [尝试{attempt}] API 失败: {e}")
                if args.no_api:
                    break
                continue
            cand = strip_empty_rows(raw)
            if not cand.lstrip().startswith("|"):
                print(f"  [尝试{attempt}] 输出不像表格")
                continue
            cand = fix_header_col_mismatch(cand)
            cst = table_stats(cand)
            if cst["real_rows"] < 3:
                print(f"  [尝试{attempt}] 实质行不足({cst['real_rows']})")
                continue
            if cst["rows"] and cst["real_rows"] / cst["rows"] < 0.5:
                print(f"  [尝试{attempt}] 空行率仍高({cst['real_rows']}/{cst['rows']})")
                continue
            if cst["cols"] and cst["data_cols"] and cst["cols"] != cst["data_cols"]:
                print(f"  [尝试{attempt}] 列数不一致(表头{cst['cols']} vs 数据{cst['data_cols']})")
                continue
            txt, st = cand, cst
            break
        if txt is None:
            # API 不可用/质量门始终不过 -> 退到本地重建(低置信)
            print(f"  API 路径失败, 退到本地重建")
            try:
                grid, cols = local_reconstruct(info["img"], info["rotated"])
            except Exception as e:
                print(f"  本地重建也失败: {e}")
                continue
            if not grid:
                print("  本地重建无结果, 放弃")
                continue
            txt = local_grid_to_md(grid)
            st = table_stats(txt)
            if st["real_rows"] < 3:
                print(f"  本地重建实质行不足({st['real_rows']}), 放弃")
                continue
            local_used = True
        out = find_md(info["stem"])          # 每次重新查(索引可能已失效)
        if not out or not os.path.exists(os.path.dirname(out)):
            print("  找不到目标 md (语料树可能刚被重组), 放弃")
            continue
        if not args.dry_run:
            if os.path.exists(out):
                shutil.copy2(out, out + ".bak")
            with open(out, "w", encoding="utf-8") as f:
                f.write(f"<!-- source: {os.path.relpath(info['img'], REPO).replace(chr(92), '/')} -->\n")
                f.write(f"<!-- repaired: rotated={'yes' if info['rotated'] else 'no'}, "
                        f"method={'local-ocr' if local_used else 'api-minimax'} -->\n\n")
                f.write(txt + "\n")
        print(f"  表格 {st['real_rows']} 实质行 x {st['cols']} 列, "
              f"{'[本地重建, 低置信]' if local_used else '[API]'}, "
              f"已写 {os.path.relpath(out, REPO)}")
        print("  " + txt.split("\n")[0][:170])

    with open(args.json, "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k != "img"} for r in results],
                  f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
