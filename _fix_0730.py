#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0730 —— **页730 是纯正文**(文档首页), 原 md 把标题层级压平了。

【页面映射(先读页码确认)】
Images/02制度文件/0729.jpg = 书第 728(左) + 729(右)   <- 另一份文件
Images/02制度文件/0731.jpg = 书第 730(左) + 731(右)
  -> 0730 = **页730** = 0731.jpg 的左半
  书脊(最暗带) x≈2120~2160, 页730 文字右边界 ~2100 -> cut=2110

【原状态(标题层级被压平)】
0730.md 2744B —— 章节标题和正文**粘在一起**:
  「一、充分认识发展农业产业化联合体的重要意义农业产业化联合体是龙头企业、
    农民合作社和家庭农场等新型农业经营主体以分工协作为前提…」
  缺标题分级、缺文号行、缺主送机关的分行、缺 (一)(二)(三)(四) 的段落结构。

【做法】走 API 读正文(提示词明确「没有表格, 只输出正文, 保留标题层级」),
      再目视核对。

【页730 结构】
  标题 关于促进农业产业化联合体发展的指导意见
  文号 农经发〔2017〕9 号
  主送 (4 行) 各省、自治区、直辖市及新疆生产建设兵团农业（农牧、农村经济、农村工作）
        厅（局、委）、发展改革委、财政厅（局）、国土资源厅（局），中国人民银行上海
        总部、各分行、营业管理部、各省会（首府）城市中心支行，各省、自治区、
        直辖市及新疆生产建设兵团国家税务局、地方税务局:
  正文 当前，我国农业农村发展进入新阶段。…现提出以下意见。
  一、充分认识发展农业产业化联合体的重要意义
  （一）有利于构建现代农业经营体系。…
  （二）有利于推进农村一二三产业融合发展。…
  （三）有利于提高农业综合生产能力。…
  （四）有利于提高农业综合竞争力。…
  二、准确把握农业产业化联合体的基本特征
  （一）独立经营，联合发展。…
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

import mm_ocr

OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "09_（九）行业规划和政策",
                      "138_关于促进农业产业化联合体发展的指导意见")
SRC = os.path.join(REPO, "Images", "02制度文件", "0731.jpg")

CUT = 2110

PROMPT = (
    "请把这张中文**公文扫描页**转写成 Markdown, 要求极其严格:\n"
    "1. **这一页没有表格**, 只输出正文段落。绝对不要输出 <table> 或任何表格标记。\n"
    "2. **逐字抄写**, 不要改写、不要摘要、不要合并段落、不要纠正原文。\n"
    "3. **保留标题层级**, 用 Markdown 标题标记:\n"
    "   - 文件标题 -> `# `\n"
    "   - 文号(如 农经发〔2017〕9 号) -> 单独一行, 用 **粗体**\n"
    "   - 一、二、三… 级标题 -> `## `\n"
    "   - （一）（二）… 级标题 -> `### `\n"
    "   **关键: 标题必须单独成行, 后面不要接正文, 正文另起一段。**\n"
    "4. 主送机关单独成段(可以跨行, 但要合并成一个段落)。\n"
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


def check(txt):
    errs = []
    if "<table" in txt:
        errs.append("页730 是正文页, 不该有 <table>")
    for bad in ("并不是表格格式", "无法将其转换为HTML表格",
                "以下是转换后的 HTML 表格代码", "<td colspan"):
        if bad in txt:
            errs.append("残留模型痕迹: " + bad[:18])
    for k in ("关于促进农业产业化联合体发展的指导意见",
              "农经发〔2017〕9号",
              "各省、自治区、直辖市及新疆生产建设兵团农业（农牧、农村经济、农村工作）",
              "发展改革委、财政厅（局）、国土资源厅（局）",
              "中国人民银行上海总部",
              "国家税务局、地方税务局",
              "当前，我国农业农村发展进入新阶段",
              "现提出以下意见",
              "## 一、充分认识发展农业产业化联合体的重要意义",
              "### （一）有利于构建现代农业经营体系",
              "### （二）有利于推进农村一二三产业融合发展",
              "### （三）有利于提高农业综合生产能力",
              "### （四）有利于促进农民持续增收",
              "## 二、准确把握农业产业化联合体的基本特征",
              "### （一）独立经营，联合发展"):
        if k not in txt:
            errs.append("缺: " + k[:26])
    # 标题不能和正文粘在一起
    for h in ("一、充分认识发展农业产业化联合体的重要意义",
              "二、准确把握农业产业化联合体的基本特征"):
        if (h + "农业") in txt or (h + "产业化") in txt:
            errs.append("标题和正文粘在一起了: " + h[:12])
    if len(txt.encode("utf-8")) < 1800:
        errs.append("内容过短(%d 字节)" % len(txt.encode("utf-8")))
    return errs


def main():
    im = Image.open(SRC).convert("RGB")
    W, H = im.size
    cands = [CUT - 40, CUT, CUT + 40]

    def run(c):
        page = im.crop((0, 0, c, H))
        raw = clean(api_ocr(prep(page), PROMPT))
        return (c, raw)

    results = []
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        for c, raw in ex.map(run, cands):
            errs = check(raw)
            print("  cut=%d  字节=%d  errs=%s" % (c, len(raw.encode()), errs[:3] or "无"))
            results.append((len(errs), c, raw))
    results.sort(key=lambda r: r[0])
    best = results[0]
    print("  -> 选中 cut=%d (errs=%d)" % (best[1], best[0]))
    out = os.path.join(OUTDIR, "0730.md")
    with open(out + ".draft", "w", encoding="utf-8") as f:
        f.write("<!-- source: Images/02制度文件/0731.jpg (split: 0730, 左半, cut=%d) -->\n"
                "<!-- repaired: rotated=no, method=api-minimax, form=prose, no-table -->\n\n"
                % best[1] + best[2] + "\n")
    print("  草稿已写 0730.md.draft")

    # 用选中的 cut 重新出一遍, 写成正式文件
    best_c = best[1]
    page = im.crop((0, 0, best_c, H))
    raw = clean(api_ocr(prep(page), PROMPT))
    errs = check(raw)
    if errs:
        print("!! 质量门未过: %s" % "; ".join(errs[:6]))
        return 1
    out = os.path.join(OUTDIR, "0730.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("<!-- source: Images/02制度文件/0731.jpg (split: 0730, 左半, cut=%d) -->\n"
                "<!-- repaired: rotated=no, method=api-minimax, form=prose, no-table -->\n\n"
                % best_c + raw + "\n")
    os.remove(out + ".draft")
    print("OK 0730 -> %s (%d 字节, 0 表)" %
          (os.path.relpath(out, REPO), len(raw.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
