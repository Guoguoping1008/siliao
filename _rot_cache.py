"""批量探测各页的旋转方向, 结果存 _rot_cache.json(供 VLM 批量用)。"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_table_vlm_par.py", encoding="utf-8").read().split("def main()")[0])

OUT = r"E:/workspace/siliao/_rot_cache.json"


def one(stem):
    src = find_src(stem)
    if not src:
        return stem, None
    try:
        return stem, detect_rot(src)
    except Exception as e:
        return stem, [0, 90, 270]


def main():
    stems = [l.strip() for l in open(r"E:/workspace/siliao/_vlm_pick.txt",
                                     encoding="utf-8") if l.strip()]
    cache = {}
    if os.path.exists(OUT):
        cache = json.load(open(OUT, encoding="utf-8"))
    todo = [s for s in stems if s not in cache]
    print(f"待探测 {len(todo)} 页 (缓存已有 {len(cache)})")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(one, s) for s in todo]
        for fu in as_completed(futs):
            stem, rots = fu.result()
            cache[stem] = rots
            print(f"  {stem}: {rots}")
    json.dump(cache, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已写入 {OUT}")


if __name__ == "__main__":
    main()
