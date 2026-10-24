#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨页扫描件书脊定位: 算法生成候选 + 视觉模型在标线图上挑。

【背景与实测教训】
纯图像算法在 7 张实测图上错过 4 张:
  0255  沟谷 2765 / 最右峰 2749 -> 正确 2750(峰对了)
  0155  沟谷 1881 -> 正确 2422(错 541px)
  0051  沟谷 2262 -> 正确 2300(峰 2351 偏 51px)
  0311  沟谷 2691 -> 正确 2744
  0059  沟谷 2182 -> 正确 2260
  0061  沟谷 2188 -> 正确 2250
  0075  沟谷 2044 -> 正确 2100
根因: 一页里常有**多张表**, 「最靠右的竖线」不等于页边界;
      而扫描件页边常被裁掉, 没有可靠的页框线。

【做法】
1. 算法给 3~4 个候选(沟谷、沟谷±邻峰、最右峰)
2. 画成红/蓝/绿/黄 4 条线, 裁一条**横向窄带**(只取书脊那一段)
3. 视觉模型回答哪条线落在两页内容之间
4. 选中的 x 用于切分

【注意】
窄带要**足够宽**(两侧各 400px 以上)且**包含页面的中部**,
否则模型看不到「左页表格右边框终止、右页内容开始」这个关键视觉证据。
"""
import base64
import io
import json
import os
import re
import sys

import numpy as np
from PIL import Image, ImageDraw

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

COLORS = [(230, 0, 0), (0, 90, 255), (0, 165, 0), (230, 150, 0)]
NAMES = ["R", "B", "G", "Y"]


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=1200, timeout=120):
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


def candidates(img):
    """返回 (候选列表, 沟谷)"""
    a = np.asarray(img.convert("L"), dtype=np.uint8)
    H, W = a.shape
    reg = (a[int(H * 0.06):int(H * 0.95)] < 150)
    cc = reg.sum(axis=0).astype(float)

    k = max(3, W // 400)
    sm = np.convolve(cc, np.ones(k) / k, mode="same")
    lo, hi = int(W * 0.34), int(W * 0.70)
    valley = lo + int(np.argmin(sm[lo:hi]))

    win = 151
    peaks = []
    x = int(W * 0.30)
    while x < int(W * 0.72):
        base = float(np.median(cc[max(0, x - win):min(W, x + win + 1)]))
        if cc[x] > max(400, 1.9 * base):
            j = x
            while j < int(W * 0.72) and cc[j] > base:
                j += 1
            peaks.append((x, j - 1))
            x = j + 20
        else:
            x += 4

    cands = [valley]
    if peaks:
        # 最靠右的峰(左页内容右边界候选)
        rightmost = max(peaks, key=lambda p: p[1])
        cands.append(rightmost[1])
        # 沟谷附近左右各一条
        near = [p for p in peaks if abs((p[0] + p[1]) // 2 - valley) < W * 0.10]
        if near:
            cands.append((near[0][0] + near[0][1]) // 2)
    # 去重
    out = []
    for c in cands:
        if all(abs(c - o) > 25 for o in out):
            out.append(c)
    out = sorted(out)[:4]
    while len(out) < 4:
        out.append(out[-1] + 50)
    return out, valley


def pick(img_path, verbose=True):
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    cands, valley = candidates(im)
    d = ImageDraw.Draw(im)
    for x, c in zip(cands, COLORS):
        d.line([(x, 0), (x, H)], fill=c, width=max(5, W // 700))

    # 窄带: 以候选中点为中心, 两侧各 550px; 纵向取页面 8%~70%
    mid = cands[len(cands) // 2]
    x0 = max(0, min(cands) - 550)
    x1 = min(W, max(cands) + 550)
    y0, y1 = int(H * 0.08), int(H * 0.70)
    band = im.crop((x0, y0, x1, y1))
    scale = min(1.6, 1500 / max(1, band.size[0]))
    band = band.resize((int(band.size[0] * scale), int(band.size[1] * scale)),
                       Image.LANCZOS)
    o = io.BytesIO()
    band.save(o, "JPEG", quality=92)
    data = o.getvalue()

    prompt = (
        "这是一张中文跨页书扫描件的**中间竖条**(已裁出书脊附近)。"
        "上面画了 4 条竖线, 颜色分别是:\n"
        "  红 R / 蓝 B / 绿 G / 黄 Y\n"
        "请判断**哪一条线正好落在两页之间的装订沟** —— 判据:\n"
        "  * 该线的**左边**是左页的内容(左页表格最右边框应当正好终止于该线附近)\n"
        "  * 该线的**右边**是右页的内容(右页表格的左边框应当正好始于该线附近)\n"
        "  * 切在别的线上会切掉左页表格的最后一列, 或把右页的内容切进来\n"
        "请只回答一个字母(R/B/G/Y)加一句理由。"
    )
    raw = api_ocr(data, prompt)
    m = re.search(r"\b([RBGY])\b", raw)
    pc = m.group(1) if m else None
    idx = NAMES.index(pc) if pc in NAMES else 1
    chosen = cands[idx]
    if verbose:
        print(f"  候选 {cands} 沟谷 {valley} -> 选 {pc} = {chosen}")
        print("  ", raw.strip().replace("\n", " ")[:160])
    return chosen, cands, pc, valley


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p)
        pick(p)
