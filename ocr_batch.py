"""
批量 OCR: E:/workspace/siliao/Images/**/*.jpg -> 每页一个 .md

关键技术点:
1. 页眉去除: 顶部 HEADER_CROP 比例直接裁掉(章节名 + 页码 + 装饰条)
2. 双页跨页(gutter)检测: 用列方向"无文字竖直空白带"定位书脊,
   左右分栏独立排序, 避免左右栏交错(本书扫描件书脊弯曲, 固定 x=0.5 不可靠)
3. 行合并成段: 按 y 聚类成行 -> 行内按 x 排序 -> 中文书籍无空行,
   依据"段首缩进 / 句末标点 / 编号开头"续接成段
"""
import os, re, sys, time, json, argparse
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

HEADER_CROP = 0.13
SCALE = 0.55
ROW_TOL_FRAC = 0.010   # 行聚类容差 = tol_frac * 页高
END_PUNCT = "。！？!?；;：:"


# ---------- 几何工具 ----------
def gutter_x(items, nw, nh):
    """检测书脊 x(竖直空白带中心)。返回 None 表示单栏。

    真实书脊常只有 20~60px(缩放后), 约 1%~3% 页宽, 因此:
    - 用较小平滑核, 阈值取近零
    - 搜索区间放宽到 32%~68%
    - 校验: 空白带左右两侧都要有足量内容, 且带宽度 >= 页宽的 0.6%
    """
    occ = np.zeros(nw, dtype=np.int32)
    for it in items:
        a, b = int(max(0, it["x0"])), int(min(nw, it["x1"]))
        if b > a:
            occ[a:b] += 1
    # 小核平滑, 抑制单字突出但不吞掉窄缝
    k = max(3, nw // 400)
    occ = np.convolve(occ, np.ones(k) / k, mode="same")

    lo, hi = int(nw * 0.32), int(nw * 0.68)
    thr = 0.02
    best = (0, None, None)
    run_start, run_len = None, 0
    for x in range(lo, hi):
        if occ[x] <= thr:
            if run_start is None:
                run_start = x
            run_len = x - run_start + 1
        else:
            if run_len > best[0]:
                best = (run_len, run_start, x)
            run_start, run_len = None, 0
    if run_len > best[0]:
        best = (run_len, run_start, hi - 1)
    gap, a, b = best
    min_gap = nw * 0.006
    if not (gap and a is not None and b is not None and gap >= min_gap):
        return None
    left_n = sum(1 for it in items if it["x1"] <= a)
    right_n = sum(1 for it in items if it["x0"] >= b)
    if left_n < 3 or right_n < 3:
        return None
    # 校验: 不应有大量文本框横跨书脊(否则不是真正的空白缝)
    span = sum(1 for it in items if it["x0"] < b and it["x1"] > a)
    if span > max(1, int(0.08 * len(items))):
        return None
    return (a + b) / 2.0


def to_rows(items, nh, nw=1000, tol_frac=ROW_TOL_FRAC):
    """按 y 聚类成行, 行内按 x 排序。

    扫描件存在倾斜/书脊弯曲, 同一行左右两端的 y 会差几十像素,
    因此用"与当前行已有成员的 y 中位数之差"做容差判断, 而不是与行首 y 比较。
    """
    tol = max(6.0, nh * tol_frac)
    items = sorted(items, key=lambda i: i["y0"])
    rows = []
    cur = []
    for it in items:
        if not cur:
            cur = [it]
            continue
        med = float(np.median([m["y0"] for m in cur]))
        # 允许斜率: 行内成员 x 跨度大时放宽容差
        xs = [m["x0"] for m in cur] + [it["x0"]]
        spread = max(xs) - min(xs)
        t = tol * (1.0 + min(1.5, spread / max(1.0, nw)))
        if abs(it["y0"] - med) <= t:
            cur.append(it)
        else:
            rows.append(sorted(cur, key=lambda i: i["x0"]))
            cur = [it]
    if cur:
        rows.append(sorted(cur, key=lambda i: i["x0"]))
    return rows


def is_item_start(txt):
    return bool(re.match(r"^\s*([(（【\[]?\s*(?:第[一二三四五六七八九十百零〇\d]+[条章节款项]|[一二三四五六七八九十]+[、．.]|\d+[、．.]|[(（【\[]))", txt))


HDR_CHARS = "饲料法规文件相关法律法规文件制度文件标准及标准目录"


def is_running_header(t):
    """识别页眉/页码行。

    页眉形态: "<页码> <书名/章节名> (2023) >>>" 或 "<<< 三、相关法律法规文件 929"。
    跨页扫描件因书脊弯曲, 页眉在左右页高度不同, 固定裁剪会漏掉, 因此再做一次内容级过滤。
    """
    t = t.strip()
    if not t:
        return False
    # 去掉所有空白后必须很短(页眉行很短)
    core = re.sub(r"[\s　]", "", t)
    if not core or len(core) > 40:
        return False
    if ">>>" in t or "<<<" in t:
        return True
    # 纯页码 + 章节名 + 纯页码
    if any(w in core for w in ("饲料法规文件", "相关法律法规文件", "制度文件", "标准及标准目录")):
        # 章节名常伴随孤立页码, 且总长很短
        nums = re.findall(r"\d{1,4}", core)
        return len(nums) >= 1 and len(core) <= 30
    # 纯数字页码(单行, 短)
    if re.fullmatch(r"\d{1,4}", core):
        return True
    return False


# 页眉章节名(用于在正文中精确定位页眉片段的起止)
_HDR_NAME = r"(?:饲料法规文件|相关法律法规文件|相关法规|制度文件|标准及标准目录|目\s*录)"


def strip_inline_header(t):
    """把粘连进正文的页眉片段切掉。

    例: "县级以上...药物残留>>>三、相关法律法规文件的监控工作。929"
    -> "县级以上...药物残留的监控工作。"

    页眉片段由 "章节名" 前后各有限定符界定, 因此用"章节名 + 可选年份 + 页码"
    的完整模式精确匹配, 而不是靠 >>>/<<< 贪心截断(会吃掉正文)。
    """
    if not (">>>" in t or "<<<" in t or "三、相关法律法规文件" in t
            or "二、制度文件" in t):
        return t.strip()
    # 优先: 完整页眉形态 "[>>>|<<<] [序号、] 章节名 [(2023)] 页码 [>>>|<<<]"
    pat = re.compile(
        r"(?:>>>|<<<)?[\s　]*"
        r"(?:[一二三四五六七八九十]+[、．.]|附\s*)?"
        rf"{_HDR_NAME}"
        r"[\s　]*(?:[\(（]20\d\d[\)）])?[\s　]*"
        r"\d{1,4}"
        r"[\s　]*(?:>>>|<<<)?"
    )
    t2 = pat.sub("", t)
    # 页眉紧贴 >>> 的形态: ">>>三、相关法律法规文件的..." —— 章节名之后到行尾为页眉
    pat2 = re.compile(
        rf"(?:>>>|<<<)[\s　]*(?:[一二三四五六七八九十]+[、．.])?{_HDR_NAME}"
        r"[^\n]{0,24}$"
    )
    t2 = pat2.sub("", t2)
    t2 = re.sub(r"(?:>>>|<<<)", "", t2)
    t2 = re.sub(r"(?<=。)\s*\d{1,4}\s*$", "", t2)
    return t2.strip()


def merge_rows_to_paras(rows, font_w):
    """行 -> 段落"""
    paras, cur, prev_txt, prev_x0 = [], "", None, None
    for row in rows:
        line = "".join(i["t"] for i in row)
        line = strip_inline_header(line)
        if not line:
            continue
        if is_running_header(line):
            continue
        x0 = row[0]["x0"]
        if prev_txt is None:
            cur, prev_txt, prev_x0 = line, line, x0
            continue
        start = False
        # 段首缩进(相对上一行行首右移 >= 1.5 字宽)
        if x0 - prev_x0 >= font_w * 1.5:
            start = True
        # 上一行以句末标点收尾
        elif prev_txt.rstrip()[-1:] in END_PUNCT:
            start = True
        # 本行以编号/列表符开头, 且上一行不是长正文续行
        elif is_item_start(line) and len(prev_txt) > font_w * 20:
            start = True
        if start and cur.strip():
            paras.append(cur.strip())
            cur = line
        else:
            cur += line
        prev_txt, prev_x0 = line, x0
    if cur.strip():
        paras.append(cur.strip())
    return paras


def ocr_page_stats(engine, path, header_crop=HEADER_CROP, scale=SCALE):
    """返回 (段落列表, 识别框数, 字符数) —— 框数用于识别"稀疏/丢行"页"""
    paras, nboxes = ocr_page_with_count(engine, path, header_crop, scale)
    return paras, nboxes


def ocr_page_with_count(engine, path, header_crop=HEADER_CROP, scale=SCALE, split_boxes=False):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    ch = int(H * header_crop)
    body = im.crop((0, ch, W, H))
    nw, nh = int(W * scale), int(body.height * scale)
    body = body.resize((nw, nh), Image.LANCZOS)
    res, _ = engine(np.array(body))

    items = []
    for box, txt, score in (res or []):
        txt = txt.strip()
        if score < 0.5 or not txt:
            continue
        # 框级过滤: 纯页眉/页码的小框直接丢弃(避免与正文粘连成一行)
        if is_running_header(txt):
            continue
        xs = [c[0] for c in box]; ys = [c[1] for c in box]
        items.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "t": txt})
    n_raw = len(items)
    if not items:
        return [], 0

    med_len = max(1.0, float(np.median([len(i["t"]) for i in items])))
    med_w = float(np.median([i["x1"] - i["x0"] for i in items]))
    font_w = max(6.0, med_w / med_len)
    for i in items:
        i["font_w"] = font_w

    gx = gutter_x(items, nw, nh)
    if gx is None:
        cols = [items]
    else:
        band = font_w * 2
        right = [i for i in items if i["x0"] >= gx - band]
        rid = {id(i) for i in right}
        left = [i for i in items if i["x1"] <= gx + band and id(i) not in rid]
        cols = [left, right]

    paras = []
    for col in cols:
        if not col:
            continue
        paras.extend(merge_rows_to_paras(to_rows(col, nh, nw), font_w))
    return paras, n_raw


