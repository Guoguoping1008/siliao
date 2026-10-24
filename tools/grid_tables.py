"""Reconstruct md tables from OCR cell geometry (no vision model needed).

RapidOCR gives one box per cell with its x/y centre. That is enough to rebuild
a table's row and column grid:

  1. cluster cell centres on y  -> row bands  (a row's cells share a baseline)
  2. cluster cell left edges on x -> column anchors
  3. assign each cell to its (row, column) slot and emit a md pipe table

Handles the two layouts in this corpus that naive OCR gets wrong:
  * sideways tables (text rotated 90 deg) -- cells form tall narrow columns,
    detected because their boxes are far taller than wide
  * cross-page tables -- written per page, never merged, per the brief
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image

from make_md import is_blank_leaf, is_headerish, leaf_lines

WORK = Path("E:/workspace/siliao/work")
OUT = Path("E:/workspace/siliao/output2")
IMAGES = Path("E:/workspace/siliao/Images")

MD_ROW = re.compile(r"^\s*\|.*\|\s*$")


def cluster(vals, tol):
    """Group sorted values into runs whose neighbours differ by < tol."""
    out = []
    for v in sorted(vals):
        if out and abs(v - out[-1][-1]) <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def sideways(lines, page_h):
    """True when the page's text is rotated 90 deg.

    Rotated CJK cells are tall and narrow; upright body text is wide and flat.
    """
    body = [l for l in lines if len(l["text"].strip()) > 1]
    if len(body) < 8:
        return False
    tall = sum(1 for l in body if (l["y1"] - l["y0"]) > (l["x1"] - l["x0"]) * 1.6)
    return tall > len(body) * 0.5


def build_table(cells, page_h):
    """Return a list of md rows (list[str]) from cell boxes."""
    if len(cells) < 4:
        return []
    xs = [c["x0"] for c in cells]
    widths = [c["x1"] - c["x0"] for c in cells]
    tol_x = max(28, sorted(widths)[len(widths) // 2] * 0.55)

    # --- rows: cluster centres on the short axis ---
    if sideways(cells, page_h):
        # rotated: a printed row runs vertically, so cluster on x
        col_anchors = cluster([c["x"] for c in cells], tol_x)
        row_groups = defaultdict(list)
        for c in cells:
            idx = min(range(len(col_anchors)), key=lambda i: abs(col_anchors[i] - c["x"]))
            row_groups[idx].append(c)
        n_rows = max(len(col_anchors), 2)
    else:
        row_anchors = cluster([c["y"] for c in cells], 26)
        col_anchors = cluster(xs, tol_x)
        row_groups = defaultdict(list)
        for c in cells:
            idx = min(range(len(row_anchors)), key=lambda i: abs(row_anchors[i] - c["y"]))
            row_groups[idx].append(c)
        n_rows = max(len(row_anchors), 2)

    if not col_anchors:
        return []
    n_cols = len(col_anchors)

    grid = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    for idx, group in row_groups.items():
        if idx >= n_rows:
            continue
        for c in sorted(group, key=lambda c: c["x"]):
            ci = min(range(n_cols), key=lambda i: abs(col_anchors[i] - c["x0"]))
            txt = c["text"].strip()
            if grid[idx][ci] and txt:
                grid[idx][ci] += txt
            else:
                grid[idx][ci] = txt

    # a grid that is nearly empty is not a table
    filled = sum(1 for r in grid for v in r if v)
    if filled < max(4, n_rows * 2) or n_cols < 2:
        return []
    return grid


def to_md(grid):
    rows = [[(c or "").replace("|", "丨").replace("\n", "") for c in r] for r in grid]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return None
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join(["---"] * len(rows[0])) + "|"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def page_cells(payload, part, w, h):
    """Return per-leaf cell lists with headers already removed."""
    leaves = leaf_lines(payload.get("lines", []), w)
    while len(leaves) > 1 and is_blank_leaf(leaves[0][1], w):
        leaves.pop(0)
    res = []
    for _, ls in leaves:
        ls = [l for l in ls if l["y"] >= h * 0.115]
        kept = [l for l in ls if not is_headerish(l, part)] or ls
        res.append(kept)
    return res


def main():
    cache = json.loads((WORK / "ocr_raw.json").read_text(encoding="utf-8"))
    pages = json.loads((WORK / "table_pages.json").read_text(encoding="utf-8"))
    made, tried = 0, 0
    for key in pages:
        payload = cache.get(key)
        if not payload:
            continue
        w, h = Image.open(IMAGES / key).size
        part = key.split("/")[0]
        blocks = []
        for li, cells in enumerate(page_cells(payload, part, w, h), 1):
            if len(cells) < 4:
                continue
            grid = build_table(cells, h)
            md = to_md(grid) if grid else None
            if md:
                blocks.append(md)
        if not blocks:
            continue
        tried += 1
        rel = Path(key)
        d = OUT / rel.parent.name
        d.mkdir(parents=True, exist_ok=True)
        for n, md in enumerate(blocks, 1):
            (d / f"{rel.stem}_tbl_{n}.md").write_text(
                f"<!-- source: {key} | table {n} -->\n\n{md}\n", encoding="utf-8")
        made += 1
    print(f"table pages attempted: {tried}/{len(pages)} -> _tbl_ files written for {made}")


if __name__ == "__main__":
    main()