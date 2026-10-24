"""找出该有 rowspan 但没有的表格(合并单元格识别不足)。

判据: md 源里(HEAD 版本)数据行首格为空、上一行首格非空 -> 应该是 rowspan。
现在转成 HTML 后, 看那个位置有没有 rowspan。
"""
import collections
import os
import re
import subprocess

repo = r"E:/workspace/siliao"
base = os.path.join(repo, "minimax")

ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh]\b([^>]*)>(.*?)</t[dh]>", re.S | re.I)


def md_rows_of(text):
    """HEAD 版 md 里的表格行 -> [[cells]]"""
    rows = []
    for l in text.splitlines():
        s = l.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(c and set(c) <= set("-:") for c in cells if c):
            continue
        rows.append(cells)
    return rows


def html_rows_of(text):
    out = []
    for m in re.finditer(r"<table\b.*?</table>", text, re.S | re.I):
        for rm in ROW.finditer(m.group(0)):
            cells = []
            for cm in CELL.finditer(rm.group(1)):
                d = dict(re.findall(r'(\w+)="([^"]*)"', cm.group(1)))
                cells.append((d, re.sub(r"<[^>]+>", "", cm.group(2)).strip()))
            out.append(cells)
    return out


out = subprocess.run(
    ["git", "-C", repo, "-c", "core.quotepath=false",
     "ls-files", "-z", "minimax"],
    capture_output=True).stdout.decode("utf-8", "ignore")
names = [n for n in out.split("\0") if n.endswith(".md")]

missing = []
for n in names:
    p = os.path.join(repo, n.replace("/", os.sep))
    if not os.path.exists(p):
        continue
    new = open(p, encoding="utf-8").read()
    if "<table" not in new:
        continue
    old = subprocess.run(["git", "-C", repo, "show", f"HEAD:{n}"],
                         capture_output=True).stdout.decode("utf-8", "ignore")
    md = md_rows_of(old)
    if not md:
        continue
    hr = html_rows_of(new)
    # md 数据行里"首格空且上一行首格非空"的次数
    want = 0
    for i in range(1, len(md)):
        if md[i] and md[i][0] == "" and md[i - 1] and md[i - 1][0] != "":
            want += 1
    have = sum(1 for row in hr for d, t in row
               if "rowspan" in d and int(d["rowspan"]) > 1)
    if want > have:
        missing.append((n, want, have))

print(f"应加 rowspan 但没加够的页: {len(missing)}")
tot_w = tot_h = 0
for n, w, h in missing[:25]:
    print(f"  {n}")
    print(f"      应有 {w} 处, 实有 {h} 处")
    tot_w += w
    tot_h += h
print(f"合计: 应有 {tot_w}, 实有 {tot_h}")
