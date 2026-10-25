#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 1001 —— 饲料产品标准和检测方法标准目录(检测方法标准, 续)。

【页面映射(先读页码确认)】
Images/04标准及标准目录/1001.jpg = 书第 1000(左) + 1001(右)
  页眉右上角印着「四、标准及标准目录 | 1001」-> 确认 1001 = **页1001** = 右半
  书脊 x≈2100, 切点 cut=2100

【原状态(3761B)—— 从第 236 行起内容全错】
  序号 230~235 正确, 但 **236~258 全是「饲料中钙的测定」**(23 行重复),
  而原图这些行的标准名称各不相同(硒/钴/锌/牛羊源性成分/伏马毒素/黄曲霉毒素/
  玉米赤霉烯酮/T-2毒素/烟酰胺/山梨酸/维生素B6/罗丹明B/添加剂/有机铬/叶酸/
  斑蝥黄/β-阿朴-8'-胡萝卜素/串珠鞭毛藻素/氨基酸/动物源性成分/调味剂/香芹酚/
  艾戈美酮)。
  另外行232 把「苯乙醇**二**胺」读成了「苯乙醇胺**A**」。

【页面是**倾斜**的】页面上有明显的斜切, 序号列与标准名称列**上下错开半行**。
  -> 配对要靠**标准编号**(每行唯一且规整), 不能靠横向对齐。

【原图结构】3 列: 序号 | 标准编号 | 标准名称
  - 表头**只有 1 行**; 「（续表）」在**标准名称表头格内**(右对齐)
  - 序号列实测: **230 ~ 258**, 共 29 行
  - 每行 3 格

【对策】用 API 专门重读(倾斜页它比目视稳), 再:
  1. 用**序号列**独立裁图确认 230~258 的区间
  2. 质量门: 序号连续 + 每行 3 格 + 标准编号不得重复
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

OUTDIR = os.path.join(REPO, "minimax", "04标准及标准目录",
                      "05_饲料产品标准和检测方法标准目录")
CUT = 2100
CONT = "（续表）"

PROMPT = (
    "请把这张中文**标准目录**扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>\n"
    "2. 本目录表是 **3 列**: 序号 | 标准编号 | 标准名称\n"
    "3. **这一页是倾斜扫描的**, 序号列与标准名称列上下错开约半行。"
    "请**按标准编号**来配对(每行一个标准编号, 标准名称就是该编号对应的那条),\n"
    "   **绝对不要**把上一行/下一行的标准名称配到本行\n"
    "4. 「（续表）」印在**表上边框之内、标准名称列的上方**, 请作为**表头行"
    "「标准名称」单元格里的一行文字**输出(写在「标准名称」后面, 换行或空格分隔)\n"
    "5. **每行都必须有 3 个格子**, 序号列不能漏, **一行只能有一项标准**\n"
    "6. 标准编号原样保留(含全角破折号「—」), 标准名称原样保留\n"
    "7. **同一个标准名称不要重复抄多行** —— 每行内容都不同\n"
    "8. 页眉、页码、书名不要输出\n"
    "9. 只输出表格本身, 不要任何解释文字\n"
    "10. **不要省略任何一行**; 宁可多输出也不要漏"
)


def api_ocr(img_bytes, prompt, model="MiniMax-Text-01", max_tokens=24000, timeout=300):
    import mm_ocr
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,"
                 + img_bytes}},
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


