#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEP 文件识别 —— 判断「书生SEP / SUREXML 版式文档」还是别的 .sep

为什么需要先识别
--------------
`.sep` 扩展名被 **10+ 个毫不相干的应用**复用:
  · 书生电子 SEP / SUREXML —— 版式文档(带 DRM, 目标场景)
  · IGE+XAO SEE Electrical —— 电气工程原理图(JetDB 数据库)
  · SynthEdit —— 音频插件
  · 印刷分色位图 —— 单通道 TIFF(印版用)
  · 司法档案 —— ZIP 压缩的诉讼卷宗
  ...

网上「SEP 转 PDF」的在线工具基本只认 **TIFF 分色图** 和 **CAD 原理图**,
对书生 SEP **完全无效** —— 书生 SEP 是加密/DRM 的私有容器, 没有渲染引擎。

所以第一步永远是: **确认这个 .sep 到底是什么**。

用法
----
    python build/tools/sep_inspect.py <文件.sep>
    python build/tools/sep_inspect.py --dir <目录>          # 批量扫描
"""

import io
import os
import struct
import sys
import zipfile

# ── 魔数特征表 ──
# 每项: (签名 bytes, 偏移, 描述)
SIGNATURES = [
    (b"PK\x03\x04", 0, "ZIP 容器(OFD/OOXML/或被塞进 ZIP 的其他格式)"),
    (b"%PDF", 0, "PDF 文件(扩展名被改成了 .sep)"),
    (b"\x89PNG", 0, "PNG 图像"),
    (b"GIF8", 0, "GIF 图像"),
    (b"BM", 0, "BMP 图像"),
    (b"II*\x00", 0, "TIFF(小端) —— ⚠️ 很可能是**印刷分色图**, 可直接转 PDF"),
    (b"MM\x00*", 0, "TIFF(大端) —— ⚠️ 很可能是**印刷分色图**, 可直接转 PDF"),
    (b"{\\rtf", 0, "RTF 富文本"),
    (b"\xd0\xcf\x11\xe0", 0, "OLE2 复合文档(旧版 .doc/.xls)"),
    (b"\x00\x00\x01\x00", 0, "TrueType 字体"),
    (b"\x4c\x00\x00\x00\x01\x14\x02\x00", 0, "MS Installer / CAB"),
    (b"MSCF", 0, "Microsoft Cabinet 压缩包"),
    (b"SGZB", 0, "书生 SEP 压缩数据块(SGZip)"),
    (b"SU", 0, "书生 SEP/SUREXML 可能的签名"),
]

# SUREXML / 书生 SEP 的已知标识串
STRINGS = [
    b"SUREXML",
    b"ShuSheng",
    b"ShuShengSEP",
    b"SUReader",
    b"SEPFile",
    b"DocBase",
    b"UOML",
]


def sniff_head(path, n=4096):
    """读文件头 n 字节。"""
    with open(path, "rb") as f:
        return f.read(n)


def detect(path):
    """返回 (类型, 置信度, 说明, 是否可脱离书生软件转 PDF)。"""
    try:
        head = sniff_head(path)
    except OSError as e:
        return ("读取失败", 0, str(e), False)

    if not head:
        return ("空文件", 0, "文件为空", False)

    size = os.path.getsize(path)

    # 1) 魔数
    for sig, off, desc in SIGNATURES:
        if head[off:off + len(sig)] == sig:
            # 印刷分色 TIFF 是最常见的"能直接转"的情况
            if "TIFF" in desc:
                return ("印刷分色位图", 0.9, desc, True)
            if "PDF" in desc:
                return ("PDF(改名)", 0.99, desc, True)
            if "ZIP" in desc:
                # 看看 zip 里是什么
                try:
                    with zipfile.ZipFile(path) as z:
                        names = z.namelist()[:5]
                        inner = ", ".join(names)
                except Exception:
                    inner = "(无法读取)"
                if any(n.lower().endswith(".ofd") for n in names):
                    return ("OFD 版式文档", 0.95, f"ZIP 内含: {inner}", True)
                return ("ZIP 容器", 0.8, f"ZIP 内含: {inner}", True)
            return ("已知格式", 0.85, desc, True)

    # 2) 标识串
    for s in STRINGS:
        if s in head:
            return ("书生 SEP/SUREXML", 0.95, f"命中标识串 {s.decode()}", False)

    # 3) 是否像 ZIP 变体 / 加密数据
    if head[:2] in (b"PK",):
        return ("ZIP 容器", 0.7, "PK 头", True)

    # 4) 熵值 —— 加密/压缩数据会很高
    if size >= 256:
        import collections
        freq = collections.Counter(head[:4096])
        import math
        ent = -sum((c / 4096) * math.log2(c / 4096) for c in freq.values())
        if ent > 7.5:
            return ("高熵数据(可能加密/压缩)", 0.6,
                    f"熵值 {ent:.2f} —— 书生 SEP 常用加密保护", False)

    # 5) 文本?
    try:
        head.decode("utf-8")
        return ("文本文件", 0.5, "看起来是 UTF-8 文本", True)
    except UnicodeDecodeError:
        pass

    return ("未知私有格式", 0.3,
            f"前 16 字节: {head[:16].hex(' ')}", False)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    args = sys.argv[1:]
    if args[0] == "--dir":
        root = args[1]
        files = []
        for dp, _, fs in os.walk(root):
            for f in fs:
                if f.lower().endswith(".sep"):
                    files.append(os.path.join(dp, f))
        print(f"扫描 {root} → {len(files)} 个 .sep 文件\n")
        for p in files:
            kind, conf, desc, conv = detect(p)
            print(f"  {os.path.basename(p)}")
            print(f"    类型: {kind} (置信度 {conf:.0%})")
            print(f"    说明: {desc}")
            print(f"    可直接转 PDF: {'✅ 可以' if conv else '❌ 需要书生软件'}")
            print()
    else:
        for p in args:
            if not os.path.exists(p):
                print(f"[FAIL] 不存在: {p}")
                sys.exit(1)
            kind, conf, desc, conv = detect(p)
            print(f"文件    : {p}")
            print(f"大小    : {os.path.getsize(p):,} 字节")
            print(f"类型    : {kind} (置信度 {conf:.0%})")
            print(f"说明    : {desc}")
            print(f"可直接转 PDF: {'✅ 可以' if conv else '❌ 需要书生 SEP 阅读器/转换工具'}")
            print()
            with open(p, "rb") as f:
                head = f.read(64)
            print("文件头 hex:")
            print("  " + head[:32].hex(" "))
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in head[:32])
            print("文件头 ascii:")
            print("  " + printable)


if __name__ == "__main__":
    main()
