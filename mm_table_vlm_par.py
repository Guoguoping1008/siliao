"""批量用 VLM 重读表格页(并行版)。

优化(相对 mm_table_vlm_batch.py):
  1) **页间并行**(线程池)—— 52 页串行要 1 小时, 并行后几分钟
  2) **旋转方向先探测**再试: 用本地 RapidOCR 算文本框宽高比,
     侧转页(w/h < 0.85)只试 90/270, 正常页只试 0
     -> 每页从 3 次请求降到 1~2 次
  3) 质量门: 数据行等效列数一致 + 内容不比旧版少 10%

用法:
    python mm_table_vlm_par.py --plan
    python mm_table_vlm_par.py --apply
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
FALLBACK_MODEL = "MiniMax-M3"
MAX_TOKENS = 8000
TIMEOUT = 120
MAX_RETRY = 2
TARGET_W = 1600
HEADER_CROP = 0.06
JPEG_QUALITY = 88
WORKERS = 6

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


# ---------- 旋转方向探测(本地 OCR 框宽高比) ----------
def detect_rot(path):
    """返回该页可能的旋转方向列表(按优先级)。

    依据 skill scanned-table-ocr-md:
      侧转页的文本框是**高**的 (w/h < 0.85); 摆正的是**扁**的 (w/h >> 1)。
    用 RapidOCR; 不可用就退回 (0, 90, 270)。

    优先读 _rot_cache.json(批量探测时算好的), 省掉每页 30~40s 的本地 OCR。
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    cache_path = r"E:/workspace/siliao/_rot_cache.json"
    if os.path.exists(cache_path):
        try:
            c = json.load(open(cache_path, encoding="utf-8"))
            if stem in c and c[stem]:
                return c[stem]
        except Exception:
            pass
    try:
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np
        engine = RapidOCR()
        img = Image.open(path).convert("RGB")
        w, h = img.size
        img = img.crop((0, int(h * HEADER_CROP), w, h))
        w, h = img.size
        if w > 1600:
            s = 1600 / w
            img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
        res, _ = engine(np.array(img))
        if not res:
            return [0, 90, 270]
        ratios = []
        for r in res:
            box = r[0]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            bw = max(xs) - min(xs)
            bh = max(ys) - min(ys)
            if bh > 4:
                ratios.append(bw / bh)
        if not ratios:
            return [0, 90, 270]
        ratios.sort()
        med = ratios[len(ratios) // 2]
        if med < 0.85:
            return [270, 90, 0]      # 侧转
        return [0, 270, 90]          # 摆正
    except Exception:
        return [0, 90, 270]


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
    return sum(int(d.get("colspan", 1)) for d, _ in row)


def process(stem, apply):
    src = find_src(stem)
    dst = find_dst(stem)
    if not src or not dst:
        return stem, "skip: 缺源图/目标", None
    old_txt = open(dst, encoding="utf-8").read()
    m = TBL.search(old_txt)
    if not m:
        return stem, "skip: 目标里没有 html 表", None
    old_text = table_text(m.group(0))

    rots = detect_rot(src)
    best = None
    for rot in rots[:2]:
        try:
            img = prep(src, rot)
        except Exception:
            continue
        for attempt in range(MAX_RETRY):
            model = MODEL if attempt < 1 else FALLBACK_MODEL
            try:
                raw = ocr(img, model)
            except Exception:
                time.sleep(1.0)
                continue
            h = TBL.search(raw)
            if not h:
                break
            h = h.group(0)
            rows = table_rows(h)
            if len(rows) < 2:
                break
            nt = table_text(h)
            if old_text and len(nt) < len(old_text) * 0.9:
                break
            nrs = len(re.findall(r'rowspan="[2-9]', h))
            ncs = len(re.findall(r'colspan="[2-9]', h))
            score = (nrs + ncs, len(rows))
            if best is None or score > best[0]:
                best = (score, h, rot)
            break
    if not best:
        return stem, "fail: 全部尝试失败", None
    score, h, rot = best
    rows = table_rows(h)
    dcols = Counter(eff_cols(r) for r in rows[1:])
    if len(dcols) > 1:
        return stem, f"fail: 数据行列数不一致 {dict(dcols)}", None
    nrs = len(re.findall(r'rowspan="[2-9]', h))
    ncs = len(re.findall(r'colspan="[2-9]', h))
    info = (rot, len(rows), nrs, ncs)
    if apply:
        p = find_dst(stem) or dst
        txt = open(p, encoding="utf-8").read()
        mm = TBL.search(txt)
        if mm:
            with open(p, "w", encoding="utf-8") as f:
                f.write(txt[:mm.start()] + h + txt[mm.end():])
    return stem, f"ok rot={rot} 行={len(rows)} rs={nrs} cs={ncs}", info


def main():
    apply = "--apply" in sys.argv
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    stems = [l.strip() for l in open(r"E:/workspace/siliao/_vlm_pick.txt",
                                     encoding="utf-8") if l.strip()]
    if limit:
        stems = stems[:limit]
    print(f"处理 {len(stems)} 页 (并行 {WORKERS})")
    ok = fail = skip = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process, s, apply): s for s in stems}
        for fu in as_completed(futs):
            stem, msg, info = fu.result()
            print(f"  {stem}: {msg}")
            if msg.startswith("ok"):
                ok += 1
            elif msg.startswith("fail"):
                fail += 1
            else:
                skip += 1
    print(f"\n成功 {ok}, 失败 {fail}, 跳过 {skip}, 用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
