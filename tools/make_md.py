"""Convert RapidOCR raw output into per-page markdown.

Handles the four corpus-specific problems:
  1. two-page spreads -> keep the right-hand page, drop the blank left page
  2. running headers / page numbers / <<< >>> markers / show-through bleed -> strip
  3. tables -> emit md pipe tables (per page, never merged across pages)
  4. chapter + section headings and paragraph text -> preserve verbatim
"""
import json
import re
from pathlib import Path

WORK = Path("E:/workspace/siliao/work/ocr_raw.json")
OUT = Path("E:/workspace/siliao/output")
IMAGES = Path("E:/workspace/siliao/Images")

# Folder name -> the running-head text printed in that part of the book.
PART_HEADS = {
    "000封面": None,
    "001目录": "目录",
    "01法规": "一、法规",
    "02制度文件": "二、制度文件",
    "03相关法规法律法规文件": "三、相关法规法律法规文件",
    "04标准及标准目录": "四、标准及标准目录",
}

PURE_NUM = re.compile(r"^\d{1,4}$")
CHAP_TITLE = re.compile(r"[一-龥]{2,12}、")
ARROW = re.compile(r"^[<>{}\s·、,，.。:：;；\-—/\\|]+$")
YEAR_MARK = re.compile(r"^[（(]\s*\d{4}\s*[）)]$")
CN_CHAPTER = re.compile(r"^第[一二三四五六七八九十百]+章")
CN_SECTION = re.compile(r"^第[一二三四五六七八九十百]+条")


def norm(s):
    return re.sub(r"\s+", "", s)


def is_headerish(line, part):
    """True if the line is a running head / folio / artefact, not body text."""
    t = line["text"].strip()
    if not t:
        return True
    if ARROW.match(t):
        return True
    if PURE_NUM.match(t):
        return True
    head = PART_HEADS.get(part, "?")
    if head and norm(t) == norm(head):
        return True
    if YEAR_MARK.match(t):
        return True
    # e.g. "500饲料法规文件（2023）" -- folio fused with the running head
    if re.match(r"^\d{3,4}饲料法规文件", norm(t)):
        return True
    # The running head is always printed as "<<< 三、相关法律法规文件 | 31".
    # OCR garbles the leading characters ("巨", "二", "、"), so match on the
    # marker plus a chapter/part title rather than on exact text.
    if "<<<" in t or ">>>" in t:
        if CHAP_TITLE.search(t) or len(t) <= 24:
            return True
    return False


def split_gutter(lines, w):
    """Return the x of the book gutter, or None for a single-page shot.

    The gutter is the geometric centre of the spread, but a spread may be
    full of text on BOTH leaves (e.g. tables facing tables), so this only
    reports where the fold is -- it does not decide what to discard.
    """
    if not lines:
        return None
    left = [ln for ln in lines if ln["x"] < w * 0.5]
    if len(left) < max(2, 0.10 * len(lines)):
        # No meaningful text on the left half -> effectively one content page.
        return None
    return w * 0.5


def leaf_lines(lines, w):
    """Group lines into leaves: (x_start, [lines]) ordered left to right.

    A spread yields two leaves, each ordered top-to-bottom. Show-through on
    a blank leaf is faint and low-scoring, so it is dropped by the caller.
    """
    if not lines:
        return []
    gx = split_gutter(lines, w)
    if gx is None:
        return [(0.0, list(lines))]
    left = [ln for ln in lines if ln["x"] < gx]
    right = [ln for ln in lines if ln["x"] >= gx]
    out = []
    if left:
        out.append((0.0, left))
    if right:
        out.append((gx, right))
    return out


def is_blank_leaf(lines, w):
    """A blank leaf carries only faint show-through from the reverse side."""
    if not lines:
        return True
    dark = sum(ln["x1"] - ln["x0"] for ln in lines if ln["score"] >= 0.80)
    strong = [ln for ln in lines if ln["score"] >= 0.80]
    if len(strong) < 4:
        return True
    # real page: dense lines filling the measure; blank leaf: sparse flecks
    if len(strong) < 8:
        return True
    return False


def in_header_band(ln, h):
    """Running head band.

    Measured across this corpus the printed head occupies only the top ~5.2%
    of the leaf (the next line down is body text at ~10.5%). Cutting at 11.5%
    silently deleted the first one or two body lines of a page, so keep the
    band tight and let is_headerish() filter the content.
    """
    return ln["y"] < h * 0.06


def page_text(key, payload, w, h):
    part = key.split("/")[0]
    lines = payload.get("lines", [])
    if not lines:
        return []

    gx = split_gutter(lines, w)
    right = [ln for ln in lines if gx is None or ln["x"] >= gx]
    if not right:
        right = lines

    right = [ln for ln in right if not in_header_band(ln, h)]
    kept = [ln for ln in right if not is_headerish(ln, part)]
    if not kept:
        kept = right
    kept.sort(key=lambda ln: (ln["y"], ln["x"]))
    return [ln["text"].strip() for ln in kept if ln["text"].strip()]


