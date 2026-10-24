#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨页扫描件的书脊定位: 多候选 + OCR 反馈选优。

【为什么需要 OCR 反馈】
纯图像算法在 8 张实测图上错过 3 张(0255 差 484px / 0155 差 761px / 0245 差 561px)。
根因: 扫描件两页内容**紧贴**, 页边没有白沟, 也没有可靠的页框线,
      「最靠右的竖线」「剖面见底」都会命中**页面内部的表格竖线**。

【可靠判据: 切错位会切掉内容, 而内容缺失在 OCR 结果里看得见】
切分点太靠右 -> 左页表格第一列被切掉 -> OCR 输出的表头/标题**残缺**
              (实测 0245: 正确是「进口饲料添加剂目录」, 切 2918 后变成「口饲料添加剂目录」)
切分点太靠左 -> 对页文字串进来 -> OCR 结果里出现对页的**页眉或正文**
所以: 生成 3~5 个候选切点, 每个切点送一次 OCR, 用「内容完整性」打分选最好的。

【打分项(都基于 OCR 输出)】
  1) 表头/标题里出现**半截中文** -> 扣分(左列被切)
     判据: 标题首字符不是常见的「一/二/三/四/五/六/附/表/第」且后面紧跟
           「饲料/目录/品种/一览/清单」等词 -> 疑似被切
  2) 出现**对页页眉** -> 大幅扣分
  3) 列数与行数一致性 -> 加分
