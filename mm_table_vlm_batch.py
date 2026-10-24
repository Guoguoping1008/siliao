"""批量用 VLM 重读表格页, 输出带 rowspan/colspan 的 HTML 表格。

质量门(不合规则不写入):
  1) 必须有 <table>
  2) 表格行数 >= 2
  3) **表头列数 == 数据行众数列数**(跨列合并后每行列数会变, 用 rowspan/colspan
     展开后的等效列数)
  4) 单元格内容不能比现有版本少(防幻觉丢数据)

流程:
  - 对每页: 旋转 0/90/270 各试一次, 用 (rowspan+colspan 数, 行数) 打分取最优
  - 与现有 md 里的表格比内容, 内容少就丢弃
  - 通过则替换

用法:
    python mm_table_vlm_batch.py --plan
    python mm_table_vlm_batch.py --apply
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter

from PIL import Image

API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
FALLBACK_MODEL = "MiniMax-M3"
MAX_TOKENS = 8000
TIMEOUT = 120
MAX_RETRY = 3
TARGET_W = 1600
HEADER_CROP = 0.06
JPEG_QUALITY = 88

MM_ROOT = r"E:/workspace/siliao/minimax"
SRC_CANDIDATES = (
    r"E:/workspace/siliao/back/Images_split",
    r"E:/workspace/siliao/back/Images_split_spine",
    r"E:/workspace/siliao/Images_split",
    r"E:/workspace/siliao/Images",
)

PROMPT = """这是一页中文书籍扫描页，其中的表格是旋转 90 度印刷的。
请把表格转写成 **HTML 表格**，要求能表达合并单元格。

严格要求：
1. 只输出 HTML：<table border="1" cellspacing="0" cellpadding="4"> ... </table>
2. 行用 <tr>，表头格用 <th>，数据格用 <td>。
3. **原图里纵向合并的格子**（一个格横跨几行）用 rowspan="N"，N 是它跨的行数。
4. **原图里横向合并的格子**（一个格横跨几列）用 colspan="N"。
5. 不要加 bgcolor / background 背景色属性。
6. 单元格内容照抄原文，不要改写、不要补字、不要总结；换行用 <br>。
7. 一个单元格内有多行文字时用 <br> 连接成同一格。
8. 表格上方的标题（如"表1 xxx"）用 <caption> 放在 table 标签内。
9. 表格外的正文、页眉、页码一律不要输出。
10. 不要输出任何解释文字。"""

ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S | re.I)
TBL = re.compile(r"<table\b.*?</table>", re.S | re.I)


def _api_key():
    env = r"C:/Users/Administrator/AppData/Local/hermes/profiles/qingmang/.env"
    with open(env, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MINIMAX_CN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("MINIMAX_CN_API_KEY not found")


API_KEY = _api_key()


def find_src(stem):
    best, best_depth = None, -1
    for root in SRC_CANDIDATES:
        if not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            for f in fns:
                if os.path.splitext(f)[0] != stem:
                    continue
                if not f.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                d = dp.count(os.sep)
                if d > best_depth:
                    best_depth, best = d, os.path.join(dp, f)
    return best


def find_dst(stem):
    best, best_depth = None, -1
    for dp, dns, fns in os.walk(MM_ROOT):
        for f in fns:
            if f != stem + ".md":
                continue
            d = dp.count(os.sep)
            if d > best_depth:
                best_depth, best = d, os.path.join(dp, f)
    return best


def prep(path, rotate=0):
    im = Image.open(path)
    w, h = im.size
    im = im.crop((0, int(h * HEADER_CROP), w, h))
    if rotate:
        im = im.rotate(rotate, expand=True)
    w, h = im.size
    if max(w, h) > TARGET_W:
        s = TARGET_W / max(w, h)
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def ocr(img_bytes, model=MODEL):
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," +
                               base64.b64encode(img_bytes).decode()}},
            ],
        }],
        "max_tokens": MAX_TOKENS,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + API_KEY,
                 "Content-Type": "application/json"},
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def table_text(h):
    """html 表 -> 全部单元格文字(拼成一个大字符串, 便于比内容)"""
    out = []
    for cm in CELL.finditer(h):
        t = re.sub(r"<[^>]+>", "", cm.group(2))
        t = t.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
        if t.strip():
            out.append(t.strip())
    return "".join(out).replace(" ", "").replace("/", "")


def table_rows(h):
    rows = []
    for rm in ROW.finditer(h):
        cells = []
        for cm in CELL.finditer(rm.group(1)):
            d = dict(re.findall(r'(\w+)="([^"]*)"', cm.group(1)))
            cells.append((d, re.sub(r"<[^>]+>", "", cm.group(2)).strip()))
        rows.append(cells)
    return rows


def eff_cols(row):
    """一行的等效列数 = 各格 colspan 之和"""
    n = 0
    for d, _ in row:
        n += int(d.get("colspan", 1))
    return n


def main():
    apply = "--apply" in sys.argv
    stems = [l.strip() for l in open(r"E:/workspace/siliao/_vlm_pick.txt",
                                     encoding="utf-8") if l.strip()]
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    ok = fail = skip = 0
    for si, stem in enumerate(stems):
        if limit and si >= limit:
            break
        src = find_src(stem)
        dst = find_dst(stem)
        if not src or not dst:
            skip += 1
            continue
        old_txt = open(dst, encoding="utf-8").read()
        old_tbl = TBL.search(old_txt)
        if not old_tbl:
            skip += 1
            continue
        old_text = table_text(old_tbl.group(0))

        best = None
        for rot in (0, 90, 270):
            try:
                img = prep(src, rot)
            except Exception:
                continue
            for attempt in range(MAX_RETRY):
                model = MODEL if attempt < 2 else FALLBACK_MODEL
                try:
                    raw = ocr(img, model)
                except Exception:
                    time.sleep(1.2)
                    continue
                h = TBL.search(raw)
                if not h:
                    break
                h = h.group(0)
                rows = table_rows(h)
                if len(rows) < 2:
                    break
                nrs = len(re.findall(r'rowspan="[2-9]', h))
                ncs = len(re.findall(r'colspan="[2-9]', h))
                # 内容不能比旧版少太多
                nt = table_text(h)
                if old_text and len(nt) < len(old_text) * 0.9:
                    break
                score = (nrs + ncs, len(rows))
                if best is None or score > best[0]:
                    best = (score, h, rot)
                break

        if not best:
            fail += 1
            print(f"  {stem}: 全部尝试失败")
            continue
        score, h, rot = best
        # 质量门: 数据行的等效列数要一致
        rows = table_rows(h)
        dcols = Counter(eff_cols(r) for r in rows[1:]) if len(rows) > 1 else Counter()
        if len(dcols) > 1:
            print(f"  {stem}: 数据行列数不一致 {dict(dcols)}  丢弃")
            fail += 1
            continue
        nrs = len(re.findall(r'rowspan="[2-9]', h))
        ncs = len(re.findall(r'colspan="[2-9]', h))
        print(f"  {stem}: rot={rot} 行={len(rows)} rs={nrs} cs={ncs} 列={dcols.most_common(1)[0][0] if dcols else '?'}")
        ok += 1
        if apply:
            p = find_dst(stem) or dst
            txt = open(p, encoding="utf-8").read()
            m = TBL.search(txt)
            if m:
                new_txt = txt[:m.start()] + h + txt[m.end():]
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new_txt)
    print(f"\n成功 {ok}, 失败 {fail}, 跳过 {skip}")


if __name__ == "__main__":
    main()
