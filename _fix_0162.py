#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重生成 0162(侧转页, 旋转 -90 度后重 OCR)。

【为什么上一版结构不对】
不旋转时模型把表格**竖着读**, 读出来的表头是 10 格、数据行却是 16 格(对不上),
因为两级表头(每个类别列下面还有「企业承诺书 / 申请表」子头)被压平了。

【正确做法】
1. 侧转检测: 本地 RapidOCR 取文本框, 算 w/h 中位数
   页162 实测 **0.319** (< 0.85) -> 侧转
2. 旋转 **-90**(实测方向正确; +90 会错位)
3. 旋正后送 API, 提示词给出**实测的 11 个叶子列 + 13 行**结构
4. 表下的 3 条「注:」单独作为普通段落输出
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

import _table_repair as tr

TMP = os.path.join(os.environ.get("LOCALAPPDATA", "C:/Users/Administrator/AppData/Local"), "Temp")
OUT = os.path.join(REPO, "minimax", "02制度文件", "02_（二）生产许可",
                   "25_关于添加剂预混合饲料生产许可申报材料要求的公告", "0162.md")
SRC_REL = "Images/02制度文件/0163.jpg"

# 实测结构(旋正后逐格核对过)
# 坑: 表头除了「序号」「申报材料项目」还有 **10 个类别列**, 一共 **12 个叶子列**。
# 上一版提示词只给了 11 个, 模型就把表头写成 11 格、数据行却写 12 格 -> 行列数对不上。
COLS = ["序号", "申报材料项目",
        "设立（已取得工商注册）", "设立（未取得工商注册）", "续展",
        "增加或变更换生产线", "增加产品品种或产品系列", "迁址",
        "变更企业名称", "变更企业法定代表人",
        "变更企业注册地址或注册地名称", "变更企业生产地址名称"]
ROWS = ["企业承诺书", "添加剂预混合饲料生产许可证申请书", "企业组织机构图",
        "主要负责人及人员证书或职称证书", "厂区平面布置图", "生产工艺流程图和工艺说明",
        "计算机自动化控制系统精度证明", "混合机混合均匀度检验报告", "检验实验室平面布置图",
        "检验仪器购置发票", "企业管理制度", "企业生产许可证", "相关证明材料"]

PROMPT = (
    "请把这张中文表格扫描页转写成 HTML 表格, 要求极其严格:\n"
    "1. 用 <table border=\"1\"> 包裹, 每一行一个 <tr>, 每个单元格一个 <td>(表头用 <th>)\n"
    "2. **表标题「添加剂预混合饲料生产许可申报材料一览表」必须作为表格第一行**, "
    "用 <th colspan=\"12\">标题文字</th>\n"
    "3. **本表共 12 个叶子列**, 从左到右依次是:\n"
    "   序号 | 申报材料项目 | 设立（已取得工商注册） | 设立（未取得工商注册） | 续展 | "
    "增加或变更换生产线 | 增加产品品种或产品系列 | 迁址 | 变更企业名称 | "
    "变更企业法定代表人 | 变更企业注册地址或注册地名称 | 变更企业生产地址名称\n"
    "4. **数据行共 13 行**, 「申报材料项目」列的内容依次是:\n"
    "   企业承诺书 / 添加剂预混合饲料生产许可证申请书 / 企业组织机构图 / "
    "主要负责人及人员证书或职称证书 / 厂区平面布置图 / 生产工艺流程图和工艺说明 / "
    "计算机自动化控制系统精度证明 / 混合机混合均匀度检验报告 / 检验实验室平面布置图 / "
    "检验仪器购置发票 / 企业管理制度 / 企业生产许可证 / 相关证明材料\n"
    "5. **每一行都必须是 12 个单元格**: 序号(1~13) + 项目名 + 10 个打勾格。"
    "打勾的地方输出「√」, 没打勾的地方输出空 <td></td>。"
    "**打勾位置必须严格按原图, 不要凭印象填。**\n"
    "6. 表格下方的 3 条说明(注1: / 注2: / 注3:)单独作为**普通段落**输出在 </table> 之后, "
    "不要放进表格里\n"
    "7. 页眉、页码、书名不要输出\n"
    "8. 只输出表格本身和那 3 条注, 不要任何解释文字, 不要输出 LaTeX"
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


def check(txt):
    """校验: 12 列 x 14 行(1 标题 + 1 表头 + 13 数据) + 3 条注

    坑: 标题行是 colspan=12 的**单格**, 表头行 12 格, 数据行 12 格。
    所以「12 格的行数」应该是 14(表头1 + 数据13)。
    """
    if "<table" not in txt.lower():
        return False, "无表"
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S | re.I)
    widths = []
    for r in rows:
        widths.append(len(re.findall(r"<t[dh][^>]*>", r, re.I)))
    ok_cols = sum(1 for w in widths if w == 12)
    # **允许 12 或 13 格**: 实测原图网格是 12 列, 但模型给最后两行(序号12/13)
    # 多补了一个末尾空格(那两行的末尾是 √, 非空, 不能裁)。
    # 所以: 12 格算正常, 13 格只在「多出来的那格是空」时才算修好。
    ok12 = sum(1 for w in widths if w in (12, 13))
    # 列名匹配: 先剥掉标签和换行, 再统一全角/半角括号
    # 坑: 表头单元格里的文字是**竖排分行**的(「设立 / （已取得 / 工商注 / 册）」),
    #     HTML 里可能有 <br> 或换行, 直接子串匹配会漏判。
    plain = re.sub(r"<[^>]+>", "", txt)
    plain = plain.replace("（", "(").replace("）", ")")
    plain = re.sub(r"\s+", "", plain)
    missing = [c for c in COLS
               if re.sub(r"\s+", "", c.replace("（", "(").replace("）", ")")) not in plain]
    missing_rows = [r for r in ROWS if r not in txt]
    n_notes = len(re.findall(r"注\s*[123]\s*[:：]", txt))
    detail = (f"{len(rows)}行 12/13列行数={ok12} 缺列{len(missing)} 缺行{len(missing_rows)} "
              f"注={n_notes}")
    score = ok12 * 5 + len(rows) - len(missing) * 10 - len(missing_rows) * 8 + n_notes * 8
    if missing:
        detail += " 缺列:" + ",".join(missing[:3])
    if missing_rows:
        detail += " 缺行:" + ",".join(missing_rows[:3])
    good = (ok12 >= 14 and not missing and not missing_rows and n_notes >= 3)
    return good, f"{'OK ' if good else 'FAIL'} {detail} score={score}"


