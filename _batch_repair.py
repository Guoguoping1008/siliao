#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量重生成退化页(裸 LaTeX longtable / 整页压平)。

用法:
    python _batch_repair.py --list                 # 列出待修页
    python _batch_repair.py --pages 0255,0311      # 修指定页(按 stem)
    python _batch_repair.py --all --limit 5       # 修前 N 个
    python _batch_repair.py --pages 0255 --dry-run

【自动书脊定位】
跨页扫描件 Images/<folder>/<M>.jpg = 书第 M-1(左) + M(右) 页。
切分点不能取几何中线(实测会切进左页表格里), 用:
  1. 暗像素列剖面找沟谷(沟谷常偏左)
  2. 在沟谷附近找**长竖线**(表格边框, 暗像素列高 > 页高*0.35)
  3. 取「左页最右竖线」与「右页最左竖线」的中点
若找不到可靠竖线, 回退到沟谷最小值, 但要人工确认。
"""
import argparse
import base64
import io
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

import _spine

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
IMAGES = os.path.join(REPO, "Images")
MINIMAX = os.path.join(REPO, "minimax")

TARGET_W = 1900
RETRY = 4

TABLE_PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **页面上方若有居中的表标题(如「表1 猪」), 必须作为表格第一行输出, "
    "用 <th colspan=\"N\">标题文字</th>, 严禁丢失**\n"
    "3. 保持原表列顺序, 合并单元格用 colspan/rowspan 表达\n"
    "4. **即使某列整列为空也必须输出该列**, 不能省略\n"
    "5. 单元格内的换行合并进同一个单元格, 不要拆成多行; "
    "带下划线的填空处(如 名称：______)照原样输出下划线\n"
    "6. 页眉、页码、书名不要输出\n"
    "7. 只输出表格本身, 不要任何解释文字, 不要输出 LaTeX"
)

TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S | re.I)
ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# 串页检测: 扫描件页眉形如「<<< 二、制度文件 311」「饲料法规文件 (2023) >>>」
# 若输出里出现这类东西, 说明切分把对页也切进来了。
RE_HDR = re.compile(r"(?:<<<\s*[一二三四五六]、|饲料法规文件\s*[（(]\s*20\d\d\s*[)）]|制度文件\s*\|\s*\d{1,4})")


# ------------------------------------------------------------------ 索引
def build_page_index():
    """(folder, page_no) -> 原图路径"""
    m = {}
    for dp, _, fs in os.walk(IMAGES):
        for f in fs:
            if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            s = os.path.splitext(f)[0]
            if not s.isdigit():
                continue
            n = int(s)
            folder = os.path.basename(dp)
            src = os.path.join(dp, f)
            m.setdefault((folder, n), src)
            m.setdefault((folder, n - 1), src)
    return m


def build_md_index():
    """stem -> md 路径(取层级最深的)"""
    idx = {}
    for dp, _, fs in os.walk(MINIMAX):
        depth = dp[len(MINIMAX):].count(os.sep)
        for f in fs:
            if f.endswith(".md") and not f.endswith(".bak"):
                stem = os.path.splitext(f)[0]
                prev = idx.get(stem)
                if prev is None or depth > prev[1]:
                    idx[stem] = (os.path.join(dp, f), depth)
    return {k: v[0] for k, v in idx.items()}


# ------------------------------------------------------------------ 切分
def find_spine(img):
    """书脊定位。委托给 _spine(白沟优先, 其次孤立尖峰)。"""
    return _spine.find_spine(img)


def make_pages(src_img, page_no):
    """把跨页图切成 [左半(页 page_no-1), 右半(页 page_no)]"""
    im = Image.open(src_img)
    W, H = im.size
    cut, why = find_spine(im)
    cut = max(200, min(W - 200, cut))
    left = im.crop((0, 0, cut, H))
    right = im.crop((cut, 0, W, H))
    return left, right, cut, why


# ------------------------------------------------------------------ API
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


def prep_bytes(img, target_w=TARGET_W):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


def parse_rows(txt):
    out = []
    for tr in TR_RE.findall(txt):
        cells = []
        for m in CELL_RE.finditer(tr):
            tag, attrs_s, inner = m.group(1), m.group(2), m.group(3)
            attrs = dict(ATTR_RE.findall(attrs_s))
            text = re.sub(r"<br\s*/?>", " ", inner, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            cells.append(dict(tag=tag,
                              colspan=int(attrs.get("colspan", 1) or 1),
                              rowspan=int(attrs.get("rowspan", 1) or 1),
                              text=text))
        if cells:
            out.append(cells)
    return out


def expand_rows(rows):
    grid, pending = [], {}
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


def table_quality(txt):
    """返回 (ok, detail, score)"""
    if "<table" not in txt.lower():
        return False, "无 <table>", -100
    tabs = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    allrows = []
    for tb in tabs:
        rows = parse_rows(tb)
        if len(rows) < 2:
            return False, f"行数不足 {len(rows)}", -50
        grid = expand_rows(rows)
        widths = [len(g) for g in grid]
        wm = sorted(set(widths))
        allrows.extend(widths)
        # 空单元格率
        allc = [c for g in grid for c in g]
        er = sum(1 for c in allc if not c.strip()) / max(1, len(allc))
        if er > 0.6:
            return False, f"空单元格率 {er:.2f} 过高", -40
        if len(wm) > 1:
            return False, f"行宽不齐 {wm}", -20
    score = len(allrows) * 2 + 20 * len(tabs) - 20 * er
    return True, f"{len(tabs)} 张表, 行宽 {sorted(set(allrows))}, 空单元率 {er:.2f}", score


def repair_page(page_img, tag, src_rel, dry_run=False):
    data = prep_bytes(page_img)
    best = None
    for attempt in range(1, RETRY + 1):
        try:
            raw = clean(api_ocr(data, TABLE_PROMPT))
        except Exception as e:
            print(f"    [尝试{attempt}] API 失败: {e}")
            continue
        ok, detail, score = table_quality(raw)
        print(f"    [尝试{attempt}] {'OK ' if ok else 'FAIL'} {detail}")
        if not ok:
            continue
        # 串页检测: 输出里出现「对页页眉」说明切分切错了
        if RE_HDR.search(raw):
            print(f"    [尝试{attempt}] 检出对页页眉, 疑似串页: "
                  f"{RE_HDR.findall(raw)[:2]}")
            continue
        if best is None or score > best[0]:
            best = (score, raw)
        break
    if best is None:
        return False
    body = (f"<!-- source: {src_rel} -->\n"
            f"<!-- repaired: rotated=no, method=api-minimax -->\n\n"
            f"{best[1].strip()}\n")
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="", help="逗号分隔的 stem 列表")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scan-json", default=os.path.join(REPO, "_degen_scan.json"))
    args = ap.parse_args()

    pidx = build_page_index()
    midx = build_md_index()
    scan = json.load(open(args.scan_json, encoding="utf-8"))
    todo = []
    for rel in scan.get("1_longtable", []) + scan.get("2_flat", []):
        stem = os.path.splitext(os.path.basename(rel))[0]
        folder = rel.split("/")[0]
        if stem in midx and (folder, int(stem)) in pidx:
            todo.append((stem, folder, int(stem), rel))
    # 去重
    seen = set()
    uniq = []
    for t in todo:
        if t[0] in seen:
            continue
        seen.add(t[0])
        uniq.append(t)

    if args.list:
        print(f"待修 {len(uniq)} 页:")
        for stem, folder, page, rel in uniq:
            print(f"  {stem}  {rel}")
        return 0

    if args.pages:
        want = set(x.strip() for x in args.pages.split(",") if x.strip())
        uniq = [t for t in uniq if t[0] in want]
    elif args.all:
        if args.limit:
            uniq = uniq[:args.limit]

    if not uniq:
        print("没有要修的页")
        return 0

    ok_n = 0
    for stem, folder, page, rel in uniq:
        src = pidx[(folder, page)]
        md = midx[stem]
        print(f"\n=== {stem}  ({rel}) ===")
        print(f"  源图 {src}")
        left, right, cut, why = make_pages(src, page)
        # page 是奇数 -> 右半; 偶数 -> 左半
        is_right = (page % 2 == 1)
        img = right if is_right else left
        print(f"  书脊切点 x={cut} ({why}), 取{'右' if is_right else '左'}半 "
              f"{img.size[0]}x{img.size[1]}")
        if args.dry_run:
            continue
        body = repair_page(img, stem, os.path.relpath(src, REPO).replace("\\", "/"),
                           args.dry_run)
        if not body:
            print("  放弃")
            continue
        with open(md, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"  已写 {os.path.relpath(md, REPO)}")
        ok_n += 1
    print(f"\n完成 {ok_n}/{len(uniq)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
