#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去掉表格页尾部残留的「模型自述」。

现象: VLM 输出表格后, 常常追加一段说明:
  「这段代码将图片中的表格内容转换成了HTML格式的表格。...」
  「这段HTML代码严格按照要求将图片中的表格转换为HTML格式: 1. ...」
这类内容**不是页面正文**, 进索引是噪声。

坑: **不能一刀切删「图片中的」** —— 语料里有合法内容含这个词:
  0345 「扫描图片中的表格内容」是表格里的**真实标签**
  0851 「兽药追溯二维码无法识别」是**法规原文**
所以判据要更严: 只删「**表格闭合之后**」的说明性段落, 且带特征词
(「这段代码」「转换为HTML」「按照要求」「以下是」...), 不碰表格内部。
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
MINIMAX = os.path.join(REPO, "minimax")

# 表格结束之后才出现的自述特征
TAIL_META = re.compile(
    r"(?:这段(?:代码|HTML代码)?|以上(?:代码|内容)?|以上是|以下是|下面(?:是|为))"
    r"[^<>]{0,120}?"
    r"(?:转换|转化|表示|呈现|输出|包含|保持)"
    r"[^<>]{0,200}?"
    r"(?:HTML|html|表格|代码|格式)",
    re.S)
TAIL_META2 = re.compile(
    r"(?:严格按照要求|按照要求|希望(?:这|以上)|如有(?:疑问|需要)|"
    r"请(?:根据|以)|注[：:]\s*以上|以上表格)",
    re.S)


def strip_tail_meta(txt):
    """删掉最后一个 </table> 之后的自述段落"""
    m = None
    for mm in re.finditer(r"</table>", txt, re.I):
        m = mm
    if not m:
        return txt, 0
    head = txt[:m.end()]
    tail = txt[m.end():]
    if not tail.strip():
        return txt, 0
    # tail 里必须命中特征, 且不含真正的正文信号(中文标点成句、较长段落)
    hit = bool(TAIL_META.search(tail) or TAIL_META2.search(tail))
    if not hit:
        return txt, 0
    # tail 太长(>1200 字)说明是正文, 不能删
    if len(tail) > 1200:
        return txt, 0
    return head.rstrip() + "\n", len(tail)


def main():
    changed = []
    for dp, _, fs in os.walk(MINIMAX):
        for f in sorted(fs):
            if not f.endswith(".md") or f.endswith(".bak"):
                continue
            p = os.path.join(dp, f)
            raw = open(p, encoding="utf-8").read()
            new, n = strip_tail_meta(raw)
            if n:
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(new)
                changed.append((os.path.relpath(p, REPO), n))
    print(f"清理 {len(changed)} 个文件:")
    for p, n in changed:
        print(f"  {p}  (删 {n} 字符)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