def ocr_page(engine, path, header_crop=HEADER_CROP, scale=SCALE, split_boxes=False):
    return ocr_page_with_count(engine, path, header_crop, scale, split_boxes)[0]


def pick_title(paras):
    """标题判定。

    优先级:
    1. "第N章 <短标题>" —— 章标题, 最可靠
    2. 页面首行, 且满足"短 + 无句读 + 不是编号列表项"
    编号列表项(如 "（一）新产品审定"、"1. xxx") 是目录/条目, 不应当标题。
    """
    for p in paras[:4]:
        t = p.strip()
        if re.match(r"^第[一二三四五六七八九十百零〇]+章[\s　]*\S{0,30}$", t):
            return t
    # 首行候选: 短、无中文句读、非纯编号
    for p in paras[:3]:
        t = p.strip()
        if not (4 <= len(t) <= 45):
            continue
        if re.search(r"[。；，,、！？]", t):
            continue
        # 纯编号/条目行: （一）xxx / 1. xxx / 一、xxx
        if re.match(r"^\s*[(（【\[]?\s*(?:第[一二三四五六七八九十\d]+[条章节项]|[一二三四五六七八九十]+[、．.]|\d+[、．.])\s*[\)）\.]?", t):
            continue
        if re.match(r"^\s*[（(][一二三四五六七八九十\d]+[)）]\s*\S", t):
            continue
        return t
    # 兜底: 首行偏短(公告/办法类文档标题), 允许含少量标点
    if paras:
        t = paras[0].strip()
        if 6 <= len(t) <= 40 and t.count("。") <= 1 and not t.endswith("：") \
                and not re.match(r"^\d+\s*[、．.]", t):
            return t
    return None


