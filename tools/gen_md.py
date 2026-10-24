"""Generate one markdown file per photo in E:/workspace/siliao/output.

Per image:
  RapidOCR boxes -> drop show-through -> split at the gutter into leaves
  -> drop running head / folio on each leaf -> segment by printed indent
  -> emit md with heading levels

When a spread carries real text on BOTH leaves (e.g. facing tables) both are
kept, in book order (left leaf then right leaf), separated by an explicit
page marker. Tables are emitted per page and never merged across pages.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image

from make_md import (
    ART_MARK, OPEN_MARK, classify_page, in_header_band, is_blank_leaf,
    is_headerish, leaf_lines,
)

WORK = Path("E:/workspace/siliao/work")
OUT = Path("E:/workspace/siliao/output2")
IMAGES = Path("E:/workspace/siliao/Images")


def clean_leaf(lines, part, h):
    lines = [l for l in lines if not in_header_band(l, h)]
    kept = [l for l in lines if not is_headerish(l, part)] or lines
    kept.sort(key=lambda l: (l["y"], l["x"]))
    return kept


CHAP = re.compile(r"^(第[一二三四五六七八九十百]+章)\s*(.*)$")
ART_SPLIT = re.compile(r"^(第[一二三四五六七八九十百]+条)\s*(.*)$", re.S)


def render_leaf(lines, w):
    """Render one leaf.

    Regulation layout rules requested by the user:
      * "## 第二章 审定和登记"  -- chapter number and name on ONE line,
        separated by a space.
      * "第七条国家鼓励..."     -- the article number is pulled out of the
        paragraph and becomes its own "### 第七条" heading, with the article
        body following underneath.
    """
    parts = classify_page(lines, w)
    if not parts:
        return None

    out, first = [], True

    def emit(t):
        nonlocal first
        m = CHAP.match(t)
        if m:
            num, name = m.group(1), m.group(2).strip()
            out.append(f"## {num} {name}".rstrip())
            first = False
            return True
        m = ART_SPLIT.match(t)
        if m:
            num, body = m.group(1), m.group(2).strip()
            out.append(f"### {num}")
            first = False
            if body:
                out.append(body)
            return True
        return False

    for p in parts:
        if isinstance(p, tuple):
            t = p[1]
            if not emit(t):
                if first:
                    out.append(f"# {t}")
                    first = False
                else:
                    out.append(f"### {t}")
        else:
            if emit(p):
                continue
            out.append(p)
    return "\n\n".join(out).strip()


def out_path(key):
    rel = Path(key)
    d = OUT / rel.parent.name
    d.mkdir(parents=True, exist_ok=True)
    return d / (rel.stem + ".md")


def main():
    cache = json.loads((WORK / "ocr_raw.json").read_text(encoding="utf-8"))
    pfile = WORK / "band_patch.json"
    patch = json.loads(pfile.read_text(encoding="utf-8")) if pfile.exists() else {}
    written = blanks = two_leaf = patched = 0
    for key in sorted(cache):
        payload = cache[key]
        try:
            w, h = Image.open(IMAGES / key).size
        except Exception:
            continue
        part = key.split("/")[0]
        all_lines = payload.get("lines", [])
        if not all_lines:
            blanks += 1
            continue

        # Lines recovered by the band re-OCR pass (whole pages fit in one
        # detector pass and occasionally lose a line near the top).
        extra = patch.get(key) or []
        if extra:
            patched += 1
            seen = {l["text"] for l in all_lines}
            merged = list(all_lines)
            for e in extra:
                if e["text"] in seen:
                    continue
                # drop if it is a garbled echo of an existing line
                if any(abs(e["y"] - l["y"]) < 30 and abs(e["x"] - l["x"]) < 140
                       for l in all_lines):
                    continue
                seen.add(e["text"])
                merged.append(e)
            all_lines = merged

        leaves = leaf_lines(all_lines, w)
        # drop a blank left leaf that only shows show-through
        while len(leaves) > 1 and is_blank_leaf(leaves[0][1], w):
            leaves.pop(0)

        chunks = []
        for _, ln in leaves:
            md = render_leaf(clean_leaf(ln, part, h), w)
            if md:
                chunks.append(md)
        if not chunks:
            blanks += 1
            continue
        if len(chunks) > 1:
            two_leaf += 1

        body = "\n\n".join(chunks)
        header = f"<!-- source: {key} -->\n\n"
        out_path(key).write_text(header + body + "\n", encoding="utf-8")
        written += 1

    print(f"written={written} blank={blanks} two_leaf={two_leaf} patched={patched} total={len(cache)}")


if __name__ == "__main__":
    main()