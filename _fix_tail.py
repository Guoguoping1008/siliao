#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收尾修复最后几页退化(0911/0847/0848/0931/0950)。

这 5 页是全库扫描后剩下的:
  0911  裸 LaTeX \\begin{table}...\\begin{tabular}      -> 表 + 下面还有正文(附件2)
  0847  Markdown 管道表但**全挤在一行**(无换行)          -> 表
  0848  同上                                            -> 表
  0931  整页压平                                        -> 表
  0950  正文页被当成 1 列表                               -> 正文

所以要**按页选提示词**: 表页用表格提示词, 正文页用散文提示词。
0911 是「表 + 正文」混合页 -> 切两段分别送 API。
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
import _spine_pick

TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")

TABLE_PROMPT = _spine_pick.TABLE_PROMPT
PROSE_PROMPT = (
    "请把这张中文书页扫描件转写成 Markdown 正文。要求:\n"
    "1. **这一页是正文, 不是表格**。绝对不要输出 HTML 表格, 不要用竖线或表格边框。\n"
    "2. 逐段转写正文文字, 保持原段落划分。\n"
    "3. 页眉(形如「<<< 三、相关法律法规文件 847」)、页码、书名一律不要输出。\n"
    "4. 标题保留原编号文字, 作为独立一行输出, 不要加 Markdown 标记。\n"
    "5. 不要加任何解释性文字, 只输出页面正文内容。"
)


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=20000, timeout=150):
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


def prep(img, target_w=1900):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=92)
    return o.getvalue()


def best_cut(im, n=7):
    """多候选 + OCR 反馈选切点(表格页用)"""
    from concurrent.futures import ThreadPoolExecutor
    cands, base, why = _spine_pick.gen_candidates(im, n=n)
    print(f"    候选 {cands}")

    def run(c):
        page = im.crop((c, 0, im.size[0], im.size[1]))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page), TABLE_PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {e}")
        s, d = _spine_pick.score(raw)
        return (s, c, raw, d)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for r in ex.map(run, cands):
            if r is None:
                continue
            s, c, raw, d = r
            print(f"      cut={c}: score={'%+d' % s if s is not None else 'ERR'} {d}")
            if raw is not None:
                results.append(r)
    if not results:
        return None, None
    results.sort(key=lambda r: -r[0])
    return results[0][1], results[0][2]


def table_page(md_path, src, src_rel, is_right=True):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    from concurrent.futures import ThreadPoolExecutor
    cands, base, why = _spine_pick.gen_candidates(im, n=7)
    print(f"    候选 {cands}")

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page), TABLE_PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {e}")
        s, d = _spine_pick.score(raw)
        return (s, c, raw, d)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for r in ex.map(run, cands):
            if r is None:
                continue
            s, c, raw, d = r
            print(f"      cut={c}: score={'%+d' % s if s is not None else 'ERR'} {d}")
            if raw is not None:
                results.append(r)
    if not results:
        print("  全部候选失败")
        return False
    results.sort(key=lambda r: -r[0])
    cut, raw = results[0][1], results[0][2]
    print(f"  -> cut={cut}")
    body = (f"<!-- source: {src_rel} -->\n"
            f"<!-- repaired: rotated=no, method=api-minimax -->\n\n"
            f"{raw.strip()}\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  已写 {os.path.relpath(md_path, REPO)}")
    return True


def prose_page(md_path, src, src_rel, is_right=True):
    """正文页: 多候选 + 用「是否含表格/页眉」打分选切点"""
    from concurrent.futures import ThreadPoolExecutor
    im = Image.open(src).convert("RGB")
    W, H = im.size
    cands, base, why = _spine_pick.gen_candidates(im, n=7)
    print(f"    候选 {cands}")

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page, 1700), PROSE_PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {e}")
        # 打分: 正文越长越好; 含表格/页眉要扣分
        s = len(raw)
        if "<table" in raw.lower():
            s -= 3000
        if _spine_pick.RE_HDR.search(raw):
            s -= 3000
        npara = len([l for l in raw.split("\n") if l.strip()])
        s += npara * 20
        return (s, c, raw, f"{npara}行/{len(raw)}字")

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for r in ex.map(run, cands):
            if r is None:
                continue
            s, c, raw, d = r
            print(f"      cut={c}: score={'%+d' % s if s is not None else 'ERR'} {d}")
            if raw is not None:
                results.append(r)
    if not results:
        print("  全部候选失败")
        return False
    results.sort(key=lambda r: -r[0])
    s, c, raw, d = results[0]
    print(f"  -> cut={c} score={s:+.0f}")
    body = (f"<!-- source: {src_rel} -->\n"
            f"<!-- repaired: rotated=no, method=api-minimax, kind=prose -->\n\n"
            f"{raw.strip()}\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  已写 {os.path.relpath(md_path, REPO)}")
    return True


