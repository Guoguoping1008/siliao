#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「被误当成表格」的正文页重新 OCR 成散文。

【缺陷类(第 5 类退化)】
模型把**正文页**输出成「一段一句、每句一个 <tr><td>」的伪表格。
成因: 正文页本身没有表, 但模型的 HTML 表格提示词诱导它把每个版面行当成一个表格行。
特征: 表格只有 1 列, 或列数=1 而内容全是长段落。

实测样本:
  0074.md  纯正文(4.4 观察与检测 ~ 5.2)  -> 32 个单列 <tr>
  0075.md  正文(5.3 A-K 列表 / 5.4 / 6 资料存档) + 附录A 真表 -> 正文被包成表

【做法】
正文页改用**普通 OCR 提示词**(输出 Markdown 正文, 不要表格),
真表再单独用表格提示词处理或直接手工落 HTML。
本页脚手架: 一页可能 = 正文 + 末尾一张真表 -> 分两段处理。

【语料格式约定(照 0073.md 等正常页对齐)】
  ## <一级标题>      例: ## 4 试验方法
  ### <二级标题>     例: ### 4.1 受试物
  编号条款(4.1.1 / 4.4.3.1)保持纯段落, 不加标记
  页面顶部: <!-- source: ... --> + <!-- repaired: ... -->
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

TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
DOC_DIR = os.path.join(REPO, "minimax", "02制度文件", "01_（一）新产品审定",
                       "11_饲料和饲料添加剂水产靶动物耐受性评价试验指南（试行）")

TARGET_W = 1600
RETRY = 5

PROSE_PROMPT = (
    "请把这张中文书页扫描件转写成 Markdown 正文。要求:\n"
    "1. **这一页是正文, 不是表格**。绝对不要输出 HTML 表格, 不要用竖线或表格边框。\n"
    "2. 逐段转写正文文字, 保持原段落划分。段首缩进的段落各自独立成段, 用空行分隔。\n"
    "3. 页眉(形如「饲料法规文件 (2023) >>>」「<<< 三、制度文件 75」)、页码、书名一律不要输出。\n"
    "4. 章节标题保留原编号文字, 例如「4.4 观察与检测」「4.4.1 临床观察」「5 试验报告」, "
    "作为独立一行输出, 不要加 Markdown 标记。\n"
    "5. 编号条款(如 4.4.2、4.4.3.1)后面跟正文, 保持同一行。\n"
    "6. 字母编号列表(如 A. 试验名称; B. 摘要;)按原样逐行输出。\n"
    "7. 不要加任何解释性文字, 不要加引号, 只输出页面正文内容。"
)

TABLE_PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格。要求:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. 保持原表列顺序, 合并单元格用 colspan/rowspan 表达\n"
    "3. 单元格内的换行合并进同一个单元格, 不要拆成多行\n"
    "4. 页眉、页码、书名, 以及表格上方的**章节标题和表题**(如「附录 A」"
    "「水产靶动物种类、试验期和动物数量」)一律不要输出, 只输出表格本身\n"
    "5. **只输出表格本身, 不要任何解释文字**"
)


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
                 r"图片里检测到的文字如下[：:]?|识别结果如下[：:]?|以下是图片中的文字[：:]?)\s*",
                 "", txt.strip())
    return txt.strip()


def prep_bytes(img, target_w=TARGET_W):
    im = img.convert("RGB")
    W, H = im.size
    if W > target_w:
        im = im.resize((target_w, max(1, int(H * target_w / W))), Image.LANCZOS)
    o = io.BytesIO()
    im.save(o, "JPEG", quality=90)
    return o.getvalue()


HEADER_NOISE = re.compile(r"(饲料法规文件|制度文件|相关法规法律法规文件|标准及标准目录|"
                          r"<<<?|>>>?|\(\s*20\d\d\s*\)|\d{1,4})")


def looks_like_prose(txt):
    """判断 OCR 输出是不是散文(而不是伪表格)。

    坑: **模型有时把整页正文压成一行**(没有换行)。实测 0075 的散文
    就是一行。所以不能只看「行数」, 要看「去掉页眉噪声后还剩多少字」。
    """
    if "<table" in txt.lower():
        return False
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    if not lines:
        return False
    # 竖线开头的行 -> 表格
    if sum(1 for l in lines if l.startswith("|")) >= len(lines) * 0.3:
        return False
    # 去掉页眉噪声后要剩下足够的正文
    body = [l for l in lines if not HEADER_NOISE.fullmatch(l.strip())]
    body = [l for l in body if l.strip("<>《》 　") != ""]
    if not body:
        return False
    nchars = sum(len(l) for l in body)
    return nchars >= 200


