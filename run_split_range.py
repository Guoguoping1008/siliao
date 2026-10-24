"""按页码区间重跑拆分, 输出到指定目录。

为什么不直接用 CLI:
`--folder "02制度文件"` 经过 shell 会编码损坏(实测进程里看到 `02�ƶ��ļ�`),
过滤器静默失效, 导致全库 362 张被误处理。本脚本用 Python 直接读清单,
中文路径与 dst 都不经过 shell, 避免同类事故。

用法:
    python run_split_range.py            # 默认 137-737 -> Images_split_spine, --spine
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import split_pages

SRC_ROOT = r"E:/workspace/siliao/Images"
DST_ROOT = r"E:/workspace/siliao/Images_split_spine"
FOLDER = "02制度文件"
LO, HI = 137, 737


def select():
    imgs = []
    for dp, _, fs in os.walk(SRC_ROOT):
        for f in sorted(fs):
            if not f.lower().endswith((".jpg", ".jpeg")):
                continue
            rel = os.path.relpath(os.path.join(dp, f), SRC_ROOT).replace("\\", "/")
            d, name = os.path.split(rel)
            stem = os.path.splitext(name)[0]
            if d != FOLDER or not stem.isdigit():
                continue
            if LO <= int(stem) <= HI:
                imgs.append(os.path.join(dp, f))
    imgs.sort()
    return imgs


def main():
    # 左右半必须各自覆盖
    split_pages.OVERWRITE = True

    imgs = select()
    if not imgs:
        print("[scan] 0 张源图命中, 检查 LO/HI 与 FOLDER")
        return 1

    planned = set()
    for p in imgs:
        fn = os.path.basename(p)
        n = int(os.path.splitext(fn)[0])
        rel_dir = os.path.relpath(os.path.dirname(p), SRC_ROOT)
        for k in (n - 1, n):
            planned.add(os.path.join(DST_ROOT, rel_dir, "%04d.jpg" % k))

    print("[scan] 源图 %d 张 -> 将覆盖输出 %d 个 -> %s"
          % (len(imgs), len(planned), DST_ROOT), flush=True)

    t0 = time.time()
    ok = err = 0
    log = []
    for i, src in enumerate(imgs, 1):
        rel = os.path.relpath(src, SRC_ROOT)
        dst_dir = os.path.join(DST_ROOT, os.path.dirname(rel))
        try:
            r = split_pages.split_one(src, dst_dir, use_spine=True, slant=True)
        except Exception as e:
            err += 1
            print("  [%d] ERR %s: %s" % (i, rel, e), flush=True)
            continue
        if r is None:
            err += 1
            continue
        st, lp, rp, frac, mode = r[0], r[1], r[2], r[3], r[4]
        if st == "SKIP":
            print("  [%d] SKIP(未覆盖!) %s" % (i, rel), flush=True)
        else:
            ok += 1
        log.append({"src": rel, "status": st, "frac": frac, "mode": mode,
                    "left": os.path.relpath(lp, DST_ROOT).replace("\\", "/"),
                    "right": os.path.relpath(rp, DST_ROOT).replace("\\", "/")})
        if i % 50 == 0 or i == len(imgs):
            el = time.time() - t0
            print("  %d/%d ok=%d err=%d %.2fs/img eta=%.1fmin"
                  % (i, len(imgs), ok, err, el / i, (len(imgs) - i) * el / i / 60),
                  flush=True)

    # mtime 验证: 返回值 ok 可能是静默失败, 必须查实际写入
    ref = t0 - 5
    fresh = sum(1 for p in planned if os.path.exists(p) and os.path.getmtime(p) > ref)
    missing = sorted(p for p in planned if not os.path.exists(p))

    with open(os.path.join(DST_ROOT, "_split_report.json"), "w", encoding="utf-8") as f:
        import json
        json.dump(log, f, ensure_ascii=False, indent=1)

    print("[done] ok=%d err=%d total=%.0fs" % (ok, err, time.time() - t0))
    print("[verify] 计划输出 %d, mtime 为本次 %d, 缺失 %d"
          % (len(planned), fresh, len(missing)))
    if missing[:5]:
        print("[verify] 缺失示例:", missing[:5])
    return 0 if (fresh == len(planned) and err == 0) else 2


if __name__ == "__main__":
    sys.exit(main())