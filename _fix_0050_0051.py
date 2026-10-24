#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0050/0051 的表格部分(第三轮: 加叶子列数一致性门)。

【前两轮实测的 VLM 缺陷】
  A. 表标题行丢失            -> 提示词第 2 条修好
  B. 最右列合并内容丢失      -> 提示词第 3 条修好
  C. **丢掉整列「结束体重（kg）」**, 且把 试验阶段 写成 colspan=2
  D. **滥用 rowspan**: 把 最短试验期 列 5 个不同值(56天/56天/49天*/受精至断奶/42天)
     合并成一个 rowspan=5 的「56天」-> 数据直接丢失

【根因】
  VLM 在列数上做加法不可靠: 它把「试验阶段（体重或日龄）」下面的子列数错数成 2,
  然后整张表左移一列, 后面的列自然对不上; 一旦对不上, 它就用 rowspan 硬凑。

【对策(本轮)】
  1. 提示词**直接告知叶子列数**(实测 6), 并禁止在数据区乱用 rowspan
  2. 提示词要求: 合并单元格只允许出现在**最后一列**; 其他列一律逐行独立 <td>
  3. 后处理加**叶子列数一致性门**: 从表头的 rowspan/colspan 算出叶子列数 L,
     再要求所有数据行的**展开后**单元格数 == L。不等就重试。
     (rowspan 的单元格在展开时要按跨行数摊到多行, 这是校验的关键。)
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

SRC = os.path.join(REPO, "Images", "02制度文件", "0051.jpg")
TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
DOC_DIR = os.path.join(REPO, "minimax", "02制度文件", "01_（一）新产品审定",
                       "07_饲料和饲料添加剂畜禽靶动物有效性评价试验指南（试行）")

# 书脊实测位置(几何中线 2250 会切掉左页最后一列)
CUT_X = 2300

# 实测叶子列数(从图上数出来的, 不是猜的):
#   表2 家禽 / 表3 牛: 类别|起始|结束日龄|结束体重（kg）|最短试验期|最少试验重复和动物数量
#   表4 绵羊 / 表5 山羊 / 表6 家兔: 同上 6 列
LEAF_COLS = 6

# 表头结构的**实测不变量**(从图上数出来的):
#   第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=3) | 最短试验期(rowspan=2) | 最少试验重复和动物数量(rowspan=2)
#   第2行: 起始 | 结束日龄 | 结束体重（kg）
# 关键: **列数一致不等于内容对齐**。
#   实测坏样本里 VLM 输出 6 列, 但第6列是个**空的幽灵列**,
#   而真值是「每个处理…」这一列 —— 值整体左移了一列, 计数完全看不出来。
#   所以必须校验**表头结构本身**(colspan/rowspan 的形状), 不能只数格子。
HEADER_ROW1 = [("类别", 1, 2), ("试验阶段", 3, 1), ("最短试验期", 1, 2),
               ("最少试验重复", 1, 2)]
HEADER_ROW2 = ["起始", "结束日龄", "结束体重"]

PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **页面顶部若有一行居中的表标题(如「表2 家禽」「表3 牛（包括水牛）」), "
    "必须作为表格的第一行输出, 用 <th colspan=\"6\">标题文字</th>, 严禁丢失**\n"
    "3. **本表共 6 列**, 从左到右依次是:\n"
    "   第1列 类别 | 第2列 起始 | 第3列 结束日龄 | 第4列 结束体重（kg） | "
    "第5列 最短试验期 | 第6列 最少试验重复和动物数量\n"
    "   表头第1行: 类别(rowspan=2) | 试验阶段（体重或日龄）(colspan=3) | "
    "最短试验期(rowspan=2) | 最少试验重复和动物数量(rowspan=2)\n"
    "   表头第2行: 起始 | 结束日龄 | 结束体重（kg）\n"
    "4. **第4列「结束体重（kg）」即使全为空也必须输出**, 不能省略该列。\n"
    "5. **只有最后一列(第6列)可能存在跨行合并**, 其余 5 列每行都必须是独立的 <td>, "
    "绝对不要给第1~5列加 rowspan。\n"
    "6. 最后一列的合并长句(如「每个处理15个有效重复，每个重复1头，性别比例相同」)必须输出, "
    "放在该列第一行并用 rowspan 标出它跨越的行数, 后续行留空 <td>。\n"
    "7. 保持原表列顺序, 合并单元格用 colspan/rowspan 表达\n"
    "8. 单元格内的换行合并进同一个单元格, 不要拆成多行\n"
    "9. 页眉、页码、书名不要输出\n"
    "10. 只输出表格本身, 不要任何解释文字"
)

RETRY = 6
TARGET_W = 1900

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S | re.I)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=20000, timeout=180):
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
    """把 <table> 解析成 [(cells, attrs)] 列表, 保留 colspan/rowspan。"""
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


def leaf_cols_of_header(header_rows):
    """从表头行算叶子列数: 展开 colspan。"""
    best = 0
    for row in header_rows:
        n = sum(c["colspan"] for c in row)
        best = max(best, n)
    return best