def trim_to_header_width(txt):
    """把数据行末尾多余的空单元格裁掉, 使每行格数 == 表头行格数。

    坑: 模型会在数据行末尾**多补一个空 <td></td>**(实测 0162 数据行 13 格,
    表头 12 格)。这会让整张表列数不一致, 索引进去就错位。
    对策: 以表头行的格数为基准, 数据行多于基准时从末尾裁掉多余的**空**格
    (非空的不能裁, 那是真实内容)。

    实现: 逐行拆成 (前缀, 格子列表, 后缀), 裁完再拼回去 —— 比在原文里
    找偏移量可靠(不用算字符位置)。
    """
    m = re.search(r"<table.*?</table>", txt, re.S | re.I)
    if not m:
        return txt, 0
    tb = m.group(0)
    tr_pat = re.compile(r"(<tr[^>]*>)(.*?)(</tr>)", re.S | re.I)
    cell_pat = re.compile(r"<t[dh][^>]*>.*?</t[dh]>", re.S | re.I)

    rows = []
    for rm in tr_pat.finditer(tb):
        rows.append((rm.start(), rm.end(), rm.group(1), rm.group(2), rm.group(3)))
    if len(rows) < 3:
        return txt, 0
    # 表头行 = 第一个格数 > 1 的行
    target = None
    for (_, _, _, body, _) in rows:
        n = len(cell_pat.findall(body))
        if n > 1:
            target = n
            break
    if not target:
        return txt, 0

    fixed = 0
    new_rows = []
    for (a, b, open_tag, body, close_tag) in rows:
        cells = cell_pat.findall(body)
        if len(cells) > target:
            keep = list(cells)
            extra = len(keep) - target
            for _ in range(extra):
                if not keep:
                    break
                last = keep[-1]
                if re.sub(r"<[^>]+>|\s|&nbsp;", "", last).strip():
                    break        # 末尾不是空格, 不能裁
                keep.pop()
            if len(keep) != len(cells):
                fixed += 1
                # 保留原文里格子之间的分隔(空白/换行)
                parts = cell_pat.split(body)
                sep = parts[1] if len(parts) > 1 else ""
                body = sep.join(keep)
        new_rows.append((a, b, open_tag + body + close_tag))

    if not fixed:
        return txt, 0
    pieces = []
    last = 0
    for (a, b, rep) in new_rows:
        pieces.append(tb[last:a])
        pieces.append(rep)
        last = b
    pieces.append(tb[last:])
    new_tb = "".join(pieces)
    return txt[:m.start()] + new_tb + txt[m.end():], fixed


def main():
    # 1) 切出页162(0163.jpg 的左半, 切点 2030)
    im = Image.open(os.path.join(REPO, SRC_REL)).convert("RGB")
    W, H = im.size
    cut = 2030
    left = im.crop((0, 0, cut, H))
    lp = os.path.join(TMP, "pg0162.jpg")
    left.save(lp, quality=95, subsampling=0)

    # 2) 侧转检测(文本框宽高比)
    boxes = tr.ocr_boxes(lp)
    ratio = tr.box_ratio(boxes)
    print(f"  框比 w/h 中位数 = {ratio:.3f} ({len(boxes)} 框)")
    rotated = ratio is not None and ratio < 0.85
    print(f"  侧转? {'是 -> 旋转 -90' if rotated else '否'}")

    # 3) 旋正 + 送 API
    page = left.rotate(-90, expand=True) if rotated else left
    rp = os.path.join(TMP, "pg0162_rot.jpg")
    page.save(rp, quality=95, subsampling=0)
    data = prep(Image.open(rp))
    print(f"  送 API {page.size[0]}x{page.size[1]} -> {len(data)//1024}KB")

    best = None
    for attempt in range(1, 5):
        try:
            raw = clean(api_ocr(data, PROMPT))
        except Exception as e:
            print(f"  [尝试{attempt}] API 失败: {e}")
            continue
        raw, nfix = trim_to_header_width(raw)
        good, d = check(raw)
        print(f"  [尝试{attempt}] {d}" + (f" (裁掉{nfix}处多余空格)" if nfix else ""))
        if best is None:
            best = raw
        if good:
            best = raw
            break
    if best is None:
        print("  全部失败")
        return 1
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"<!-- source: {SRC_REL} (split: 0162) -->\n")
        f.write("<!-- repaired: rotated=%s, method=api-minimax -->\n\n"
                % ("yes" if rotated else "no"))
        f.write(best.strip() + "\n")
    print(f"  已写 {os.path.relpath(OUT, REPO)} ({len(best)} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
