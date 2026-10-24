"""重新生成单个表格页的 md(走 MiniMax API + 旋正图)。

用法:
    python mm_table_fix.py 0031          # 干跑, 看计划
    python mm_table_fix.py 0031 --apply   # 执行

流程(依据 skill scanned-table-ocr-md):
1. 找源图(按 stem 在多个候选根下递归查, 同名多份取层级最深的)
2. 侧转检测: 旋转 90/270 两个方向, 送 API, 用**质量门**挑最好的
3. 质量门:
   - 输出以 | 开头(是表格)
   - 实质行 >= 3, 空行率 < 50%
   - 表头列数 == 数据列数
4. 去空行(先判空行, 再判分隔行; 不能用"去掉竖线后为空"当分隔行判据)
5. 写回(按 stem 递归查, 取层级最深的那份)
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request

from PIL import Image

API_URL = "https://api.minimaxi.com/v1/chat/completions"
MODEL = "MiniMax-Text-01"
FALLBACK_MODEL = "MiniMax-M3"
MAX_TOKENS = 8000
TIMEOUT = 120
MAX_RETRY = 4
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

TABLE_PROMPT = (
    "这是一页中文书籍扫描页，其中的表格是旋转 90 度印刷的。\n"
    "请把表格完整转写成 Markdown 表格。\n\n"
    "严格要求：\n"
    "1. 只输出 Markdown 管道表格，以 | 开头，以 |---|---| 之类分隔表头。\n"
    "2. 列数必须与原图完全一致；表头行和每个数据行的列数要相同。\n"
    "3. 单元格内容照抄原文，不要改写、不要补字、不要总结。\n"
    "4. 一个单元格内有换行的，用空格连接写成同一格。\n"
    "5. 合并单元格（跨行的）用空格表示，不要向下重复填充。\n"
    "6. 表格外的正文、页眉、页码、装饰符号一律不要输出。\n"
    "7. 表格上方的标题行（如果存在）用 # 输出，一行。\n"
    "8. 不要输出任何解释文字。"
)


def _api_key():
    """和 mm_ocr.py 保持一致: 读 profile 的 .env 里的 MINIMAX_CN_API_KEY"""
    env = r"C:/Users/Administrator/AppData/Local/hermes/profiles/qingmang/.env"
    with open(env, encoding="utf-8") as f:
        for line in f:
            if line.startswith("MINIMAX_CN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("MINIMAX_CN_API_KEY not found")


API_KEY = _api_key()


# ---------- 源图定位 ----------
def find_src(stem):
    """按 stem 递归找源图, 同名多份取层级最深的"""
    best = None
    best_depth = -1
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
                    best_depth = d
                    best = os.path.join(dp, f)
    return best


def find_dst(stem):
    """按 stem 递归找目标 md, 同名多份取层级最深的(重组后平铺路径是残留副本)"""
    best = None
    best_depth = -1
    for dp, dns, fns in os.walk(MM_ROOT):
        for f in fns:
            if f != stem + ".md":
                continue
            d = dp.count(os.sep)
            if d > best_depth:
                best_depth = d
                best = os.path.join(dp, f)
    return best


# ---------- 图像处理 ----------
def prep(img, rotate=0, crop_header=True):
    im = Image.open(img)
    if crop_header:
        w, h = im.size
        im = im.crop((0, int(h * HEADER_CROP), w, h))
    if rotate:
        im = im.rotate(rotate, expand=True)
    # 长边缩到 TARGET_W
    w, h = im.size
    if max(w, h) > TARGET_W:
        s = TARGET_W / max(w, h)
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


def ocr_bytes(img_bytes, model=MODEL, prompt=TABLE_PROMPT):
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
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


# ---------- 清洗 + 质量门 ----------
def is_empty_row(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return all(not c for c in cells)


def is_sep_row(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(c and set(c) <= set("-:") for c in cells)


def ncols(line):
    return len(line.strip().strip("|").split("|"))


def clean_table(raw):
    """提取 md 表格块, 去空行, 返回 (行列表, 统计)"""
    lines = raw.splitlines()
    # 先按行判定空行/分隔行
    kept = []
    for ln in lines:
        s = ln.rstrip()
        if not s.strip().startswith("|"):
            continue
        if is_empty_row(s):
            continue
        kept.append(s)
    if not kept:
        return [], {"rows": 0, "empty_rate": 1.0, "cols_head": 0, "cols_body": 0}
    # 找到分隔行, 它前面是表头
    sep_idx = None
    for i, ln in enumerate(kept):
        if is_sep_row(ln):
            sep_idx = i
            break
    if sep_idx is None or sep_idx == 0:
        return kept, {"rows": len(kept), "empty_rate": 0.0,
                      "cols_head": ncols(kept[0]), "cols_body": ncols(kept[-1])}
    header = kept[:sep_idx + 1]
    body = kept[sep_idx + 1:]
    out = header + body
    ch = ncols(header[0])
    cbs = [ncols(b) for b in body]
    mode = max(set(cbs), key=cbs.count) if cbs else 0
    return out, {"rows": len(out), "empty_rate": 0.0,
                 "cols_head": ch, "cols_body": mode,
                 "body_col_hist": {c: cbs.count(c) for c in set(cbs)}}


def quality(out, st):
    """质量门: 是表格 / 实质行>=3 / 表头列数==数据列数"""
    if not out or not out[0].strip().startswith("|"):
        return False, "不是表格"
    body = out[2:] if len(out) > 2 else []
    if len(body) < 3:
        return False, f"实质行只有 {len(body)}"
    if st["cols_head"] != st["cols_body"]:
        return False, f"列数不一致 表头{st['cols_head']} vs 数据{st['cols_body']}"
    return True, "OK"


def main():
    stem = sys.argv[1]
    apply = "--apply" in sys.argv

    # 期望的表头关键词(用于在多个旋转/重试结果里挑**正确**的那份)。
    # 坑: 不能只靠"行数多"或"列数多"来挑 —— 模型会**幻觉**出一张列数多、
    #      表头自洽但内容完全无关的表。所以要拿已知的表头关键词去校验。
    # 用法: --hdr 序号,试验机构名称,联系电话 ...
    expect_hdr = []
    for a in sys.argv[1:]:
        if a.startswith("--hdr="):
            expect_hdr = [x for x in a.split("=", 1)[1].split(",") if x]
    if not expect_hdr:
        # 没给就用**现有 md 的表头**做基准(现有 md 至少表头是对的)
        dst0 = find_dst(stem)
        if dst0:
            for ln in open(dst0, encoding="utf-8").read().splitlines():
                if ln.strip().startswith("|"):
                    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                    expect_hdr = [c for c in cells if c and set(c) <= set("-:") is False]
                    break
    # 只保留"有区分度"的词(去掉重复出现的通用词)
    if expect_hdr:
        seen = set()
        uniq = []
        for c in expect_hdr:
            if c and c not in seen:
                seen.add(c)
                uniq.append(c)
        expect_hdr = uniq
    print("期望表头关键词:", expect_hdr)

    src = find_src(stem)
    dst = find_dst(stem)
    print(f"源图: {src}")
    print(f"目标: {dst}")
    if not src or not dst:
        sys.exit(1)

    best = None
    for rot in (0, 90, 270):
        try:
            img = prep(src, rotate=rot)
        except Exception as e:
            print(f"  rot={rot} 预处理失败: {e}")
            continue
        for attempt in range(MAX_RETRY):
            model = MODEL if attempt < 2 else FALLBACK_MODEL
            try:
                raw = ocr_bytes(img, model=model)
            except Exception as e:
                print(f"  rot={rot} try{attempt} {model} 失败: {e}")
                time.sleep(1.5)
                continue
            out, st = clean_table(raw)
            ok, why = quality(out, st)
            hdr = out[0] if out else ""
            print(f"  rot={rot:3d} try{attempt} {model:18s} 行={st['rows']:3d} "
                  f"表头列={st['cols_head']} 数据列={st['cols_body']} -> {why}")
            print(f"          表头: {hdr[:120]}")
            if ok:
                # 打分: **表头与期望关键词的匹配度**优先, 再列数, 再行数。
                # 坑1: 只按行数打分会选中"列数少但行数多"的错读结果。
                # 坑2: 只按列数打分会选中**幻觉表** —— 模型会编一张列数多、
                #      表头自洽但内容完全无关的表(实测 0031 rot=90 出了
                #      14 列的"样品编号/样品状态/检测人"表, 全是编的)。
                hit = sum(1 for k in expect_hdr if k in hdr)
                score = (hit, st["cols_body"], st["rows"])
                if best is None or score > best[0]:
                    best = (score, rot, out, st)
                break

    if not best:
        print("全部尝试失败")
        sys.exit(1)

    score, rot, out, st = best
    print()
    print(f"采用 rot={rot}  行={st['rows']}  列={st['cols_head']}")
    print("=" * 78)
    for ln in out:
        print(ln)

    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")
        return

    # 写回: 标题 + 表格
    old = open(dst, encoding="utf-8").read()
    title = ""
    for ln in old.splitlines():
        if ln.startswith("# "):
            title = ln
            break
    content = (title + "\n\n" if title else "") + "\n".join(out) + "\n"
    # 写之前重新确认目标还在(语料可能被重组)
    dst2 = find_dst(stem) or dst
    with open(dst2, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n已写入: {dst2}")


if __name__ == "__main__":
    main()
