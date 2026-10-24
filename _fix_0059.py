#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0059 的表格部分。

【背景】
0059.md 的 OCR 原文是裸 LaTeX \\begin{longtable}, 后处理把换行也吃掉了,
结果整页挤成 3 行, 表格结构全丢。同 0050/0051 的缺陷类。

【映射】
Images/02制度文件/0059.jpg = 书第 58 页(左) + 第 59 页(右) 的跨页扫描件。
0059.md 是**右半**(第 59 页), 含 4 张表: 表3 牛 / 表4 绵羊 / 表5 山羊 / 表6 家兔。
(左半第 58 页是 6 资料存档 + 附录A + 表1 猪 + 表2 家禽, 不在本任务范围。)

【书脊切分】
几何中线 W//2 = 2236 落在左页表2 内部。实测:
  左页表2 右边框 x≈2180, 右页表3 左边框 x≈2325 -> 切在 2260。

【实测表结构(从图上数出来的, 不是猜的)】
表3 牛 / 表4 绵羊 / 表5 山羊  -> 5 个叶子列
  第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=3) | 最短试验期(rowspan=2)
  第2行: 起始 | 结束日龄 | 结束体重（kg）
表6 家兔 -> 4 个叶子列
  第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=2) | 最短试验期(rowspan=2)
  第2行: 开始 | 结束日龄

