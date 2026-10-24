#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 错字自动纠正 —— siliao / output2

只做**白名单**替换, 且每条规则带上下文约束, 避免误伤合法词。
单字类错字(治/脏/洲/脉)一律不碰 —— 它们本身是常用词。

【关键坑 · 必须带上下文约束的规则】
    「投人」有两种:
      - 投人生产  -> 投入生产   (OCR 错, 人->入)
      - 投人品    -> 投人品     (正确! 农业投入品, 是法定术语)
    盲目全局替换会把 13 处「投人品」改坏。
    对策: 规则支持「前/后否定上下文」(neg_before / neg_after)。

用法:
    python _fix_typos.py --scan                # 只扫描, 打印命中清单(不改文件)
    python _fix_typos.py --apply               # 实际改写 (先备份到 .bak)
    python _fix_typos.py --apply --no-backup   # 实际改写 (不备份)
    python _fix_typos.py --scan --json out.json # 扫描结果存 JSON
"""
import argparse
import json
import os
import re
import shutil
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
OUT2 = os.path.join(REPO, "output2")

# ---------------------------------------------------------------------------
# 错字规则表
#   wrong  : 要替换的错误串
#   right  : 正确串
#   neg_before : 若匹配位置前面紧邻这些串, 则**跳过**(该处是合法词)
#   neg_after  : 若匹配位置后面紧邻这些串, 则**跳过**
#   note   : 说明
# ---------------------------------------------------------------------------
RULES = [
    # --- 确认过的 OCR 错字 ---
    dict(wrong="投人", right="投入",
         neg_after=["品"],           # 投人品 / 投入品监管 / 投入品减量 —— 法定术语, 别动
         note="人->入; 但「投人品」是法定术语, 后接「品」时跳过"),
    dict(wrong="中请", right="申请", note="中->申"),
    # 私舞 -> 徇私舞弊
    # 坑: 替换结果「徇私舞弊」本身含「私舞」, 规则非幂等, 第二遍会再改一遍
    #      变成「徇徇私舞弊」。必须加 neg_before 把「徇」排除掉。
    dict(wrong="私舞", right="徇私舞弊",
         neg_before=["徇"],       # 已经是「徇私舞弊」了, 别再改
         note="漏字; 原文「滥用职权、玩忽职守、私舞的」"),
    # 清理: 重复改写留下的畸形
    dict(wrong="徇徇私舞弊", right="徇私舞弊", note="重复替换清理"),
    dict(wrong="徇私舞弊弊", right="徇私舞弊", note="重复替换清理"),
    dict(wrong="坦生", right="报告", note="报->坦"),
    dict(wrong="提世", right="提供", note="供->世"),
    dict(wrong="出u", right="试验", note="试->u"),
    dict(wrong="左效", right="有效", note="有->左"),
    dict(wrong="报生)", right="报告等)", note="等->生"),
    dict(wrong="编生", right="编制", note="制->生"),
    dict(wrong="纳人", right="纳入", note="入->人"),
    dict(wrong="理吿", right="理工", note="工->吿"),
    dict(wrong="认i", right="认定", note="定->i"),
    dict(wrong="户检", right="尸检", note="尸->户"),
    dict(wrong="户体", right="尸体", note="尸->户"),
    dict(wrong="形吿", right="形容", note="容->吿"),
    # 注: 单字规则「吿」->「告」已移除 —— 全库 0 命中, 且单字规则有误伤风险。
    #     单字类错字(治/脏/洲/脉)一律不碰: 它们本身是常用词。
]

# 规则命中前的排除: 已在正确词里的子串, 避免「投人」命中「投入品」之外的误伤
SKIP_FILES_SUFFIX = (".bak",)


def iter_md_files(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns
                  if d not in ("_rag_index_split", "_chunk_split", "__pycache__")]
        for fn in fns:
            if fn.endswith(".md") and not fn.startswith("_"):
                yield os.path.join(dp, fn)


def compile_rules():
    """长规则优先 —— 「徇私舞弊弊」必须在「私舞」之前匹配,
    否则「私舞」先命中并产出「徇徇私舞弊弊」, 清理规则永远等不到。"""
    out = []
    for r in sorted(RULES, key=lambda x: -len(x["wrong"])):
        out.append((re.compile(re.escape(r["wrong"])), r))
    return out


def find_hits(text, compiled):
    """返回 [(start, end, wrong, right, rule)]"""
    hits = []
    for rx, r in compiled:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            before = text[max(0, s - 4):s]
            after = text[e:e + 4]
            if any(before.endswith(nb) for nb in r.get("neg_before", [])):
                continue
            if any(after.startswith(na) for na in r.get("neg_after", [])):
                continue
            hits.append((s, e, r["wrong"], r["right"], r))
    # 去重叠: 同一位置优先取**更长的匹配**(否则 "私舞" 会盖掉 "徇徇私舞弊")
    # 排序: 长的匹配排前面; 同起点时长的优先。保证「徇私舞弊弊」整体先被吃掉。
    hits.sort(key=lambda h: (-(h[1] - h[0]), h[0]))
    out, taken = [], []
    for h in hits:
        if any(h[0] < t[1] and h[1] > t[0] for t in taken):
            continue
        taken.append(h)
        out.append(h)
    out.sort(key=lambda h: h[0])
    return out


def apply_hits(text, hits):
    parts, pos = [], 0
    for s, e, wrong, right, _ in hits:
        parts.append(text[pos:s])
        parts.append(right)
        pos = e
    parts.append(text[pos:])
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true", help="只扫描不改写")
    ap.add_argument("--apply", action="store_true", help="改写文件")
    ap.add_argument("--no-backup", action="store_true", help="改写时不备份")
    ap.add_argument("--json", help="扫描结果写入 JSON")
    args = ap.parse_args()

    if not (args.scan or args.apply):
        ap.print_help()
        return 0

    compiled = compile_rules()
    total_hits = 0
    files_touched = 0
    report = []

    for path in iter_md_files(OUT2):
        if path.endswith(SKIP_FILES_SUFFIX):
            continue
        text = open(path, encoding="utf-8").read()
        hits = find_hits(text, compiled)
        if not hits:
            continue
        files_touched += 1
        total_hits += len(hits)
        rel = os.path.relpath(path, OUT2).replace("\\", "/")
        by_rule = {}
        for s, e, wrong, right, r in hits:
            by_rule.setdefault((wrong, right, r["note"]), []).append(
                text[max(0, s - 16):e + 16].replace("\n", " "))
        report.append(dict(file=rel, hits=len(hits),
                           rules=[{"wrong": w, "right": rt, "note": nt,
                                   "count": len(ctxs), "contexts": ctxs[:5]}
                                  for (w, rt, nt), ctxs in by_rule.items()]))

        if args.apply:
            new_text = apply_hits(text, hits)
            if not args.no_backup:
                shutil.copy2(path, path + ".bak")
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_text)

    print("=" * 74)
    print(f"命中 {total_hits} 处, 涉及 {files_touched} 个文件")
    print("=" * 74)
    for r in sorted(report, key=lambda x: -x["hits"]):
        print(f"\n{r['file']}  ({r['hits']} 处)")
        for rr in r["rules"]:
            print(f"   {rr['wrong']} -> {rr['right']}   x{rr['count']}   [{rr['note']}]")
            for c in rr["contexts"][:2]:
                print(f"        ...{c}...")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"\n清单已写入: {args.json}")

    if args.apply:
        print("\n已改写。" + ("" if args.no_backup else "  原文件已备份为 .bak"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