def normalize_headings(txt):
    """按语料约定补 Markdown 标题标记。

    语料约定(照 08_ 耐受性指南的正常页对齐):
      ## <一级>   例: ## 5 试验报告 / ## 6 资料存档
      ### <二级>  例: ### 4.4 观察与检测
      编号条款(4.1.1 / 5.4 / 5.1 试验报告应提供...)保持纯段落, 不加标记

    坑 1: **「N.M 标题 + 正文」同一行**的情况不能当标题。
      实测 0074 的「5.1 试验报告应提供试验获取的所有数据, ...」是**条款**, 不是标题 ——
      加了 ### 会把整段正文吞进标题, 破坏目录结构。
      判据: 标题必须**短且不含句读**(逗号/句号/分号/冒号)。否则是条款。

    坑 2: 模型有时把整页正文压成一行(无换行), 所以先按编号条款切开。
    """
    lines = txt.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            out.append(line)
            continue
        # 标题必须短且无句读
        def is_title(rest):
            rest = rest.strip()
            if not rest or len(rest) > 20:
                return False
            return not re.search(r"[，,。；;：:、（）()]", rest)

        m = re.match(r"^(\d+(?!\d|\.))\s+(\S.*)$", s)       # 一级: 5 试验报告
        if m and not re.match(r"^\d+\.\d", s) and is_title(m.group(2)):
            out.append(f"## {m.group(1)} {m.group(2)}")
            continue
        m = re.match(r"^(\d+\.\d+(?!\d|\.))\s+(\S.*)$", s)  # 二级: 4.4 观察与检测
        if m and not re.match(r"^\d+\.\d+\.\d", s) and is_title(m.group(2)):
            out.append(f"### {m.group(1)} {m.group(2)}")
            continue
        out.append(line)
    return "\n".join(out)


def split_flat_prose(txt):
    """模型有时把整页正文压成一行(没有换行)。按编号条款切开。

    坑: 不能简单按句号切 —— 「4.4.2 血液学检测」这种编号条款的点会被切碎。
    做法: 只在「编号条款开头」处断, 其余保留原样。
    还要能断一级标题(「5 试验报告」「6 资料存档」)—— 它们后面接的是标题+正文,
    用「数字 + 空格 + 短词」识别。

    坑 2: **一级标题和它的正文可能在同一行**(实测 0075:
      「6 资料存档  最终报告、原始记录、...」)。标题词本身很短(4 字),
      后面跟 2 个以上空格再接正文。所以要额外切一刀: 短标题 + 2+ 空格 + 正文。

    顺序很重要: **先按编号条款切, 再切「标题+正文」**。
    反过来的话, 「5.4 ... 完整性。  6 资料存档  最终报告」这一行会先被
    「标题+正文」规则切成两半, 变成「...完整性。  6 资料存档」+「最终报告...」,
    于是「6 资料存档」被粘在上一行末尾, 识别不到一级标题。
    """
    # --- 第一步: 按编号条款切(多行和单行都要做) ---
    # 坑: **不要用 \b**。`\b\d{1,2}` 在「.」和「4」之间也成立(那是词边界),
    #   所以 "4.4.1 临床观察" 会在 "4." 处切开, 留下 "4." + "4.1 临床观察" ——
    #   后面一级标题正则又把 "4." 当一级编号, 整段编号全乱。
    # 正确写法: 用 (?<![\d.]) 保证数字不从「数字/点」中间起步,
    #   用完整编号模式 \d+(?:\.\d+)* 保证贪心吃完整串, 再要求后面跟空格。
    NUM = r"\d+(?:\.\d+)*"
    parts = re.split(rf"(?=(?<![\d.]){NUM}(?!\d|\.)\s+(?=[^\d\s]))", txt)
    parts = [p.strip() for p in parts if p.strip()]
    out = []
    for p in parts:
        sub = re.split(rf"(?=(?<![\d.]){NUM}(?!\d|\.)\s)", p)
        out.extend([s.strip() for s in sub if s.strip()])
    txt = "\n".join(out) if len(out) > 1 else txt

    # --- 第二步: 切「一级标题 + 正文」(标题短 + 2+ 空格 + 正文) ---
    pat2a = r"(?m)^(" + NUM + r"(?!\d|\.)\s+\S{2,12}?)\s{2,}(?=\S)"
    pat2b = r"(" + NUM + r"(?!\d|\.)\s+\S{2,12}?)\s{2,}(?=[^\s])"
    txt = re.sub(pat2a, r"\1\n", txt)
    txt = re.sub(pat2b, r"\1\n", txt)
    return txt


