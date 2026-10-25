#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0145/0146 的表格(空白表单模板)。

【原状态】
0145.md 337 字节、0146.md 249 字节 —— 表格结构全丢, 只剩一串标签:
  「企业名称生产地址通讯地址及邮编法定代表人...」
  这是**表格塌成纯文本**的缺陷: 行列结构没了, 但标签文字还在。

【页面映射】
Images/02制度文件/0145.jpg = 书第 144(左)+145(右) 页
Images/02制度文件/0147.jpg = 书第 146(左)+147(右) 页
所以:
  0145.md <- 0145.jpg 的**右半**
  0146.md <- 0147.jpg 的**左半**(偶数页在左半!)

【书脊定位】
自动算法给的切点都偏左(0145 给 1392, 实测右边界约 1600;
0146 给 1424, 明显把右边的「生产能力」列切掉了)。
所以用「多候选 + OCR 反馈选优」, 且**这两页是空白表单**,
打分要特别看重**列数**(切太靠左会丢右边整列)和**标签齐全度**。
"""
import base64
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import _spine_pick

TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
DOC_DIR = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                       "23_关于饲料添加剂生产许可申报材料要求的公告")

PROMPT = (
    "请把这张中文**表格表单扫描页**转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头/标签用 <th>)\n"
    "2. **页面顶部若有一行居中的表标题(如「表1 企业基本情况」「表2 产品基本情况」"
    "「表3 生产设备明细表（生产线___）」), 必须作为该表的第一行输出, "
    "用 <th colspan=\"N\">标题文字</th>, 严禁丢失。**\n"
    "3. **保持原表的行列数**: 原表有几列就输出几列, **绝不能因为右边是空白就少输出列**。\n"
    "4. 合并单元格用 colspan/rowspan 表达。本页大量使用**嵌套合并**, 必须还原:\n"
    "   - 「注册资本(万元)」与「固定资产(万元)」并排在同一行(各占自己的列)\n"
    "   - 「所属法人机构信息」是一个**左侧纵向标签**(rowspan 覆盖其下方多行)\n"
    "   - 「主要机构设置及人员组成」同样是**左侧纵向标签**(rowspan 覆盖多行)\n"
    "   - 「名称」「住所」「统一社会信用代码」「法定代表人」「企业类型」「联系人」"
    "「联系电话」「传真」「机构名称」「人数」「人员总数」「其中专业技术人员」"
    "各自是一个标签格, 其右侧是空白填写格\n"
    "   - 「企业简介：」是整行通栏\n"
    "5. **原表是空白表单, 大量单元格本来就是空的 —— 空的单元格保留为 <td></td>, "
    "但总行数必须严格按原表的行数来, 绝对不要自己编造额外的空行或空列。**\n"
    "6. 单元格内的换行合并进同一个单元格, 不要拆成多行; "
    "带下划线的填空处(如 生产线___)照原样输出下划线\n"
    "7. 页眉、页码、书名不要输出\n"
    "8. 只输出表格本身, 不要任何解释文字, 不要输出 LaTeX"
)


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
                 r"图片里检测到的文字如下[：:]?|根据图片内容[，,]?\s*"
                 r"(以下是|下面是)[^<]{0,40})\s*", "", txt.strip())
    return txt.strip()


def prep(img, target_w=1900):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


# 每页必须出现的标签(缺失说明切错了)
REQUIRED = {
    "0145": ["企业名称", "生产地址", "通讯地址及邮编", "法定代表人", "统一社会信用代码",
             "企业类型", "注册资本", "固定资产", "机构名称", "人员总数",
             "其中专业技术人员", "企业简介", "表1"],
    "0146": ["表2", "产品基本情况", "序号", "产品名称", "含量规格", "生产能力",
             "表3", "生产设备明细表", "设备名称", "位号", "型号规格", "材质",
             "生产厂家", "出厂日期", "技术性能指标"],
}

# **串页标签**: 属于对页的内容。出现了就说明切点太靠左, 对页串进来了。
# 实测 0145 的对页(144)是「生产许可证编号 / 申请书 / 生产线路」那一页。
BLEED_LABELS = {
    "0145": ["生产许可证编号", "申请书", "生产线路", "企业概况", "生产许可证"],
    "0146": ["生产许可证编号", "申请书", "生产线路", "表1 企业基本情况"],
}


def score_form(raw, tag):
    """空白表单专用打分: 列数 + 标签齐全度 + 串页检测。"""
    if "<table" not in raw.lower():
        return -100, "无表"
    tabs = re.findall(r"<table.*?</table>", raw, re.S | re.I)
    rows_all = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S | re.I)
    widths = []
    for tr in rows_all:
        n = len(re.findall(r"<t[dh][^>]*>", tr, re.I))
        if n:
            widths.append(n)
    max_cols = max(widths) if widths else 0
    # 标签齐全度
    missing = [k for k in REQUIRED.get(tag, []) if k not in raw]
    got = len(REQUIRED.get(tag, [])) - len(missing)
    total = len(REQUIRED.get(tag, [])) or 1
    s = 0
    why = []
    s += len(tabs) * 15
    s += len(rows_all) * 1.5
    s += max_cols * 10            # 列数越多越好(切太靠左会丢右边整列)
    s += int(got / total * 60)    # 标签齐全度
    if missing:
        s -= len(missing) * 12
        why.append("缺" + ",".join(missing[:4]))
    # **串页检测**: 出现了对页才有的标签 -> 切点太靠左
    bleed = [k for k in BLEED_LABELS.get(tag, []) if k in raw]
    if bleed:
        s -= 50 * len(bleed)
        why.append("串页:" + ",".join(bleed[:3]))
    if _spine_pick.RE_HDR.search(raw):
        s -= 60
        why.append("串页页眉")
    if _spine_pick.RE_TRUNC.search(raw):
        s -= 40
        why.append("标题被切")
    why.append(f"{len(tabs)}表/{len(rows_all)}行/最大{max_cols}列/标签{got}/{total}")
    return s, ",".join(why)


def pick(img_path, tag, is_right, extra_cands=()):
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    cands, base, why = _spine_pick.gen_candidates(im, n=9)
    # 追加人工确认过的候选(算法有时会偏 600px, 候选池必须够宽)
    for c in extra_cands:
        c = int(c)
        if 200 <= c <= W - 200 and all(abs(c - o) > 25 for o in cands):
            cands.append(c)
    cands.sort()
    print(f"  候选 {cands} (基线 {base}: {why})")

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page), PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {e}")
        s, d = score_form(raw, tag)
        return (s, c, raw, d)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for r in ex.map(run, cands):
            if r is None:
                continue
            s, c, raw, d = r
            print(f"    cut={c}: score={'%+d' % s if s is not None else 'ERR'}  {d}")
            if raw is not None:
                results.append(r)
    if not results:
        return None, None
    results.sort(key=lambda r: -r[0])
    best = results[0]
    print(f"  -> 选中 cut={best[1]} (score={best[0]:+.0f})")
    return best[1], best[2]


def main():
    jobs = [
        # (tag, 源图, 是否右半, 额外候选)
        # 0145: 书脊(装订折痕)实测在 x≈2007, 算法给的 1392 偏了 615px,
        #       会把对页 144 的「生产许可证编号/申请书/（公章）」串进来。
        ("0145", "Images/02制度文件/0145.jpg", True, (2020, 1990, 2060)),
        # 0146: 偶数页在**左半**; 书脊实测在 x≈2300 左右(算法给 1424 偏左太多)
        ("0146", "Images/02制度文件/0147.jpg", False, (2183, 2250, 2320)),
    ]
    for tag, src_rel, is_right, extra in jobs:
        src = os.path.join(REPO, src_rel)
        print(f"\n=== {tag}  ({src_rel}, {'右半' if is_right else '左半'}) ===")
        cut, raw = pick(src, tag, is_right, extra)
        if raw is None:
            print("  全部候选失败")
            continue
        out = os.path.join(DOC_DIR, tag + ".md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"<!-- source: {src_rel} (split: {tag}) -->\n")
            f.write("<!-- repaired: rotated=no, method=api-minimax, form=blank -->\n\n")
            f.write(raw.strip() + "\n")
        print(f"  已写 {os.path.relpath(out, REPO)} ({len(raw)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
