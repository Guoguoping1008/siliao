#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0061 的表格部分。

【背景】
0061.md 是**退化输出**: 模型只读出 3 个标签(试验编号：/第2页，共___页/日粮组成),
然后把表格补成 16KB 的空单元格网格(200+ 个空格子)。
内容对、体积废 —— 纯空白表单进索引会稀释向量空间。

【映射】
Images/02制度文件/0061.jpg = 书第 60(左)+61(右) 页跨页扫描件。
0061.md 是**右半**(第 61 页) = 附录B「试验概述表」的第 2 页。
书脊实测: 几何中线 2241 会切到左页表格内部; 左页右边框 x≈2173, 右页左边框 x≈2333
-> 切在 2250。

【实测结构(从图上数出来的)】
第1行: 试验编号： | 第2页，共___页                                  (2 列)
第2行: 试验日粮(rowspan=8) | 日粮组成（营养素和能值）(colspan=3)
第3行: 计算值 | 实测值
第4-7行: 成分1 / 成分2 / 成分3 / ……
第8行: 日粮形态 | 粉料□ 颗粒□ 膨化□ 其他____
之后每行 2 列(标签 | 空):
  检测项目和实施时间 / 治疗和预防措施(原因、时间、种类、持续时间等) /
  数据统计分析方法 / 突发状况的处理、不良后果发生的时间及发生范围 /
  结论 / 原始记录保管 / 备注
最后一行: 试验人员：| 项目负责人：| 报告签署人及签署时间:            (3 列)

叶子列数: 上半部 4 列(试验日粮 | 成分 | 计算值 | 实测值),
          下半部 2 列(标签 | 空), 末行 3 列。

【为什么不能只「裁空行」】
原缺陷是「1 行巨长表格 + 200 个空格子」, 不是「很多空行」。
必须让模型**按原图的行列结构**重建, 否则裁剪也救不回来。
所以这里用 HTML 表格提示词 + 结构校验, 而不是 trim_blank_form。
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

SRC = os.path.join(REPO, "Images", "02制度文件", "0061.jpg")
TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
DOC_DIR = os.path.join(REPO, "minimax", "02制度文件", "01_（一）新产品审定",
                       "08_饲料和饲料添加剂畜禽靶动物耐受性评价试验指南（试行）")

CUT_X = 2250
TARGET_W = 1900
RETRY = 6

PROMPT = (
    "请把这张中文**表格表单扫描页**转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头/标签用 <th>)\n"
    "2. **本页是一张「试验概述表」表单的第2页**。表格的上半部是 4 个叶子列, 下半部只有 2 个叶子列。\n"
    "   请**严格按下面的行结构**输出(这是从图上数出来的, 不要自己发挥):\n"
    "   第1行: 「试验编号：」(colspan=1) | 「第2页，共___页」(colspan=3)\n"
    "   第2行: 「试验日粮」(rowspan=8) | 「日粮组成（营养素和能值）」(colspan=3)\n"
    "   第3行: 「计算值」(colspan=1) | 「实测值」(colspan=2)\n"
    "   第4行: 「成分1」 | 空 | 空\n"
    "   第5行: 「成分2」 | 空 | 空\n"
    "   第6行: 「成分3」 | 空 | 空\n"
    "   第7行: 「……」 | 空 | 空\n"
    "   第8行: 「日粮形态」 | 「粉料□ 颗粒□ 膨化□ 其他____」(colspan=2)\n"
    "   第9~15行 全部是 2 个叶子列(左标签 | 右空, 右格 colspan=2):\n"
    "     「检测项目和实施时间」/「治疗和预防措施（原因、时间、种类、持续时间等）」/\n"
    "     「数据统计分析方法」/「突发状况的处理、不良后果发生的时间及发生范围：」/\n"
    "     「结论」/「原始记录保管」/「备注」\n"
    "   第16行 3 个叶子列: 「试验人员：」| 「项目负责人：」| 「报告签署人及签署时间：」\n"
    "3. **原表是空白表单, 大量单元格本来就是空的 —— 空的单元格要保留为 <td></td>, "
    "但总行数必须严格是上面列出的 16 行, 绝对不要自己编造额外的空行或空列。**\n"
    "4. 合并单元格用 colspan/rowspan 表达\n"
    "5. 单元格内的换行合并进同一个单元格, 不要拆成多行\n"
    "6. 页眉(「<<< 二、制度文件 61」)、页码、书名不要输出\n"
    "7. 只输出表格本身, 不要任何解释文字"
)

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S | re.I)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=16000, timeout=180):
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