def clean(raw):
    t = raw.strip()
    t = re.sub(r"^```(?:html)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    t = re.sub(r"(?m)^.*?饲料法规文件.*?$", "", t)
    t = re.sub(r"(?m)^.*?四、标准及标准目录.*?$", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def td(v="", attrs="", tag="td"):
    a = (" " + attrs) if attrs else ""
    return "<%s%s>%s</%s>" % (tag, a, v, tag)


def tr(cells):
    return "<tr>%s</tr>" % "".join(cells)


def build(rows):
    out = ['<table border="1">']
    out.append(tr([td("序号", tag="th"), td("标准编号", tag="th"),
                   td("标准名称<br>" + CONT, tag="th")]))
    for r in rows:
        out.append(tr([td(c) for c in r]))
    out.append("</table>")
    out.append("")
    return "\n".join(out)


MUST = [
    "NY/T 1619—2008", "饲料中甜菜碱的测定",
    "NY/T 1757—2009", "苯并二氮杂卓类药物",
    "NY/T 1944—2010", "饲料中钙的测定",
    "NY/T 1970—2010", "饲料中伏马毒素的测定",
    "NY/T 1946—2010", "牛羊源性成分检测",
    "NY/T 1945—2010", "饲料中硫的测定",
    "NY/T 3139—2017", "饲料中左旋咪唑的测定",
]

MUST_NOT = [
    "#### ",
        "(续表)",        # 半角
]


def check(txt):
    errs = []
    for k in MUST:
        if k not in txt:
            errs.append("缺: " + k)
    for k in MUST_NOT:
        if k in txt:
            errs.append("不应出现: " + k)
    if txt.count("<table") != 1:
        errs.append("表数 != 1")
    m = re.findall(r"<table.*?</table>", txt, re.S)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", m, re.S)
    for i, r in enumerate(rows, 1):
        tags = re.findall(r"<t[dh]([^>]*)>", r)
        width = 0
        for a in tags:
            mc = re.search(r'colspan="(\d+)"', a)
            width += int(mc.group(1)) if mc else 1
        if width != 3:
            errs.append("第 %d 行展开后列数 != 3, 实际 %d" % (i, width))
    nums, codes, names = [], [], []
    for r in rows:
        cs = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if cs and re.fullmatch(r"\d+", cs[0]):
            nums.append(int(cs[0]))
            codes.append(cs[1])
            names.append(cs[2])
    if not nums:
        errs.append("无数据行")
        return errs
    if nums[0] != 230:
        errs.append("起始序号 != 230, 实际 %d" % nums[0])
    if nums[-1] != 258:
        errs.append("结束序号 != 258, 实际 %d" % nums[-1])
    for a, b in zip(nums, nums[1:]):
        if b != a + 1:
            errs.append("序号不连续: %d -> %d" % (a, b))
    # 标准编号不得重复
    dup = [c for c in set(codes) if codes.count(c) > 1]
    if dup:
        errs.append("标准编号重复: %s" % dup)
    # 标准名称不得大量重复(原 md 就是 23 行重复"钙的测定")
    from collections import Counter
    cnt = Counter(names)
    worst = cnt.most_common(1)[0]
    if worst[1] > 3:
        errs.append("标准名称重复过多: %r 出现 %d 次" % (worst[0], worst[1]))
    return errs


def main():
    from PIL import Image
    p = os.path.join(REPO, "Images", "04标准及标准目录", "1001.jpg")
    im = Image.open(p)
    W, H = im.size
    page = im.crop((CUT, 0, W, H))
    b = io.BytesIO()
    page.convert("RGB").save(b, "JPEG", quality=95)
    raw = clean(api_ocr(base64.b64encode(b.getvalue()).decode("ascii"), PROMPT))
    rows = []
    for m in re.findall(r"<tr>(.*?)</tr>", raw, re.S):
        cs = re.findall(r"<td[^>]*>(.*?)</td>", m, re.S)
        if len(cs) == 3 and re.fullmatch(r"\d+", cs[0].strip()):
            rows.append((cs[0].strip(), cs[1].strip(), cs[2].strip()))
    # 目视纠正: NY/T 1945—2010 = 饲料中**硫**的测定(API 读成了"磷")
    rows = [(a, b, ("饲料中硫的测定 微分溶解-原子荧光光谱法"
                    if b == "NY/T 1945—2010" else c))
            for (a, b, c) in rows]
    txt = build(rows)
    errs = check(txt)
    if errs:
        print("!! 1001 质量门未过:")
        for e in errs:
            print("   -", e)
        print("  解析到 %d 行" % len(rows))
        return 1
    out = os.path.join(OUTDIR, "1001.md")
    open(out, "w", encoding="utf-8").write(txt)
    print("OK 1001 -> %s (%d 字节, 1 表, %d 行)" %
          (os.path.relpath(out, REPO), len(txt.encode("utf-8")), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
