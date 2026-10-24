"""书脊检测的验收: 目视标定真值 + 误差评估。

真值获取方法
------------
`python spine_truth.py` 会在代表页上画出 0.44~0.54 的多条候选竖线并标注数值,
逐页目视判读"哪条线对齐纸面折痕", 结果记录在本文件的 GROUND_TRUTH 中。

目视标定的依据是左右页页眉的页码(左偶右奇), 例如 0035.jpg 左页 34 / 右页 35。
"""

GROUND_TRUTH = {
    "Images/02制度文件/0423.jpg": (0.490, "左页422/右页423, 折痕对齐 0.49"),
    "Images/02制度文件/0035.jpg": (0.485, "左页34/右页35, 折痕略偏左于 0.50"),
    "Images/02制度文件/0015.jpg": (0.487, "左页14(空白)/右页15, 折痕偏左"),
    "Images/02制度文件/0235.jpg": (0.478, "左页234/右页235, 折痕明显偏左"),
    "Images/02制度文件/0551.jpg": (0.492, "质谱参数表, 折痕接近中线"),
    "Images/02制度文件/0339.jpg": (0.489, "续表页, 折痕略偏左"),
    "Images/03相关法规法律法规文件/0749.jpg": (0.500, "左页748/右页749, 折痕正中"),
    "Images/04标准及标准目录/0953.jpg": (0.497, "标准正文, 折痕接近中线"),
}


def evaluate(detect_fn, spine_x_at, root=r"E:/workspace/siliao"):
    """返回 (mae, max_err, rows)。rows 为 [(file, truth, got, err)]。"""
    import os
    from PIL import Image
    rows = []
    for f, (truth, _why) in GROUND_TRUTH.items():
        p = os.path.join(root, f.replace("/", os.sep))
        if not os.path.exists(p):
            continue
        d = detect_fn(Image.open(p))
        got = spine_x_at(d, 0.5)
        rows.append((f, truth, got, got - truth))
    if not rows:
        return None, None, []
    errs = sorted((abs(r[3]), r) for r in rows)
    mae = sum(r[3] for r in rows) / len(rows)
    return mae, errs[-1][0], rows


if __name__ == "__main__":
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from PIL import Image
    import spine_detect as S

    print("%-30s %-7s %-8s %-8s %-8s %s" %
          ("file", "truth", "x_top", "x_bot", "got", "err"))
    rows = []
    for f, (truth, _w) in GROUND_TRUTH.items():
        p = os.path.join(r"E:/workspace/siliao", f.replace("/", os.sep))
        d = S.detect_spine(Image.open(p))
        got = S.spine_x_at(d, 0.5)
        rows.append((f, truth, got, got - truth))
        print("%-30s %.3f   %.4f   %.4f   %.4f   %+.4f" % (
            f.replace("\\", "/")[-28:], truth, d["x_top"], d["x_bot"], got, got - truth))
    mae = sum(r[3] for r in rows) / len(rows)
    mx = max(rows, key=lambda r: abs(r[3]))
    print("\nMAE = %.4f   最大 = %.4f (%s)" % (mae, abs(mx[3]), mx[0].split("/")[-1]))
    print("中心分割的 MAE = %.4f (恒为 0.5000)" %
          (sum(abs(0.5 - r[1]) for r in rows) / len(rows)))