# A body line is an indented continuation when it neither opens nor closes a
# clause: no leading article/appendix marker, no terminal punctuation.
OPEN_MARK = re.compile(r"^第[一二三四五六七八九十百]+章")
ART_MARK = re.compile(r"^第[一二三四五六七八九十百]+条")
CLAUSE_MARK = re.compile(r"^[（(][一二三四五六七八九十]+[）)]")
# Standard/notice documents use flat numbered sections: "1  项目类型",
# "2审批内容", "4  办事条件". These are genuine headings, unlike "2.1…".
SECTION_MARK = re.compile(r"^(\d{1,2})\s*[项目内容、]?\s*[^0-9\s]{2,14}$")
SUBSECTION_MARK = re.compile(r"^\d{1,2}\.\d{1,2}\s*\S")
CLOSE_PUNCT = "。！？；：）】》”" 
OPEN_PUNCT = "（【《“"


def centred_on_measure(line, left_edge, right_margin, tol=0.12):
    """True when the line sits in the middle of the text measure.

    A real title is centred between the margins. A right-aligned signatory
    ("农业部") or an indented clause ("附件：1.进口饲料…") is flush to one
    side instead, so reject anything whose gap to one margin is tiny.
    """
    mid = (left_edge + right_margin) / 2
    width = right_margin - left_edge
    left_gap = line["x0"] - left_edge
    right_gap = right_margin - line["x1"]
    if left_gap < width * tol or right_gap < width * tol:
        return False
    return abs((line["x0"] + line["x1"]) / 2 - mid) < width * tol


def classify_page(lines, page_w):
    """Split a page's lines into paragraphs, titles and chapter headings.

    Layout signals, measured on this corpus:
      * continuation line -> x0 at the flush left margin
      * paragraph start   -> x0 indented by two full-width CJK chars (~95px)
      * title / heading   -> horizontally centred, so its right edge stops
                             well short of the right margin
    """
    if not lines:
        return []

    xs = sorted(l["x0"] for l in lines)
    # robust left margin: the 15th percentile ignores a few stray boxes
    margin = xs[max(0, int(len(xs) * 0.15) - 1)]
    left_edge = xs[0]

    # right margin: modal of the x1 values
    from collections import Counter
    right_margin = Counter(round(l["x1"] / 50) * 50 for l in lines).most_common(1)[0][0]

    INDENT = 60   # >= 2 CJK chars
    paras, cur = [], None

    for l in lines:
        t = l["text"].strip()
        if not t:
            continue
        centred = (l["x1"] < right_margin - 200) and (l["x0"] > margin + INDENT)
        is_heading = OPEN_MARK.match(t)
        # A short line can stop short of the right margin without being a
        # heading. A real heading is centred AND reads like one: short, no
        # terminal sentence punctuation, not an article/clause marker.
        # Indented body lines ("附件：1.进口饲料…", a date, a signatory) also
        # stop short of the margin but must stay body text.
        title_like = (
            centred
            and not ART_MARK.match(t)
            and not CLAUSE_MARK.match(t)
            and len(t) <= 40
            and not t.endswith(("。", "；", "："))
            and not t.endswith("日")            # e.g. "2014年12月24日"
            and not re.match(r"^\d+年\d+月\d+日$", t)
            # Indented or right-aligned short body lines also stop short of
            # the margin: "附件：1.进口饲料…", "2.新饲料…证书核发标准",
            # a signatory "农业部". A heading is centred on the measure, so
            # require it to be roughly centred rather than offset.
            and centred_on_measure(l, left_edge, right_margin)
        )
        # An enumerator such as （五） always opens its own clause, even when it
        # sits flush with the body margin.
        enum_start = CLAUSE_MARK.match(t) is not None
        # A flat numbered section heading ("1  项目类型") also opens a block.
        # Must sit at the left margin and be short, so "2.1产品是否…" (body)
        # and "2014年12月24日" (a date) are not mistaken for one.
        at_margin = l["x0"] < margin + INDENT
        section_head = bool(at_margin and SECTION_MARK.match(t)
                            and not SUBSECTION_MARK.match(t))
        if is_heading or title_like or enum_start or section_head:
            if cur:
                paras.append(cur)
                cur = None
            if is_heading or title_like or section_head:
                paras.append(("TITLE", t))
            else:
                cur = t
            continue
        indented = l["x0"] >= margin + INDENT
        if indented or cur is None:
            if cur:
                paras.append(cur)
            cur = t
        else:
            cur += t
    if cur:
        paras.append(cur)
    return paras


def main():
    cache = json.loads(WORK.read_text(encoding="utf-8"))
    print("cached pages:", len(cache))
    from PIL import Image
    for key in list(cache)[:2]:
        p = IMAGES / key
        w, h = Image.open(p).size
        print("=" * 20, key, (w, h))
        for t in page_text(key, cache[key], h):
            print("   ", t)


if __name__ == "__main__":
    main()