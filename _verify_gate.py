#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
门禁有效性验证 —— 证明「B 类拦截 + C 类表格隔离」确实消除了错配风险

方法:
  1. 构造一组「机构名 + 联系电话」查询(这批字段是 错配后危害最大的)
  2. 在【未过滤全库】上跑检索 -> 统计有多少 chunk 会让模型拿到
     机构名和电话但行列已断的文本
  3. 在【过滤后 A+C(prose)】上跑同样检索 -> 对比
  4. 断言: 过滤后「表格型错配风险 chunk」命中数必须显著下降

用法:
    python _verify_gate.py            # 跑验证并打印报告
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _audit_corpus as A

REPO = A.REPO
OUT2 = A.OUT2
SPLIT = os.path.join(OUT2, "_rag_index_split")
CHUNK = os.path.join(OUT2, "_chunk_split")

# 高风险查询: 机构名 + 联系方式/地址 —— 表格崩塌后最容易被错配
QUERIES = [
    ("中国农业大学", "联系电话"),
    ("南京农业大学", "试验场地地址"),
    ("扬州大学", "报告签发人"),
    ("中国科学院亚热带农业生态研究所", "机构类型"),
    ("浙江大学", "试验场地名称"),
    ("沈阳农业大学", "证书编号"),
]

# 判定一个 chunk 是否属于「表格型错配风险」:
# 同一 chunk 内同时出现 机构名 与 电话/地址类字段, 但两者不在同一行
PHONE = re.compile(r"\d{3,4}-\d{7,8}")
INST = re.compile(r"[一-鿿]{2,12}(?:大学|科学院|研究所|学院|中心|监测所|质检所|实验室)")
ADDR = re.compile(r"[一-鿿]{2,10}(?:省|市|区|县)[一-鿿]{0,20}(?:路|镇|街道|号)")


def risky_chunks(text):
    """统计「模型会把 A 机构的联系方式配给 B 机构」的证据条数

    判据: 同一 chunk 内, 存在至少 2 个不同机构名, 且至少 1 个联系方式字段,
          但**机构名与联系方式不在同一行** —— 这正是表格崩塌后的典型形态:
          机构名单独成行, 电话号单独成行, 行列关系已断, 模型只能自己配。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return 0

    inst_lines = set()
    inst_names = set()
    for i, l in enumerate(lines):
        for m in INST.finditer(l):
            inst_lines.add(i)
            inst_names.add(m.group(0))

    field_lines = set()
    for i, l in enumerate(lines):
        if PHONE.search(l) or ADDR.search(l):
            field_lines.add(i)

    if len(inst_names) < 2 or not field_lines:
        return 0

    # 联系方式所在行没有机构名 -> 行列已断, 模型会错配
    orphan = [i for i in field_lines if i not in inst_lines]
    if not orphan:
        return 0
    return len(orphan)


def load_corpus(mode):
    """mode: 'raw' | 'filtered'"""
    chunks = []
    if mode == "raw":
        for dp, dns, fns in os.walk(OUT2):
            dns[:] = [d for d in dns if d not in ("_rag_index_split", "_chunk_split")]
            for fn in fns:
                if fn.endswith(".md") and not fn.startswith("_"):
                    p = os.path.join(dp, fn)
                    chunks.append((os.path.relpath(p, REPO).replace("\\", "/"),
                                   open(p, encoding="utf-8").read()))
    else:
        # A 类: 整篇进索引
        adir = os.path.join(SPLIT, "A-INDEX")
        for fn in os.listdir(adir):
            if fn.endswith(".md"):
                p = os.path.join(adir, fn)
                chunks.append((fn, open(p, encoding="utf-8").read()))
        # C 类: 只有 _prose 版进索引, 表格区已隔离
        if os.path.isdir(CHUNK):
            for fn in os.listdir(CHUNK):
                if fn.endswith("_prose.md"):
                    p = os.path.join(CHUNK, fn)
                    chunks.append((fn, open(p, encoding="utf-8").read()))
    return chunks


def retrieve(chunks, keyword, topk=5):
    """简单关键词检索(模拟 FTS5 + LIKE 兜底), 返回 top-k chunk"""
    scored = []
    for name, text in chunks:
        n = text.count(keyword)
        if n:
            scored.append((n, name, text))
    scored.sort(key=lambda x: -x[0])
    return scored[:topk]


def main():
    print("=" * 78)
    print("门禁有效性验证 —— 机构名/联系方式错配风险")
    print("=" * 78)

    raw = load_corpus("raw")
    filtered = load_corpus("filtered")
    print(f"语料规模: 全库 {len(raw)} 个 md  ->  过滤后 {len(filtered)} 个 chunk")
    print()

    total_raw_risk = total_filt_risk = 0
    detail = []
    for keyword, field in QUERIES:
        q = f"{keyword} {field}"

        hits_raw = retrieve(raw, keyword)
        hits_filt = retrieve(filtered, keyword)

        r_raw = sum(risky_chunks(t) for _, _, t in hits_raw)
        r_filt = sum(risky_chunks(t) for _, _, t in hits_filt)

        total_raw_risk += r_raw
        total_filt_risk += r_filt
        detail.append((q, len(hits_raw), r_raw, len(hits_filt), r_filt,
                       [n for _, n, _ in hits_raw[:3]],
                       [n for _, n, _ in hits_filt[:3]]))

    print(f"{'查询':44} {'全库命中':>8} {'全库风险':>8} {'过滤命中':>8} {'过滤风险':>8}")
    for q, hr, rr, hf, rf, nr, nf in detail:
        print(f"{q[:42]:44} {hr:8} {rr:8} {hf:8} {rf:8}")
    print()
    print(f"错配风险证据总数: 全库 {total_raw_risk}  ->  过滤后 {total_filt_risk}")
    drop = 1 - (total_filt_risk / max(1, total_raw_risk))
    print(f"降幅: {drop:.1%}")

    print()
    print("=" * 78)
    print("结论")
    print("=" * 78)
    if total_filt_risk == 0:
        print("PASS  过滤后无任何「机构名 + 联系方式」错配风险 chunk。")
    elif drop >= 0.8:
        print(f"PASS  过滤后错配风险下降 {drop:.1%}, 剩余 {total_filt_risk} 条需人工确认。")
    else:
        print(f"FAIL  降幅仅 {drop:.1%}, 过滤规则需要加强。")
        print("      建议: 把残留 chunk 的文件降级为 B-EXCLUDE。")
    return 0 if total_filt_risk == 0 or drop >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
