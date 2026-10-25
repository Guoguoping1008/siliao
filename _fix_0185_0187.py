#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0185/0186/0187 的表格(空白表单)。

【原状态】
0185.md 337B —— 表1 企业基本情况塌成标签串
0186.md 1766B —— 只有表2, 缺表3
0187.md 252B —— 只有表4 的表头, 缺表5 和「注」

【页面映射】
Images/02制度文件/0185.jpg = 书第 184(左)+185(右) 页 -> 页185 = 右半
Images/02制度文件/0187.jpg = 书第 186(左)+187(右) 页 -> 页186 = 左半, 页187 = 右半

【书脊】这两张图的装订沟实测也在 **x≈2020**(放大截图看折痕阴影确认)。
算法给的 1394/1376 偏左 620px, 会把对页串进来。

【实测结构】
0185 表1 企业基本情况: 6 列网格 + 嵌套 rowspan(同 0145/0155)
0186 表2 产品基本情况: 序号|产品名称|生产能力（吨/年）|生产工艺简述
     表3 生产设备明细表（生产线____）: 「生产产品:」通栏 + 序号|设备名称|型号规格|生产厂家|出厂日期（年月）|技术性能指标
0187 表4 检验仪器明细表: 序号|仪器名称|型号规格|生产厂家|出厂日期（年月）|出厂编号|技术性能指标
     表5 主要管理技术人员及持有工种人员登记表:
         序号|姓名|职务|职称|学历|所学专业|资格证书时间、种类及编号|发证机关
     表下: 注: "证书"指管理人员、技术人员的职称证书、最高学历证书。
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

import _spine_pick

TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
OUTDIR = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                      "27_关于单一饲料生产许可申报材料要求的公告")

PROMPT = (
    "请把这张中文**表格表单扫描页**转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头/标签用 <th>)\n"
    "2. **每张表的标题(如「表1 企业基本情况」「表2 产品基本情况」"
    "「表3 生产设备明细表（生产线____）」「表4 检验仪器明细表」"
    "「表5 主要管理技术人员及持有工种人员登记表」)必须作为该表的第一行输出**, "
    "用 <th colspan=\"N\">标题文字</th>, 严禁丢失。**一页有多张表就输出多个 <table>。**\n"
    "3. **保持原表的行列数**, 绝不能因为右边是空白就少输出列。\n"
    "4. 合并单元格用 colspan/rowspan 表达:\n"
    "   - 表1: 「注册资本(万元)」与「固定资产(万元)」并排; "
    "「所属法人机构信息」「主要机构设置及人员组成」是**左侧纵向标签**(rowspan 覆盖多行); "
    "「企业简介：」整行通栏\n"
    "   - 表3: 「生产产品：」是整行通栏的一行\n"
    "   - 表5: 「资格证书时间、种类及编号」是合并的表头格\n"
    "5. **原表是空白表单, 大量单元格本来就是空的 —— 空的单元格保留为 <td></td>, "
    "但总行数必须严格按原表的行数来, 绝对不要自己编造额外的空行或空列。**\n"
    "6. 单元格内的换行合并进同一个单元格, 不要拆成多行; "
    "带下划线的填空处(如 生产线____)照原样输出下划线\n"
    "7. 页眉、页码、书名不要输出; 表下的「注:」说明文字**单独作为普通段落输出在表格之后**\n"
    "8. 只输出表格本身和注, 不要任何解释文字, 不要输出 LaTeX"
)

REQUIRED = {
    "0185": ["表1", "企业基本情况", "企业名称", "生产地址", "通讯地址及邮编",
             "法定代表人", "统一社会信用代码", "企业类型", "注册资本", "固定资产",
             "机构名称", "人员总数", "其中专业技术人员", "企业简介"],
    "0186": ["表2", "产品基本情况", "序号", "产品名称", "生产能力", "生产工艺简述",
             "表3", "生产设备明细表", "生产产品", "设备名称", "型号规格", "材质",
             "生产厂家", "出厂日期", "技术性能指标"],
    "0187": ["表4", "检验仪器明细表", "序号", "仪器名称", "型号规格", "生产厂家",
             "出厂日期", "出厂编号", "技术性能指标", "表5",
             "主要管理技术人员及持有工种人员登记表", "姓名", "职务", "职称",
             "学历", "所学专业", "资格证书", "发证机关", "注"],
}

BLEED = {
    "0185": ["生产许可证编号", "申请书", "生产线路"],
    "0186": ["检验仪器明细表", "表4", "表5", "出厂编号"],
    "0187": ["产品基本情况", "表2", "表3", "生产工艺简述"],
}


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


def score_form(raw, tag):
    if "<table" not in raw.lower():
        return -100, "无表"
    tabs = re.findall(r"<table.*?</table>", raw, re.S | re.I)
    rows_all = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S | re.I)
    widths = [len(re.findall(r"<t[dh][^>]*>", tr, re.I)) for tr in rows_all]
    widths = [w for w in widths if w]
    max_cols = max(widths) if widths else 0
    req = REQUIRED.get(tag, [])
    missing = [k for k in req if k not in raw]
    got = len(req) - len(missing)
    total = len(req) or 1
    s = 0
    why = []
    s += len(tabs) * 15
    s += len(rows_all) * 1.5
    s += max_cols * 10
    s += int(got / total * 70)
    if missing:
        s -= len(missing) * 12
        why.append("缺" + ",".join(missing[:4]))
    bleed = [k for k in BLEED.get(tag, []) if k in raw]
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


def pick(src, tag, is_right, cands):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    print(f"  候选 {cands}")

    def run(c):
        page = im.crop((c, 0, W, H)) if is_right else im.crop((0, 0, c, H))
        if page.size[0] < 300:
            return None
        try:
            raw = clean(api_ocr(prep(page), PROMPT))
        except Exception as e:
            return (None, c, None, f"API失败 {type(e).__name__}")
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


JOBS = [
    ("0185", "Images/02制度文件/0185.jpg", True, [2030, 2050, 2075, 2100]),
    ("0186", "Images/02制度文件/0187.jpg", False, [2030, 2050, 2075, 2100]),
    ("0187", "Images/02制度文件/0187.jpg", True, [2030, 2050, 2075, 2100]),
]


def main():
    for tag, src_rel, is_right, cands in JOBS:
        src = os.path.join(REPO, src_rel)
        print(f"\n=== {tag}  ({src_rel}, {'右半' if is_right else '左半'}) ===")
        cut, raw = pick(src, tag, is_right, cands)
        if raw is None:
            print("  全部候选失败")
            continue
        out = os.path.join(OUTDIR, tag + ".md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"<!-- source: {src_rel} (split: {tag}) -->\n")
            f.write("<!-- repaired: rotated=no, method=api-minimax, form=blank -->\n\n")
            f.write(raw.strip() + "\n")
        print(f"  已写 {os.path.relpath(out, REPO)} ({len(raw)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