"""
import base64
import io
import json
import os
import re
import sys

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import _spine

RE_HDR = re.compile(r"(?:<<<\s*[一二三四五六]、|饲料法规文件\s*[（(]\s*20\d\d\s*[)）]|"
                    r"制度文件\s*[|｜]\s*\d{1,4})")
# 半截中文: 标题首字是「不可能作词首」的字 —— 即原词被切掉了前缀。
# 实测 0245: 正确是「进口饲料添加剂目录」, 切多了变成「口饲料添加剂目录」。
# 「口」不可能是「目录/品种」类词的首字, 所以它是可靠的截断信号。
# 坑: 正则必须**紧跟标签的 > 之后**, 不能用 (?:^|>) —— 那样会匹配到上一个标签的
#     结束符, 导致正常标题(如「进口饲料添加剂目录」的「进」)也被误判。
RE_TRUNC = re.compile(r">\s*(口|们|目|斤|刀|卜|上|下)(?=[一-鿿]{1,6}"
                      r"(?:目录|品种|一览|清单|表|说明|标准|规范))")


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=16000, timeout=150):
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


TABLE_PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **页面上方若有居中的表标题(如「表1 猪」「进口饲料添加剂目录」), "
    "必须作为表格第一行输出, 用 <th colspan=\"N\">标题文字</th>, 严禁丢失, "
    "也严禁只输出标题的后半截**\n"
    "3. 保持原表列顺序, 合并单元格用 colspan/rowspan 表达\n"
    "4. **即使某列整列为空也必须输出该列**, 不能省略\n"
    "5. 单元格内的换行合并进同一个单元格, 不要拆成多行; "
    "带下划线的填空处(如 名称：______)照原样输出下划线\n"
    "6. 页眉、页码、书名不要输出\n"
    "7. 只输出表格本身, 不要任何解释文字, 不要输出 LaTeX"
)


def clean(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    txt = re.sub(r"```[a-zA-Z]*\n?", "", txt)
    txt = re.sub(r"\n```\s*$", "", txt)
    txt = re.sub(r"^(图像中的文字如下[：:]?|图片中识别出的文字如下[：:]?|"
                 r"图片里检测到的文字如下[：:]?)\s*", "", txt.strip())
    return txt.strip()


def prep_bytes(img, target_w=1900):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


def gen_candidates(img, n=6):
    """生成候选切点。

    坑: 候选**必须覆盖足够宽的范围**。早先只在算法基线附近取 ±2 步(±4% 页宽),
    而算法基线本身可能偏 500px(实测 0255 偏 484px), 于是正确答案根本不在候选里。
    现在: 以「沟谷」为中心, 在 ±12% 页宽范围内均匀取 n 个候选,
    再把算法基线/白沟中点/尖峰右沿也加进去。
    """
    cc, H, W = _spine._profile(img)
    base, why = _spine.find_spine(img)

    # 沟谷(用暗像素剖面最小值, 作为「书脊大致位置」的锚)
    k = max(3, W // 400)
    sm = np.convolve(cc, np.ones(k) / k, mode="same")
    lo, hi = int(W * 0.34), int(W * 0.70)
    valley = lo + int(np.argmin(sm[lo:hi]))

    cands = []
    span = int(W * 0.12)
    for i in range(n):
        cands.append(valley - span + (2 * span) * i // max(1, n - 1))
    cands += [base, valley]
    z, _ = _spine.find_zero_gap(cc, W)
    if z:
        cands.append(z)
    b, _ = _spine.find_border_spike(cc, W)
    if b:
        cands.append(b)

    out = []
    for c in cands:
        c = int(max(200, min(W - 200, c)))
        if all(abs(c - o) > 25 for o in out):
            out.append(c)
    out.sort()
    return out, base, why


def score(raw):
    """给 OCR 结果打分(越大越好)"""
    if "<table" not in raw.lower():
        return -100, "无表"
    tabs = re.findall(r"<table.*?</table>", raw, re.S | re.I)
    rows = len(re.findall(r"<tr", raw, re.I))
    cells = len(re.findall(r"<t[dh][ >]", raw, re.I))
    s = 0
    why = []
    s += rows * 2 + len(tabs) * 10
    # 格子数: 切点太靠右会切掉一整列 -> 格子数明显变少。
    # 所以格子数参与打分, 让「切得准(内容全)」的候选胜出。
    s += min(30, cells // 3)
    if RE_HDR.search(raw):
        s -= 60
        why.append("串页页眉")
    if RE_TRUNC.search(raw):
        s -= 40
        why.append("标题被切")
    # 列完整性: 数据行的列数必须一致
        # 坑: **标题行(第1行)的格数天然与数据行不同**(标题跨全部列, 1 个 <td colspan=N>),
        #     所以列宽一致性检查必须**跳过标题行**, 否则每张表都被扣分。
        # 坑 2: **列数本身要参与打分** —— 实测 0255 切点 2876 时表格只剩 2 列
        #     (定义 | 常用名称), 丢了「编号」「加工工艺」两列, 但因为拆成了 2 张表
        #     而拿到「2表」加分, 反而胜出。所以列数越多越好。
        from collections import Counter
        max_cols = 0
        for tb in tabs:
            trs = re.findall(r"<tr[^>]*>(.*?)</tr>", tb, re.S | re.I)
            widths = []
            for tr in trs:
                cells_in = re.findall(r"<t[dh][^>]*>", tr, re.I)
                if not cells_in:
                    continue
                # 标题行: 只有 1 个格 且 带 colspan -> 跳过
                if len(cells_in) == 1 and re.search(r'colspan\s*=\s*["\']?\s*([2-9])',
                                                  tr, re.I):
                    continue
                widths.append(len(cells_in))
            if widths:
                max_cols = max(max_cols, max(widths))
            if len(widths) >= 2:
                wc = Counter(widths)
                if len(wc) > 1:
                    s -= 25
                    why.append(f"列宽不齐{sorted(wc)}")
                else:
                    s += 12
        s += max_cols * 8          # 列数越多越好(切太靠右会丢列)
    # 空单元格率
    allc = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw, re.S | re.I)
    if allc:
        empty = sum(1 for c in allc
                    if not re.sub(r"<[^>]+>|\s|&nbsp;", "", c).strip())
        er = empty / len(allc)
        if er > 0.6:
            s -= 30
            why.append(f"空单元率{er:.2f}")
        else:
            s += 10 - er * 10
    why.append(f"{len(tabs)}表/{rows}行/{cells}格")
    return s, ",".join(why)


def pick_cut(img_path, verbose=True, n_cand=4):
    """返回 (best_cut, best_raw, 全部候选结果)"""
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    cands, base, why = gen_candidates(im, n_cand)
    if verbose:
        print(f"  候选 {cands} (算法基线 {base}: {why})")
    results = []
    for c in cands:
        page = im.crop((c, 0, W, H))
        try:
            raw = clean(api_ocr(prep_bytes(page), TABLE_PROMPT))
        except Exception as e:
            if verbose:
                print(f"    cut={c}: API 失败 {e}")
            continue
        s, d = score(raw)
        results.append((s, c, raw, d))
        if verbose:
            print(f"    cut={c}: score={s:+.0f}  {d}")
    if not results:
        return None, None, []
    results.sort(key=lambda r: -r[0])
    best = results[0]
    if verbose:
        print(f"  -> 选中 cut={best[1]} (score={best[0]:+.0f})")
    return best[1], best[2], results


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(p)
        pick_cut(p)
