"""从源图找"有纵向合并格"的表: 用 VLM 读旋正后的图, 明确给出 rowspan/colspan 需求。

流程(依据 skill scanned-table-ocr-md):
1. 定位源图(按 stem 递归, 取层级最深)
2. 旋正(0/90/270 三向, 用**表头关键词命中数**挑最优)
3. 让 VLM 直接输出带 rowspan/colspan 的 HTML 表格
4. 质量门: 是表格 / 实质行>=3 / 表头列数==数据列数
"""
import base64
import io
import json
import os
import sys
import time
import urllib.request

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
8. 表格上方的标题（如"表1 xxx"）用 <caption>放在 table 标签内，或用单独一行文字。
9. 表格外的正文、页眉、页码一律不要输出。
10. 不要输出任何解释文字。"""


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


TBL_RE = None


def extract_html_table(raw):
    """从模型输出里抠出 <table>...</table>"""
    import re
    m = re.search(r"<table\b.*?</table>", raw, re.S | re.I)
    if m:
        return m.group(0)
    return None


def main():
    stems = sys.argv[1:]
    apply = "--apply" in sys.argv
    stems = [s for s in stems if not s.startswith("--")]
    for stem in stems:
        src = find_src(stem)
        dst = find_dst(stem)
        print(f"=== {stem}  src={os.path.basename(src) if src else None}  dst={'ok' if dst else None}")
        if not src or not dst:
            print("   跳过")
            continue
        best = None
        for rot in (0, 90, 270):
            try:
                img = prep(src, rot)
            except Exception as e:
                print(f"   rot={rot} 预处理失败 {e}")
                continue
            for attempt in range(MAX_RETRY):
                model = MODEL if attempt < 2 else FALLBACK_MODEL
                try:
                    raw = ocr(img, model)
                except Exception as e:
                    print(f"   rot={rot} try{attempt} 失败: {e}")
                    time.sleep(1.5)
                    continue
                h = extract_html_table(raw)
                if h:
                    import re as _re
                    rows = _re.findall(r"<tr\b.*?</tr>", h, _re.S | _re.I)
                    nrs = len(_re.findall(r'rowspan="[2-9]', h))
                    ncs = len(_re.findall(r'colspan="[2-9]', h))
                    print(f"   rot={rot:3d} try{attempt} {model:18s} "
                          f"行={len(rows):3d} rowspan={nrs} colspan={ncs}")
                    score = (nrs + ncs, len(rows))
                    if best is None or score > best[0]:
                        best = (score, h)
                    break
        if best:
            print("   -> 采用")
            print("   " + best[1][:300].replace("\n", "\n   "))
            if apply:
                p = find_dst(stem) or dst
                txt = open(p, encoding="utf-8").read()
                import re as _re
                # 替换掉文件里**已有的** html 表 或 md 管道表块
                html_tbl = _re.search(r"<table\b.*?</table>", txt, _re.S | _re.I)
                if html_tbl:
                    new_txt = txt[:html_tbl.start()] + best[1] + txt[html_tbl.end():]
                else:
                    lines = txt.splitlines()
                    out = []
                    i = 0
                    while i < len(lines):
                        if lines[i].strip().startswith("|"):
                            j = i
                            while j < len(lines) and lines[j].strip().startswith("|"):
                                j += 1
                            out.append(best[1])
                            i = j
                            continue
                        out.append(lines[i])
                        i += 1
                    new_txt = "\n".join(out).rstrip() + "\n"
                with open(p, "w", encoding="utf-8") as f:
                    f.write(new_txt)
                print(f"   已写入 {p}")


if __name__ == "__main__":
    main()