def process_file(engine, path, out_path):
    try:
        paras, nboxes = ocr_page_stats(engine, path)
    except Exception as e:
        return False, f"ERR {type(e).__name__}: {e}", 0
    title = pick_title(paras)
    body = [p for p in paras if p.strip() and p.strip() != title]
    lines = []
    if title:
        lines += [f"# {title}", ""]
    seen = set()
    for p in body:
        p = p.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        lines += [p, ""]
    text = "\n".join(lines).rstrip() + "\n"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True, f"boxes={nboxes} paras={len(paras)} chars={len(text)}", nboxes


IMG_ROOT = r"E:/workspace/siliao"
IMAGES_DIR = os.path.join(IMG_ROOT, "Images")
OUT_ROOT = os.path.join(IMG_ROOT, "Markdown")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--folder", default="")
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    imgs = []
    for dirpath, _, files in os.walk(IMAGES_DIR):
        if args.folder and args.folder not in dirpath:
            continue
        for fn in sorted(files):
            if fn.lower().endswith((".jpg", ".jpeg", ".png")):
                imgs.append(os.path.join(dirpath, fn))
    imgs.sort()
    if args.start:
        imgs = imgs[args.start:]
    if args.limit:
        imgs = imgs[:args.limit]
    print(f"[scan] {len(imgs)} images", flush=True)

    engine = RapidOCR()
    t0, ok, fail = time.time(), 0, 0
    log = []
    for i, p in enumerate(imgs, 1):
        rel = os.path.relpath(p, IMAGES_DIR)
        outp = os.path.join(args.out, os.path.splitext(rel)[0] + ".md")
        okc, msg, nb = process_file(engine, p, outp)
        log.append({"src": rel, "ok": okc, "msg": msg, "boxes": nb})
        ok, fail = ok + okc, fail + (not okc)
        if i % 10 == 0 or i == len(imgs):
            el = time.time() - t0
            print(f"  {i}/{len(imgs)} ok={ok} fail={fail} "
                  f"{el/i:.1f}s/img eta={(len(imgs)-i)*el/i/60:.1f}min", flush=True)
    with open(os.path.join(args.out, "_ocr_report.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=1)
    print(f"[done] ok={ok} fail={fail} total={time.time()-t0:.0f}s -> {args.out}")


if __name__ == "__main__":
    main()