def mixed_page(md_path, src, src_rel, split_y, is_right=True):
    """「表 + 正文」混合页: 上半表, 下半正文"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    from concurrent.futures import ThreadPoolExecutor
    cands, base, why = _spine_pick.gen_candidates(im, n=7)
    print(f"    候选 {cands}")

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page), TABLE_PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {e}")
        s, d = _spine_pick.score(raw)
        return (s, c, raw, d)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for r in ex.map(run, cands):
            if r is None:
                continue
            s, c, raw, d = r
            print(f"      cut={c}: score={'%+d' % s if s is not None else 'ERR'} {d}")
            if raw is not None:
                results.append(r)
    if not results:
        print("  表格部分失败")
        return False
    results.sort(key=lambda r: -r[0])
    cut, raw = results[0][1], results[0][2]
    print(f"  -> cut={cut}")
    page = im.crop((cut, 0, W, H)) if is_right else im.crop((0, 0, cut, H))
    # 找表的下边框(长横线)
    a = np.asarray(page.convert("L"), dtype=np.uint8)
    hh = page.size[1]
    reg = (a[int(hh * 0.10):int(hh * 0.85)] < 150)
    rows = reg.sum(axis=1)
    cand = [y for y in range(reg.shape[0]) if rows[y] > page.size[0] * 0.55]
    if cand:
        tbl_bottom = int(hh * 0.10) + max(cand)
    else:
        tbl_bottom = int(hh * split_y)
    print(f"  表下边框 y≈{tbl_bottom} (页高 {hh})")
    tbl_img = page.crop((0, 0, page.size[0], min(tbl_bottom + 40, hh)))
    pro_img = page.crop((0, max(0, tbl_bottom - 20), page.size[0], hh))
    try:
        prose = clean(api_ocr(prep(pro_img, 1700), PROSE_PROMPT))
    except Exception as e:
        prose = ""
        print(f"  正文 OCR 失败: {e}")
    body = (f"<!-- source: {src_rel} -->\n"
            f"<!-- repaired: rotated=no, method=api-minimax -->\n\n"
            f"{raw.strip()}\n\n{prose.strip()}\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  已写 {os.path.relpath(md_path, REPO)}")
    return True


M = os.path.join(REPO, "minimax")


def main():
    jobs = [
        # (md 相对路径, 源图, 是否右半, 模式)
        ("03相关法律法规文件/05_（五）转基因管理/29_农业转基因生物（植物、动物、动物用微生物）安全评价指南/0911.md",
         "Images/03相关法规法律法规文件/0911.jpg", True, "mixed"),
        ("03相关法律法规文件/04_（四）兽药管理/14_关于发布《进口兽药管理目录》的公告/0847.md",
         "Images/03相关法规法律法规文件/0847.jpg", True, "table"),
        ("03相关法律法规文件/04_（四）兽药管理/14_关于发布《进口兽药管理目录》的公告/0848.md",
         "Images/03相关法规法律法规文件/0849.jpg", False, "table"),
        ("03相关法律法规文件/06_（六）水产养殖管理/31_农业农村部关于加强水产养殖用投人品监管的通知/0931.md",
         "Images/03相关法规法律法规文件/0931.jpg", True, "table"),
        ("04标准及标准目录/02_饲料卫生标准/0950.md",
         "Images/04标准及标准目录/0951.jpg", True, "prose"),
    ]
    for rel, src_rel, is_right, mode in jobs:
        md = os.path.join(M, rel)
        src = os.path.join(REPO, src_rel)
        if not os.path.exists(src):
            print(f"!! 缺源图 {src}")
            continue
        print(f"\n=== {os.path.basename(md)} ({mode}) ===")
        if mode == "table":
            table_page(md, src, src_rel, is_right)
        elif mode == "prose":
            prose_page(md, src, src_rel, is_right)
        else:
            mixed_page(md, src, src_rel, split_y=0.62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