def ocr_prose(img_path, tag):
    data = prep_bytes(Image.open(img_path))
    print(f"[{tag}] 送 API(散文) {len(data)//1024}KB")
    best = None
    for attempt in range(1, RETRY + 1):
        try:
            raw = clean(api_ocr(data, PROSE_PROMPT))
        except Exception as e:
            print(f"  [尝试{attempt}] API 失败: {e}")
            continue
        if not looks_like_prose(raw):
            print(f"  [尝试{attempt}] 不像散文(可能仍是表): {raw[:70]!r}")
            continue
        raw = normalize_headings(split_flat_prose(raw))
        nchars = len(raw)
        print(f"  [尝试{attempt}] OK {nchars} 字符, {len(raw.splitlines())} 行")
        if best is None or nchars > len(best):
            best = raw
        break
    return best


def ocr_table(img_path, tag):
    data = prep_bytes(Image.open(img_path), target_w=1900)
    print(f"[{tag}] 送 API(表格) {len(data)//1024}KB")
    for attempt in range(1, RETRY + 1):
        try:
            raw = clean(api_ocr(data, TABLE_PROMPT, max_tokens=20000))
        except Exception as e:
            print(f"  [尝试{attempt}] API 失败: {e}")
            continue
        if "<table" not in raw.lower():
            print(f"  [尝试{attempt}] 不含 <table>: {raw[:70]!r}")
            continue
        rows = re.findall(r"<tr", raw, re.I)
        if len(rows) < 3:
            print(f"  [尝试{attempt}] 行数不足({len(rows)})")
            continue
        print(f"  [尝试{attempt}] OK {len(rows)} 行")
        return raw
    return None


def write_page(tag, body, src_rel):
    out = os.path.join(DOC_DIR, tag + ".md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"<!-- source: {src_rel} (split: {tag}) -->\n")
        f.write("<!-- repaired: rotated=no, method=api-minimax, kind=prose -->\n\n")
        f.write(body.rstrip() + "\n")
    print(f"[{tag}] 已写 {out} ({len(body)} 字符)")


def main():
    os.makedirs(TMP, exist_ok=True)
    src = os.path.join(REPO, "Images", "02制度文件", "0075.jpg")
    im = Image.open(src)
    W, H = im.size
    CUT = 2100
    lp = os.path.join(TMP, "pg0074.jpg")
    rp = os.path.join(TMP, "pg0075.jpg")
    im.crop((0, 0, CUT, H)).save(lp, quality=95, subsampling=0)
    im.crop((CUT, 0, W, H)).save(rp, quality=95, subsampling=0)
    print(f"[split] cut@{CUT} left {CUT} / right {W-CUT}")
    src_rel = "Images/02制度文件/0075.jpg"

    # --- 0074: 纯正文 ---
    prose = ocr_prose(lp, "0074")
    if prose:
        write_page("0074", prose, src_rel)
    else:
        print("[0074] 散文 OCR 失败")

    # --- 0075: 正文 + 末尾真表 ---
    # 边界实测(放大截图逐边核对):
    #   y≈1930  「附录 A」标题
    #   y≈2075  表题「水产靶动物种类、试验期和动物数量」
    #   y≈2230  表格上边框
    #   y≈2549  表格第一道内部横线
    #   y≈3371  页面底部(有条码暗带, 不能进表)
    # 所以: 正文 = y[0,1900); 表块 = y[1900, 3200)
    p = Image.open(rp)
    w, h = p.size
    tbl_img = p.crop((0, 1900, w, 3200))
    tbl_path = os.path.join(TMP, "pg0075_tbl.jpg")
    tbl_img.save(tbl_path, quality=95, subsampling=0)
    prose_img = p.crop((0, 0, w, 1900))
    prose_path = os.path.join(TMP, "pg0075_prose.jpg")
    prose_img.save(prose_path, quality=95, subsampling=0)

    prose = ocr_prose(prose_path, "0075")
    tbl = ocr_table(tbl_path, "0075-tbl")
    if prose:
        body = prose.rstrip()
        if tbl:
            # 附录A 标题与表题在表格 crop 里, 但表格提示词要求只输出表格本身,
            # 所以这里按语料约定(## 附录 / #### 表题)补回去。
            body += "\n\n## 附录 A\n\n#### 水产靶动物种类、试验期和动物数量\n\n"
            body += tbl.strip() + "\n"
        write_page("0075", body, src_rel)
    else:
        print("[0075] 散文 OCR 失败")
    return 0


if __name__ == "__main__":
    sys.exit(main())
