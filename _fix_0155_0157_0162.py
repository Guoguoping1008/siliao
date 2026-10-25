#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0155/0156/0157/0162 的表格(空白表单 + 申报材料一览表)。

【原状态】
0155.md 337B / 0156.md 252B —— 表格结构全丢, 只剩一串标签(同 0145/0146 的缺陷)
0157.md 748B —— 只有「表4 检验仪器明细表」半截, 表5 和前面的内容都丢
0162.md 898B —— 表格塌成了带 #### 标题的散文

【书脊定位(目视逐张核对过, 放大截图看装订沟阴影)】
这一批图的**书脊都在 x≈2050**(几何中线 2261 偏右 200px, 算法给的 1428 偏左 620px)。
  0155.jpg  -> 页 154(左) + 155(右)   页155 = 右半, 切 2050
  0157.jpg  -> 页 156(左) + 157(右)   页156 = 左半, 切 2050
                                        页157 = 右半, 切 2050
  0163.jpg  -> 页 162(左) + 163(右)   页162 = 左半, 切 2030

【关键提醒】
偶数页在**左半**! 0156 是 0157.jpg 的左半, 0162 是 0163.jpg 的左半。
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

PROMPT = (
    "请把这张中文**表格表单扫描页**转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头/标签用 <th>)\n"
    "2. **页面顶部若有一行居中的表标题(如「表1 企业基本情况」「表2 产品基本情况」"
    "「表4 检验仪器明细表」「表5 主要管理技术人员及持有工种人员登记表」"
    "「添加剂预混合饲料生产许可申报材料一览表」), 必须作为该表的第一行输出, "
    "用 <th colspan=\"N\">标题文字</th>, 严禁丢失。**\n"
    "3. **保持原表的行列数**: 原表有几列就输出几列, **绝不能因为右边是空白就少输出列**。\n"
    "4. 合并单元格用 colspan/rowspan 表达。特别注意这些**嵌套合并**:\n"
    "   - 「注册资本(万元)」与「固定资产(万元)」并排在同一行\n"
    "   - 「所属法人机构信息」「主要机构设置及人员组成」是**左侧纵向标签**(rowspan 覆盖多行)\n"
    "   - 表5 里「资格证书时间、种类及编号」「发证机关」是合并的表头格\n"
    "5. **原表是空白表单, 大量单元格本来就是空的 —— 空的单元格保留为 <td></td>, "
    "但总行数必须严格按原表的行数来, 绝对不要自己编造额外的空行或空列。**\n"
    "6. 单元格内的换行合并进同一个单元格, 不要拆成多行; "
    "带下划线的填空处(如 生产线___)照原样输出下划线\n"
    "7. 页眉、页码、书名不要输出; 表下方的「注：」说明文字**要单独作为普通段落输出在表格之后**\n"
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


# 每页必须出现的标签
REQUIRED = {
    "0155": ["企业名称", "生产地址", "通讯地址及邮编", "法定代表人", "统一社会信用代码",
             "企业类型", "注册资本", "固定资产", "机构名称", "人员总数",
             "其中专业技术人员", "企业简介", "表1"],
    "0156": ["表2", "产品基本情况", "序号", "产品名称", "产品组分", "载体或稀释剂",
             "生产能力", "表3", "生产设备明细表", "设备名称", "型号规格", "材质",
             "生产厂家", "出厂日期", "技术性能指标"],
    "0157": ["表4", "检验仪器明细表", "序号", "仪器名称", "型号规格", "生产厂家",
             "出厂日期", "出厂编号", "技术性能指标", "表5",
             "主要管理技术人员及持有工种人员登记表", "姓名", "职务", "职称",
             "学历", "所学专业", "资格证书", "发证机关"],
    "0162": ["申报材料一览表", "序号", "申报材料项目"],
    # 0165 与 0145/0155 是**同一张表**(表1 企业基本情况)
    "0165": ["企业名称", "生产地址", "通讯地址及邮编", "法定代表人", "统一社会信用代码",
             "企业类型", "注册资本", "固定资产", "机构名称", "人员总数",
             "其中专业技术人员", "企业简介", "表1"],
}

# 对页才有的标签 -> 出现即说明串页了
BLEED = {
    "0155": ["生产许可证编号", "申请书", "生产线路"],
    "0156": ["检验仪器明细表", "表4", "表5"],
    "0157": ["产品基本情况", "表2", "表3", "生产能力（吨/小时）"],
    "0162": ["一、申报材料", "二、遵纪守法"],
    "0165": ["生产许可证编号", "申请书", "生产线路", "预混饲料"],
}


def score_form(raw, tag):
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


def pick(img_path, tag, is_right, cands):
    im = Image.open(img_path).convert("RGB")
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


D1 = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                  "24_关于混合型饲料添加剂生产许可申报材料要求的公告")
D2 = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                  "25_关于添加剂预混合饲料生产许可申报材料要求的公告")

JOBS = [
    # (tag, 源图, 是否右半, 切点候选, 输出目录)
    ("0155", "Images/02制度文件/0155.jpg", True, [2030, 2050, 2075, 2100], D1),
    ("0156", "Images/02制度文件/0157.jpg", False, [2030, 2050, 2075, 2100], D1),
    ("0157", "Images/02制度文件/0157.jpg", True, [2030, 2050, 2075, 2100], D1),
    ("0162", "Images/02制度文件/0163.jpg", False, [2000, 2020, 2035, 2050], D2),
    # 0165 = 0165.jpg 的右半(页 164+165); 书脊实测 2050~2100
    ("0165", "Images/02制度文件/0165.jpg", True, [2050, 2075, 2100, 2125], D2),
]


def main():
    for tag, src_rel, is_right, cands, outdir in JOBS:
        src = os.path.join(REPO, src_rel)
        print(f"\n=== {tag}  ({src_rel}, {'右半' if is_right else '左半'}) ===")
        cut, raw = pick(src, tag, is_right, cands)
        if raw is None:
            print("  全部候选失败")
            continue
        out = os.path.join(outdir, tag + ".md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"<!-- source: {src_rel} (split: {tag}) -->\n")
            f.write("<!-- repaired: rotated=no, method=api-minimax, form=blank -->\n\n")
            f.write(raw.strip() + "\n")
        print(f"  已写 {os.path.relpath(out, REPO)} ({len(raw)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