【质量门(沿用 0050/0051 实测出来的判据)】
1. 输出含 <table>
2. 实质行 >= 3
3. 每张表的叶子列数 == 预期值(5 或 4)
4. 所有数据行宽度一致
5. 表头 (colspan, rowspan) 形状与实测一致  <- 抓「幽灵列/值左移」的唯一手段
6. 表标题行必须存在
"""
import base64
import io
import json
import os
import re
import sys

from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

SRC = os.path.join(REPO, "Images", "02制度文件", "0059.jpg")
TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
DOC_DIR = os.path.join(REPO, "minimax", "02制度文件", "01_（一）新产品审定",
                       "08_饲料和饲料添加剂畜禽靶动物耐受性评价试验指南（试行）")

CUT_X = 2260          # 书脊实测位置
TARGET_W = 1900
RETRY = 6

# 每张表的预期结构: (表名关键词, 叶子列数, 第1行形状, 第2行形状)
#   第1行形状: [(colspan, rowspan), ...]
#   第2行形状: [(colspan, rowspan), ...]
SPECS = [
    ("表3", 5, [(1, 2), (3, 1), (1, 2)], [(1, 1), (1, 1), (1, 1)],
     ["类别", "试验阶段", "最短试验期"], ["起始", "结束日龄", "结束体重"]),
    ("表4", 5, [(1, 2), (3, 1), (1, 2)], [(1, 1), (1, 1), (1, 1)],
     ["类别", "试验阶段", "最短试验期"], ["起始", "结束日龄", "结束体重"]),
    ("表5", 5, [(1, 2), (3, 1), (1, 2)], [(1, 1), (1, 1), (1, 1)],
     ["类别", "试验阶段", "最短试验期"], ["起始", "结束日龄", "结束体重"]),
    ("表6", 4, [(1, 2), (2, 1), (1, 2)], [(1, 1), (1, 1)],
     ["类别", "试验阶段", "最短试验期"], ["开始", "结束日龄"]),
]

PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **本页有 4 张表, 请按页面从上到下顺序, 输出 4 个独立的 <table>。**\n"
    "3. **每张表顶部若有一行居中的表标题(如「表3 牛（包括水牛）」「表4 绵羊」"
    "「表5 山羊」「表6 家兔」), 必须作为该表的第一行输出, 用 <th colspan=\"N\">标题文字</th>, "
    "严禁丢失。**\n"
    "4. **表3 牛 / 表4 绵羊 / 表5 山羊 都是 5 列**, 从左到右:\n"
    "   第1列 类别 | 第2列 起始 | 第3列 结束日龄 | 第4列 结束体重（kg） | 第5列 最短试验期\n"
    "   表头第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=3) | 最短试验期(rowspan=2)\n"
    "   表头第2行: 起始 | 结束日龄 | 结束体重（kg）\n"
    "5. **表6 家兔 只有 4 列**(没有「结束体重（kg）」这一列), 从左到右:\n"
    "   第1列 类别 | 第2列 开始 | 第3列 结束日龄 | 第4列 最短试验期\n"
    "   表头第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=2) | 最短试验期(rowspan=2)\n"
    "   表头第2行: 开始 | 结束日龄\n"
    "6. **即使某列整列为空也必须输出该列**, 不能省略。\n"
    "7. **数据区不要给任何一列加 rowspan**; 每行每列都是独立 <td>。\n"
    "8. 单元格内的换行合并进同一个单元格, 不要拆成多行\n"
    "9. 页眉、页码、书名不要输出\n"
    "10. 只输出表格本身, 不要任何解释文字"
)

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S | re.I)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=24000, timeout=180):
    import urllib.request
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


def clean(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = re.sub(r"```[a-zA-Z]*\n?", "", txt)
    txt = re.sub(r"\n```\s*$", "", txt)
    txt = re.sub(r"^(图像中的文字如下[：:]?|图片中识别出的文字如下[：:]?|"
                 r"图片里检测到的文字如下[：:]?)\s*", "", txt.strip())
    return txt.strip()


def parse_rows(txt):
    out = []
    for tr in TR_RE.findall(txt):
        cells = []
        for m in CELL_RE.finditer(tr):
            tag, attrs_s, inner = m.group(1), m.group(2), m.group(3)
            attrs = dict(ATTR_RE.findall(attrs_s))
            cs = int(attrs.get("colspan", 1) or 1)
            rs = int(attrs.get("rowspan", 1) or 1)
            text = re.sub(r"<br\s*/?>", " ", inner, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            cells.append(dict(tag=tag, colspan=cs, rowspan=rs, text=text))
        if cells:
            out.append(cells)
    return out


def expand_rows(rows):
    """把 rowspan 展开成网格, 返回每行真实占用的叶子列数。"""
    grid = []
    pending = {}
    for r, row in enumerate(rows):
        if len(grid) <= r:
            grid.append([])
        col = 0
        for c in row:
            while col in pending:
                grid[r].append(pending[col][0])
                pending[col][1] -= 1
                if pending[col][1] <= 0:
                    del pending[col]
                col += 1
            for _ in range(c["colspan"]):
                if col in pending:
                    grid[r].append(pending[col][0])
                    pending[col][1] -= 1
                    if pending[col][1] <= 0:
                        del pending[col]
                else:
                    grid[r].append(c["text"])
                    if c["rowspan"] > 1:
                        pending[col] = [c["text"], c["rowspan"] - 1]
                col += 1
        while col in pending:
            grid[r].append(pending[col][0])
            pending[col][1] -= 1
            if pending[col][1] <= 0:
                del pending[col]
            col += 1
    return grid


def leaf_cols_of_header(header_rows):
    return max(sum(c["colspan"] for c in row) for row in header_rows)


def check_table(tb, spec):
    """按 spec 校验单张表。返回 (ok, detail)。"""
    name, want_leaves, want_r1, want_r2, keys1, keys2 = spec
    rows = parse_rows(tb)
    if len(rows) < 4:
        return False, f"{name}: 行数不足({len(rows)})"
    # caption 行: 单格且 colspan>=2
    hdr_start = 0
    if len(rows[0]) == 1 and rows[0][0]["colspan"] >= 2:
        hdr_start = 1
    else:
        return False, f"{name}: 缺表标题行"
    if hdr_start + 1 >= len(rows):
        return False, f"{name}: 表头不足两行"
    r1, r2 = rows[hdr_start], rows[hdr_start + 1]
    got1 = [(c["colspan"], c["rowspan"]) for c in r1]
    got2 = [(c["colspan"], c["rowspan"]) for c in r2]
    if got1 != want_r1:
        return False, f"{name}: 表头第1行 span {got1} != {want_r1}"
    if got2 != want_r2:
        return False, f"{name}: 表头第2行 span {got2} != {want_r2}"
    for c, k in zip(r1, keys1):
        if k not in c["text"]:
            return False, f"{name}: 表头第1行缺「{k}」(实为 {c['text']!r})"
    for c, k in zip(r2, keys2):
        if k not in c["text"]:
            return False, f"{name}: 表头第2行缺「{k}」(实为 {c['text']!r})"
    # 叶子列数
    L = leaf_cols_of_header([r1, r2])
    if L != want_leaves:
        return False, f"{name}: 叶子列数 {L} != {want_leaves}"
    # 数据行宽度必须一致且 == want_leaves
    grid = expand_rows(rows)
    widths = [len(g) for g in grid]
    data_w = sorted(set(widths[hdr_start:]))
    if len(data_w) != 1 or data_w[0] != want_leaves:
        return False, f"{name}: 数据行宽 {data_w} != [{want_leaves}]"
    # 数据区不该有 rowspan>1(除表头)
    for i, row in enumerate(rows[hdr_start + 2:], start=hdr_start + 2):
        for c in row:
            if c["rowspan"] > 1:
                return False, f"{name}: 数据行出现 rowspan={c['rowspan']}"
    # 实质行数
    real = sum(1 for g in grid if any(c.strip() for c in g))
    if real < 4:
        return False, f"{name}: 实质行不足({real})"
    return True, f"{name}: OK {L}列 {real}行"


def analyze(txt):
    tables = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    if not tables:
        return None
    results = []
    for tb, spec in zip(tables, SPECS):
        ok, detail = check_table(tb, spec)
        results.append((ok, detail))
    if len(tables) != len(SPECS):
        results.append((False, f"表数量 {len(tables)} != {len(SPECS)}"))
    return dict(tables=results, raw=txt, n_tables=len(tables))


def quality(st):
    score = 0
    for ok, detail in st["tables"]:
        score += 10 if ok else -20
    return score


def report(st):
    print("  " + " | ".join(("OK  " if ok else "FAIL") + " " + d
                           for ok, d in st["tables"]))


def prep_bytes(img, target_w=TARGET_W):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


def main():
    os.makedirs(TMP, exist_ok=True)
    im = Image.open(SRC)
    W, H = im.size
    rp = os.path.join(TMP, "pg0059.jpg")
    im.crop((CUT_X, 0, W, H)).save(rp, quality=95, subsampling=0)
    print(f"[split] {SRC} {W}x{H} cut@{CUT_X} -> right {W-CUT_X}px")

    page = Image.open(rp)
    data = prep_bytes(page)
    print(f"[0059] 送 API  {page.size[0]}x{page.size[1]} -> {len(data)//1024}KB")

    best = None
    for attempt in range(1, RETRY + 1):
        try:
            raw = clean(api_ocr(data, PROMPT))
        except Exception as e:
            print(f"  [尝试{attempt}] API 失败: {e}")
            continue
        if "<table" not in raw.lower():
            print(f"  [尝试{attempt}] 输出不含 <table>: {raw[:80]!r}")
            continue
        st = analyze(raw)
        if st is None:
            print(f"  [尝试{attempt}] 解析失败")
            continue
        report(st)
        sc = quality(st)
        if best is None or sc > best[0]:
            best = (sc, st)
        if sc == 10 * len(SPECS):
            print(f"  [尝试{attempt}] 4 张表全部通过, 采用")
            break

    if best is None:
        print("[0059] 全部尝试失败")
        return 1
    sc, st = best
    out = os.path.join(DOC_DIR, "0059.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("<!-- source: Images/02制度文件/0059.jpg (split: 0059) -->\n")
        f.write("<!-- repaired: rotated=no, method=api-minimax -->\n\n")
        f.write(st["raw"] + "\n")
    print(f"[0059] 已写 {out} (score={sc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
