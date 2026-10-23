"""全量质检: 统计 minimax/ 输出的健康度。

检查项:
1. 页数对齐: 每个源图对应一个 md
2. 空文件 / 极短文件
3. 页眉残留 (>>> <<< | 饲料法规文件)
4. 模型元话术残留 (图像中的文字 / 无法识别 / 抱歉)
5. 代码围栏 / 思维链残留
6. 层级分布: # / ## / ###
7. 标题识别率 (有 # 的页占比)
8. 碎片率 (长度<=4 的行占比) —— 区分正文可用与表格崩塌
"""
import os
import re
import sys
import json
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mm_ocr

ROOT = mm_ocr.DST_ROOT
SRC = mm_ocr.SRC_ROOT


def main():
    src_map = {}
    for dp, _, fs in os.walk(SRC):
        for f in fs:
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                rel = os.path.relpath(os.path.join(dp, f), SRC).replace("\\", "/")
                src_map[os.path.splitext(rel)[0]] = rel

    files = []
    for dp, _, fs in os.walk(ROOT):
        for f in fs:
            if f.endswith(".md"):
                files.append(os.path.join(dp, f))
    files.sort()

    st = Counter()
    issues = defaultdict(list)
    h1n = h2n = h3n = 0
    total_chars = 0
    frag_hist = Counter()
    per_dir = defaultdict(lambda: Counter())

    for p in files:
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        key = os.path.splitext(rel)[0]
        d = os.path.dirname(rel) or "."
        t = open(p, encoding="utf-8").read()
        st["files"] += 1
        per_dir[d]["files"] += 1
        if key not in src_map:
            issues["orphan"].append(rel)
        body = t.strip()
        if not body:
            st["empty"] += 1
            per_dir[d]["empty"] += 1
            continue
        total_chars += len(body)
        if len(body) < 120:
            st["tiny"] += 1
            issues["tiny"].append((rel, len(body)))
        if re.search(r"[<>]{3}", t):
            st["header_leak"] += 1
            issues["header_leak"].append(rel)
        if re.search(r"(图像中的文字|图片中(?:识别|检测|的)|无法识别|没有任何文字|一片空白|请上传)", t):
            st["meta_leak"] += 1
            issues["meta_leak"].append(rel)
        if "```" in t:
            st["fence"] += 1
            issues["fence"].append(rel)
        if "<think>" in t or "</think>" in t:
            st["think"] += 1
            issues["think"].append(rel)
        h1 = len(re.findall(r"^# ", t, re.M))
        h2 = len(re.findall(r"^## ", t, re.M))
        h3 = len(re.findall(r"^### ", t, re.M))
        h1n += h1
        h2n += h2
        h3n += h3
        if h1:
            st["has_h1"] += 1
            per_dir[d]["has_h1"] += 1
        if h3:
            st["has_h3"] += 1
        lines = [l for l in t.split("\n") if l.strip()]
        short = [l for l in lines if len(l.strip()) <= 4]
        r = len(short) / max(1, len(lines))
        frag_hist[round(r * 10) / 10] += 1
        if r >= 0.6:
            st["fragmented"] += 1
            issues["fragmented"].append((rel, round(r, 2)))
        # 表格页
        if t.count("\n|") > 2:
            st["table"] += 1

    missing = [k for k in src_map if not os.path.exists(
        os.path.join(ROOT, k.replace("/", os.sep) + ".md"))]
    st["missing"] = len(missing)

    print("=" * 62)
    print("MiniMax OCR 全量质检报告")
    print("=" * 62)
    print(f"源图数        : {len(src_map)}")
    print(f"输出 md 数    : {st['files']}")
    print(f"缺失          : {st['missing']}   {missing[:10]}")
    print(f"空文件        : {st['empty']}")
    print(f"极短(<120字)  : {st['tiny']}")
    print(f"页眉残留      : {st['header_leak']}")
    print(f"模型元话术残留: {st['meta_leak']}")
    print(f"代码围栏残留  : {st['fence']}")
    print(f"思维链残留    : {st['think']}")
    print(f"孤儿文件      : {len(issues['orphan'])}")
    print(f"碎片率>=0.6   : {st['fragmented']}")
    print(f"含表格的页    : {st['table']}")
    print("-" * 62)
    print(f"总字符数      : {total_chars:,}")
    print(f"# 一级标题     : {h1n}   (含标题的页 {st['has_h1']})")
    print(f"## 二级标题    : {h2n}")
    print(f"### 三级标题   : {h3n}   (含章节条的页 {st['has_h3']})")
    print("-" * 62)
    print("碎片率分布 (长度<=4的行占比):")
    for k in sorted(frag_hist):
        bar = "#" * max(1, frag_hist[k] // 5)
        print(f"  {k:4.1f}  {frag_hist[k]:4d} {bar}")
    print("-" * 62)
    print("分目录:")
    for d in sorted(per_dir):
        c = per_dir[d]
        print(f"  {d:28s} 文件={c['files']:4d} 空={c['empty']:3d} 有#标题={c['has_h1']:3d}")
    print("-" * 62)
    for k in ("tiny", "header_leak", "meta_leak", "fence", "think", "orphan", "fragmented"):
        if issues[k]:
            print(f"[{k}] {len(issues[k])} 个:")
            for x in issues[k][:12]:
                print("   ", x)
    print("=" * 62)

    out = {k: v for k, v in st.items()}
    out["missing_list"] = missing
    out["issues"] = {k: v[:200] for k, v in issues.items()}
    out["chars"] = total_chars
    out["h1"] = h1n
    out["h2"] = h2n
    out["h3"] = h3n
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mm_ocr_qa.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