def expand_rows(rows):
    """把 rowspan 展开成网格, 返回每行占用的叶子列数。

    坑: 这里算的是**该行真实占用的叶子列数**(含 rowspan 延续下来的占位),
    不是「原始格的 colspan 之和」。
    因为合法合并的行, 原始格数天然少于叶子列数(比如 rowspan=8 的那一列,
    后续 7 行只有 5 个原始格, 但它们仍然占 6 个叶子列)。
    """
    grid = []          # grid[r][col] = text
    pending = {}       # col -> [text, rows_left]
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
            for k in range(c["colspan"]):
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
        # 该行末尾若还有 pending 占位, 说明这些列被上一行的 rowspan 占着
        while col in pending:
            grid[r].append(pending[col][0])
            pending[col][1] -= 1
            if pending[col][1] <= 0:
                del pending[col]
            col += 1
    return grid


def analyze(txt):
    """返回质量指标字典。"""
    tables = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    if not tables:
        return None
    per_table = []
    for tb in tables:
        rows = parse_rows(tb)
        if len(rows) < 3:
            per_table.append(dict(rows=rows, bad="行数不足"))
            continue
        # 找表头行: 第一行是 caption(单格)则跳过
        hdr_start = 0
        if len(rows[0]) == 1 and rows[0][0]["colspan"] >= 2:
            hdr_start = 1
        hdr_rows = rows[hdr_start:hdr_start + 2]
        L = leaf_cols_of_header(hdr_rows)
        grid = expand_rows(rows)
        # **关键**: 表头声称的叶子列数 与 数据行实际占用列数 必须一致。
        # 坑: bad1 里表头写 colspan=2(合计 6 列), 但数据行只有 5 个叶子列 ——
        #     VLM 把「结束体重（kg）」整列丢了, 却仍然把表头写成 6 列。
        #     只看「表头叶子列数 == 6」会误判为合格, 必须同时校验数据行。
        #
        # 坑 2: **用 expand_rows 后的 grid 行宽**(真实占用叶子列数),
        #     不用「原始格 colspan 之和」—— 后者对合法 rowspan 的行会偏小。
        grid_widths = [len(g) for g in grid]
        data_grid_widths = grid_widths[hdr_start:]
        data_width_set = sorted(set(data_grid_widths))
        header_data_mismatch = (len(data_width_set) == 1
                                and data_width_set[0] != L)
        # 表头两行本身的宽度也必须等于 L
        hdr_own = sorted(set(grid_widths[hdr_start:hdr_start + 2]))
        hdr_ok = (len(hdr_own) == 1 and hdr_own[0] == L)
        # **表头形状校验**: 第1行的 (colspan, rowspan) 结构必须与实测一致。
        # 这是抓「幽灵列 / 值左移」的唯一手段 —— 纯计数抓不到。
        hdr_shape = header_shape_ok(rows, hdr_start)
        allc = [c for g in grid for c in g]
        nonempty = sum(1 for c in allc if c.strip())
        per_table.append(dict(
            rows=rows, grid=grid, leaf=L,
            data_widths=data_grid_widths,
            width_mismatch=data_width_set,
            header_data_mismatch=header_data_mismatch or not hdr_ok,
            hdr_shape_ok=hdr_shape[0],
            hdr_shape_detail=hdr_shape[1],
            real_rows=sum(1 for g in grid if any(c.strip() for c in g)),
            empty_ratio=1 - nonempty / max(1, len(allc)),
            has_caption=bool(re.search(r"表\s*\d+\s*\S", tb)),
            has_merged=bool(re.search(r"每个处理|有效重复", tb)),
            n=len(rows),
        ))
    return dict(tables=per_table, raw=txt)


def header_shape_ok(rows, hdr_start):
    """校验表头两行的 (colspan, rowspan) 形状是否符合实测。

    返回 (ok, detail)。
    判据:
      第1行: 4 个格, (colspan, rowspan) 依次 = (1,2) (3,1) (1,2) (1,2)
              第1格文本含「类别」, 第2格含「试验阶段」, 第3格含「最短试验期」, 第4格含「最少试验」
      第2行: 3 个格, colspan 都是 1, rowspan 都是 1, 文本依次含
              「起始」「结束日龄」「结束体重」
    """
    detail = ""
    if hdr_start + 1 >= len(rows):
        return False, "表头不足两行"
    r1 = rows[hdr_start]
    r2 = rows[hdr_start + 1]
    if len(r1) != 4 or len(r2) != 3:
        return False, f"表头格数 {len(r1)}/{len(r2)} != 4/3"
    want1 = [(1, 2), (3, 1), (1, 2), (1, 2)]
    got1 = [(c["colspan"], c["rowspan"]) for c in r1]
    if got1 != want1:
        return False, f"表头第1行 span {got1} != {want1}"
    if any(c["colspan"] != 1 or c["rowspan"] != 1 for c in r2):
        return False, f"表头第2行 span {[(c['colspan'], c['rowspan']) for c in r2]} != 全 1/1"
    keys1 = ["类别", "试验阶段", "最短试验期", "最少试验"]
    for c, k in zip(r1, keys1):
        if k not in c["text"]:
            return False, f"表头第1行缺「{k}」(实为 {c['text']!r})"
    keys2 = ["起始", "结束日龄", "结束体重"]
    for c, k in zip(r2, keys2):
        if k not in c["text"]:
            return False, f"表头第2行缺「{k}」(实为 {c['text']!r})"
    return True, "ok"


