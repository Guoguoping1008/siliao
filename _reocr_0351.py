#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 API 对 0351 (页351) 重新 OCR, 并与现有成品**逐字比对**。

【为什么这么做】
0351 已经是「纯正文、无表」的成品(提交 cc6b4c6), 但那份是我**目视手抄**的。
用户要求「重新OCR」, 所以这次:
  1. 走真正的 API 读一遍页351
  2. 与现有成品逐字 diff —— 手抄错了也要抓出来

【页面映射】
Images/02制度文件/0351.jpg = 书第 350(左) + 351(右)
  书脊实测 **x≈2205**(竖线最密处 2200~2210)
  页351 = 右半, 从 2205 开始切
"""
import base64
import difflib
import io
import json
import os
import re
import sys
import urllib.request

from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import mm_ocr

OUT = os.path.join(REPO, "minimax", "02制度文件", "04_（四）使用管理",
                   "49_禁止在饲料和动物饮用水中使用的药物品种目录", "0351.md")
SRC = os.path.join(REPO, "Images", "02制度文件", "0351.jpg")

CUT = 2205

PROMPT = (
    "请把这张中文**公文扫描页**转写成 Markdown, 要求极其严格:\n"
    "1. **这一页没有表格**, 只输出正文段落。绝对不要输出 <table> 或任何表格标记。\n"
    "2. **逐字抄写**, 不要改写、不要摘要、不要合并段落、不要纠正原文。\n"
    "3. 标题用 `# `, 公告机关和文号单独一行加粗。\n"
    "4. 条款「一、」「二、」…每条单独一段, 保留原有的换行和缩进层次。\n"
    "5. 页眉、页码、书脊阴影**不要输出**。\n"
    "6. 只输出正文, 不要任何解释文字, 不要 LaTeX。"
)


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=16000, timeout=300):
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
                 r"根据图片内容[，,]?\s*(以下是|下面是)[^#\n]{0,40})\s*", "", txt.strip())
    return txt.strip()


def prep(img, target_w=2400):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=93)
    return o.getvalue()


def norm(txt):
    """归一化后比较: 去空白、去 markdown 记号、去标点差异。"""
    t = re.sub(r"<!--.*?-->", "", txt, flags=re.S)
    t = re.sub(r"[#*>_`\[\]()]", "", t)
    t = re.sub(r"[\s,，。、;:：()（）《》\"'“”‘’]", "", t)
    return t


def main():
    im = Image.open(SRC).convert("RGB")
    W, H = im.size
    page = im.crop((CUT, 0, W, H))
    print("切页: x=%d..%d (%d px 宽)" % (CUT, W, W - CUT))

    raw = clean(api_ocr(prep(page), PROMPT))
    print("API 输出 %d 字符" % len(raw))
    print("含 <table>? %s" % ("是 <<< 异常" if "<table" in raw.lower() else "否"))

    cur = open(OUT, encoding="utf-8").read()
    cur_body = re.sub(r"<!--.*?-->", "", cur, flags=re.S).strip()
    api_body = raw.strip()

    # 逐字 diff(按段落)
    a = [x for x in cur_body.split("\n") if x.strip()]
    b = [x for x in api_body.split("\n") if x.strip()]
    print("\n=== 段落级 diff (现有 -> API) ===")
    same = 0
    for line in difflib.unified_diff(a, b, "现有", "API", lineterm="", n=0):
        print(line[:400])
        if line.startswith("+ ") or line.startswith("- "):
            same += 1
    if same == 0:
        print("(完全一致)")

    # 归一化后的字符级相似度
    na, nb = norm(cur_body), norm(api_body)
    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    print("\n归一化后字符相似度: %.4f  (现有 %d 字, API %d 字)" %
          (ratio, len(na), len(nb)))
    if ratio < 0.97:
        print(">>> 差异较大, 需要人工核对")
    else:
        print(">>> 基本一致")

    # 保存 API 版供比对
    with open(OUT + ".api", "w", encoding="utf-8") as f:
        f.write(api_body + "\n")
    print("API 版已存 %s.api" % os.path.basename(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
