#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0298/0299 (饲料原料目录) —— 走 API 重新读表。

【为什么走 API 而不是手工抄】
这页是**高密度长文本表**: 2 页 28 行, 特征描述 列每行都是一整段。
手工从裁图抄写极易错列(实测连续 3 次都裁到了 强制性标识要求 列)。
表格本身结构规整(4 列定宽), 模型读这种表很稳 —— 之前的错是**切图切掉了列**。

【页面映射】
Images/02制度文件/0299.jpg = 书第 298(左) + 299(右)
  书脊实测 **x≈2250**(算法给 1423, 偏左 830px!)
  页298 表格真实列边界: 原料编号|原料名称|特征描述|强制性标识要求
     -> 末列右边界 x=2360, **按中线 2050 切会切掉「强制性标识要求」列**
        这就是原 0298.md 少一列 / 拼成 6 列的根因。

【每页 2 张表 + 节标题】
页298: 表1 (续表) 10.4.8~10.5.1 ; 节标题「11. 矿物质」+ 表2 (11.1 / 11.1.1 / 贝壳粉)
页299: 表1 (续表) 11.1.2~11.1.12 ; 节标题「12. 微生物发酵产品及副产品」+ 表2 (12.1 / 12.1.1)
"""
import base64
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import mm_ocr

OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "04_（四）使用管理", "44_饲料原料目录")

CUT = 2250

PROMPT = (
    "请把这张中文**表格扫描页**转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **一页有多张表就输出多个 <table>**, 中间的节标题(如「11. 矿物质」"
    "「12. 微生物发酵产品及副产品」)作为**普通段落**单独输出在两张表之间。\n"
    "3. 表头是 原料编号 | 原料名称 | 特征描述 | 强制性标识要求 —— "
    "**每张表都要有这 4 列表头, 一列都不能少**。\n"
    "4. **特征描述 列的文本必须完整**, 该列每行都是一整段话, "
    "不要截断、不要摘要、不要改写, 逐字抄下来。\n"
    "5. **强制性标识要求 列是多行项目**(如 粗蛋白/水分/赖氨酸/水分), "
    "同一格里用 <br> 分隔, 不要拆成多行 <tr>。\n"
    "6. **原料名称 后面的上标字母**(如 鱼溶浆a、鱼溶浆粉b、沸石粉a)必须保留, "
    "写成 鱼溶浆ᵃ / 鱼溶浆粉ᵇ 这种形式。\n"
    "7. **不要编造合并单元格**: 本表每行都是独立的 4 格, 不要用 rowspan/colspan。\n"
    "8. 页眉、页码、书脊阴影不要输出; 不要输出 LaTeX; "
    "只输出表格和节标题, 不要任何解释文字"
)

# 期望的原料编号序列(目视核对过), 用于质量门
EXPECT = {
    "0298": {
        "t1": ["10.4.8", "10.4.9", "10.4.10", "10.4.11", "10.4.12",
               "10.4.13", "10.4.14", "10.5", "10.5.1"],
        "t2": ["11.1", "11.1.1", ""],
    },
    "0299": {
        "t1": ["11.1.2", "11.1.3", "11.1.4", "11.1.5", "11.1.6", "11.1.7",
               "11.1.8", "11.1.9", "11.1.10", "11.1.11", "11.1.12"],
        "t2": ["12.1", "12.1.1"],
    },
}

HEAD = ["原料编号", "原料名称", "特征描述", "强制性标识要求"]


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=32000, timeout=300):
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


import urllib.request  # noqa: E402


def clean(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = re.sub(r"```[a-zA-Z]*\n?", "", txt)
    txt = re.sub(r"\n```\s*$", "", txt)
    txt = re.sub(r"^(图像中的文字如下[：:]?|图片中识别出的文字如下[：:]?|"
                 r"根据图片内容[，,]?\s*(以下是|下面是)[^<]{0,40})\s*", "", txt.strip())
    return txt.strip()


def prep(img, target_w=2400):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=93)
    return o.getvalue()


def cells_of(tr):
    return [re.sub(r"<[^>]+>", "", x).strip()
            for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]


def score(raw, tag):
    tabs = re.findall(r"<table.*?</table>", raw, re.S | re.I)
    s = 0
    why = []
    if len(tabs) != 2:
        s -= 40 * abs(len(tabs) - 2)
        why.append("表数%d" % len(tabs))
    for i, tb in enumerate(tabs):
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I)
        hdr = cells_of(raws[0]) if raws else []
        if hdr[:4] != HEAD:
            s -= 30
            why.append("表%d表头错:%s" % (i + 1, hdr[:4]))
        else:
            s += 20
        for j, r in enumerate(raws):
            n = len(cells_of(r))
            if n != 4:
                s -= 8
                why.append("表%d行%d=%d格" % (i + 1, j + 1, n))
        s += len(raws) * 3
    # 编号序列
    for ti, want in enumerate(EXPECT.get(tag, {}).values()):
        if ti >= len(tabs):
            continue
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tabs[ti], re.S | re.I)
        got = [cells_of(r)[0] if cells_of(r) else "" for r in raws[1:]]
        miss = [w for w in want if w not in got]
        if miss:
            s -= 20 * len(miss)
            why.append("表%d缺编号%s" % (ti + 1, miss[:3]))
        else:
            s += 40
    # 节标题
    for h in ("11. 矿物质", "12. 微生物发酵产品及副产品"):
        if h in raw:
            s += 15
    why.append("表%d" % len(tabs))
    return s, ";".join(why[:5])


def build(tag, src, is_right):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    cands = [CUT - 60, CUT, CUT + 60, CUT + 120]

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        raw = clean(api_ocr(prep(page), PROMPT))
        s, why = score(raw, tag)
        return (c, s, raw, why)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for c, s, raw, why in ex.map(run, cands):
            print("    cut=%d: score=%s  %s" % (c, ("%+d" % s) if s is not None else "ERR", why))
            results.append((s, raw, why))
    if not results:
        return None
    results.sort(key=lambda r: -(r[0] or -999))
    print("  -> 选中 score=%+d" % results[0][0])
    return results[0][1]


def check(txt, tag):
    errs = []
    tabs = re.findall(r"<table.*?</table>", txt, re.S | re.I)
    if len(tabs) != 2:
        errs.append("表数 %d != 2" % len(tabs))
    for i, tb in enumerate(tabs):
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I)
        if not raws:
            errs.append("表%d 空" % (i + 1))
            continue
        hdr = cells_of(raws[0])
        if hdr[:4] != HEAD:
            errs.append("表%d 表头错 %s" % (i + 1, hdr[:4]))
        for j, r in enumerate(raws):
            if len(cells_of(r)) != 4:
                errs.append("表%d 行%d 非4格" % (i + 1, j + 1))
    # 编号齐全
    nos = []
    for tb in tabs:
        raws = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I)
        for r in raws[1:]:
            c = cells_of(r)
            if c:
                nos.append(c[0])
    for want in EXPECT.get(tag, {}).get("t1", []) + EXPECT.get(tag, {}).get("t2", []):
        if want and want not in nos:
            errs.append("缺编号 " + want)
    for h in ("11. 矿物质", "12. 微生物发酵产品及副产品"):
        if h in EXPECT and False:
            pass
    if "11. 矿物质" not in txt and tag == "0298":
        errs.append("缺节标题 11. 矿物质")
    if "12. 微生物发酵产品及副产品" not in txt and tag == "0299":
        errs.append("缺节标题 12. 微生物发酵产品及副产品")
    return errs


def main():
    src = os.path.join(REPO, "Images", "02制度文件", "0299.jpg")
    for tag, is_right in (("0299", True),):
        print("\n=== %s ===" % tag)
        raw = build(tag, src, is_right)
        if raw is None:
            print("  全部候选失败")
            continue
        txt = ("<!-- source: Images/02制度文件/0299.jpg (split: %s, cut=%d) -->\n"
               "<!-- repaired: rotated=no, method=api-minimax, form=table, multi-table -->\n\n"
               % (tag, CUT)) + raw.strip() + "\n"
        errs = check(txt, tag)
        out = os.path.join(OUTDIR, tag + ".md")
        if errs:
            print("!! %s 质量门未过: %s" % (tag, "; ".join(errs[:8])))
            print("   (已写草稿到 %s, 供人工核对)" % os.path.relpath(out, REPO))
            with open(out + ".draft", "w", encoding="utf-8") as f:
                f.write(txt)
            continue
        with open(out, "w", encoding="utf-8") as f:
            f.write(txt)
        print("OK %s -> %s (%d 字节)" %
              (tag, os.path.relpath(out, REPO), len(txt.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