def quality(st):
    """打分: 越大越好。列数一致是硬要求。"""
    score = 0.0
    for t in st["tables"]:
        if "bad" in t:
            score -= 20
            continue
        L = t["leaf"]
        wm = t["width_mismatch"]
        score += t["real_rows"]
        score += 5 if t["has_caption"] else 0
        score += 5 if t["has_merged"] else 0
        score -= t["empty_ratio"] * 10
        # 叶子列数必须等于我们实测的列数
        if L != LEAF_COLS:
            score -= 25
        # 所有数据行宽度必须一致
        if len(wm) > 1:
            score -= 15
        elif wm and wm[0] != LEAF_COLS:
            score -= 10
        # 表头声称的列数与数据行实际宽度必须一致
        if t.get("header_data_mismatch"):
            score -= 20
        # 表头形状必须与实测一致(抓幽灵列/值左移)
        if not t.get("hdr_shape_ok"):
            score -= 30
    return score


def report(st, tag, attempt):
    msgs = []
    for i, t in enumerate(st["tables"], 1):
        if "bad" in t:
            msgs.append(f"表{i}:{t['bad']}")
            continue
        flags = []
        if t["leaf"] != LEAF_COLS:
            flags.append(f"叶子{t['leaf']}!=6")
        if len(t["width_mismatch"]) > 1:
            flags.append(f"行宽不齐{t['width_mismatch']}")
        elif t["width_mismatch"] and t["width_mismatch"][0] != LEAF_COLS:
            flags.append(f"行宽{t['width_mismatch'][0]}!=6")
        if t.get("header_data_mismatch"):
            flags.append("表头/数据列数不符")
        if not t.get("hdr_shape_ok"):
            flags.append("表头形状:" + str(t.get("hdr_shape_detail")))
        msgs.append(f"表{i}: 叶子{t['leaf']} 列 行宽{t['width_mismatch']} "
                    f"标题{'Y' if t['has_caption'] else 'N'} "
                    f"合并{'Y' if t['has_merged'] else 'N'} "
                    f"空单元率{t['empty_ratio']:.2f}"
                    + ("  <<< " + ",".join(flags) if flags else ""))


def prep_bytes(img, target_w=TARGET_W):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


def split_spread():
    os.makedirs(TMP, exist_ok=True)
    im = Image.open(SRC)
    W, H = im.size
    lp = os.path.join(TMP, "pg0050.jpg")
    rp = os.path.join(TMP, "pg0051.jpg")
    im.crop((0, 0, CUT_X, H)).save(lp, quality=95, subsampling=0)
    im.crop((CUT_X, 0, W, H)).save(rp, quality=95, subsampling=0)
    print(f"[split] cut@{CUT_X}  left {CUT_X}px / right {W-CUT_X}px")
    return lp, rp


def ocr_page(img_path, tag):
    im = Image.open(img_path)
    data = prep_bytes(im)
    print(f"[{tag}] 送 API  {im.size[0]}x{im.size[1]} -> {len(data)//1024}KB")
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
        if not st:
            print(f"  [尝试{attempt}] 解析失败")
            continue
        report(st, tag, attempt)
        sc = quality(st)
        if best is None or sc > best[0]:
            best = (sc, st)
        # 完美: 所有表叶子列数 == 6 且行宽全一致 且 表头/数据列数相符 且 表头形状相符
        ok = all(("bad" not in t and t["leaf"] == LEAF_COLS
                  and len(t["width_mismatch"]) == 1
                  and t["width_mismatch"][0] == LEAF_COLS
                  and not t.get("header_data_mismatch")
                  and t.get("hdr_shape_ok"))
                 for t in st["tables"])
        if ok:
            print(f"  [尝试{attempt}] 列数完全一致, 采用")
            break
    if best is None:
        return None, None
    return best[1]["raw"], best[1]


def main():
    lp, rp = split_spread()
    for tag, img_path in (("0050", lp), ("0051", rp)):
        txt, st = ocr_page(img_path, tag)
        if txt is None:
            print(f"[{tag}] 全部尝试失败, 放弃")
            continue
        out = os.path.join(DOC_DIR, tag + ".md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"<!-- source: Images/02制度文件/0051.jpg (split: {tag}) -->\n")
            f.write("<!-- repaired: rotated=no, method=api-minimax, cols=%d -->\n\n" % LEAF_COLS)
            f.write(txt + "\n")
        print(f"[{tag}] 已写 {out}  (score={quality(st):.1f})")


if __name__ == "__main__":
    main()