# 必须出现的标签(逐字)
NEED_LABELS = [
    "试验编号", "第2页", "日粮组成", "试验日粮", "计算值", "实测值",
    "成分1", "成分2", "成分3", "日粮形态",
    "检测项目和实施时间", "治疗和预防措施", "数据统计", "突发状况",
    "结论", "原始记录", "备注",
    "试验人员", "项目负责人", "报告签署人",
]
# 期望的标签数量: 19 个标签 -> 期望 19 个非空「标签行」
EXPECT_ROWS = 16
MAX_ROWS = 18          # 允许 16 行 + 少量容错
MIN_ROWS = 14
MAX_CELLS = 60         # 防止又编出一堆空格子

# 每行的 (colspan, rowspan) 期望形状(按 4 叶子列的上半部对齐):
#   行1  编号页码
#   行2  日粮组头
#   行3  计算/实测
#   行4-7 成分1-3/......
#   行8  日粮形态
#   行9-15 2 列标签行
#   行16 签字行
ROW_SHAPES = [
    [(1, 1), (3, 1)],
    [(1, 8), (3, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (1, 1), (1, 1)],
    [(1, 1), (1, 1), (1, 1)],
    [(1, 1), (1, 1), (1, 1)],
    [(1, 1), (1, 1), (1, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (2, 1)],
    [(1, 1), (1, 1), (1, 1)],
]


def check(tb):
    rows = parse_rows(tb)
    if not rows:
        return False, "无行"
    grid = expand_rows(rows)
    nrows = len(grid)
    if nrows < MIN_ROWS or nrows > MAX_ROWS:
        return False, f"行数 {nrows} 不在 [{MIN_ROWS},{MAX_ROWS}]"
    widths = [len(g) for g in grid]
    if max(widths) > 4:
        return False, f"列数 {max(widths)} > 4"
    ncells = sum(len(r) for r in rows)
    if ncells > MAX_CELLS:
        return False, f"格子数 {ncells} > {MAX_CELLS}"
    text = tb
    missing = [k for k in NEED_LABELS if k not in text]
    if missing:
        return False, f"缺标签 {missing}"
    # 逐行形状校验(只校验前 16 行, 允许末尾多出容错行)
    for i, want in enumerate(ROW_SHAPES):
        if i >= len(rows):
            return False, f"行数不足 {len(rows)} < 16"
        got = [(c["colspan"], c["rowspan"]) for c in rows[i]]
        if got != want:
            return False, f"第{i+1}行 span {got} != {want}"
    # 不该有多余的整行空行
    for i, g in enumerate(grid):
        if not any(c.strip() for c in g):
            return False, f"第{i+1}行是整行空行"
    return True, f"OK {nrows}行 宽{widths}"


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
    rp = os.path.join(TMP, "pg0061.jpg")
    im.crop((CUT_X, 0, W, H)).save(rp, quality=95, subsampling=0)
    print(f"[split] {SRC} {W}x{H} cut@{CUT_X} -> right {W-CUT_X}px")

    page = Image.open(rp)
    data = prep_bytes(page)
    print(f"[0061] 送 API  {page.size[0]}x{page.size[1]} -> {len(data)//1024}KB")

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
        tables = re.findall(r"<table.*?</table>", raw, re.S | re.I)
        if not tables:
            continue
        ok, detail = check(tables[0])
        print(f"  [尝试{attempt}] {'OK ' if ok else 'FAIL'} {detail}")
        if not ok:
            continue
        if best is None:
            best = (raw, tables[0])
            break

    if best is None:
        print("[0061] 全部尝试失败")
        return 1
    raw, tb = best
    out = os.path.join(DOC_DIR, "0061.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("<!-- source: Images/02制度文件/0061.jpg (split: 0061) -->\n")
        f.write("<!-- repaired: rotated=no, method=api-minimax, form=blank -->\n\n")
        f.write(raw + "\n")
    print(f"[0061] 已写 {out}  ({len(raw)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
