"""把章/节/文件 三层目录改成**每层各自从 01 开始**的编号。

规则:
  章层: 01_ 02_ 03_ ...           (全书连续)
  节层: 01_ 02_ 03_ ...           (每个章下重置)
  文件层: 01_ 02_ 03_ ...         (每个节下重置)

排序依据 = 目录合并.md 的自然阅读顺序(书里的先后), 不是磁盘字母序。

坑1: 章/节 目录自己没 md, 但子树里有 -> 判断空目录要看**子树** md 总数;
    且 os.walk 父先子后, 累加子树计数要沿祖先链加不能覆盖。
坑2: 磁盘深度 2 可能是 节(（一）新产品审定), 也可能是 文件(饲料和饲料添加剂管理条例),
    kind 不能靠深度猜, 要用标题去目录里查。
坑3: 改名要从深往浅做, 否则父目录改名后子目录旧路径就找不到了。
坑4: strip_prefix 要剥**所有**层前缀(脚本重跑会叠成 "01_002_xxx")。
坑5: 编号顺序(TOC顺序) 和 改名顺序(深度倒序) 是两回事, 不能混用。
"""
import os
import re
import sys
import time

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_reorg.py", encoding="utf-8").read().split("def main()")[0])

MINIMAX = r"E:/workspace/siliao/minimax"
SCOPES = ["01", "02", "03", "04"]
# 剥掉所有层前缀: "NN_"/"NNN_"/"xx_"/"x_"/"_"
_ALL_PREFIX_RE = re.compile(r"^(?:(?:\d{2,3}|xx|x)_)+")
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def strip_prefix(name):
    """去掉所有层的前缀, 拿到裸名"""
    return _ALL_PREFIX_RE.sub("", name)


def sort_key(name):
    n = strip_prefix(name)
    m = re.match(r"^[（(]?([一二三四五六七八九十]+)[）)、、]", n)
    if m:
        return (0, CN_NUM.get(m.group(1), 99), n)
    m = re.match(r"^(\d+)", n)
    if m:
        return (1, int(m.group(1)), n)
    return (2, 0, n)


def main():
    apply = "--apply" in sys.argv
    drop_empty = "--drop-empty" in sys.argv

    docs = build_docs(parse_toc(TOC))

    # TOC 顺序: 章 -> 节 -> 文件
    toc_seq = []
    for lv, t, p, dn, c, s in docs:
        if lv == 2:
            toc_seq.append(("章", t, ""))
        elif lv == 3:
            toc_seq.append(("节", t, c))
        elif lv == 4:
            toc_seq.append(("文件", t, c + "\x00" + s))
    toc_pos = {}
    for i, (k, t, ctx) in enumerate(toc_seq):
        toc_pos.setdefault((k, t, ctx), i)
    toc_pos_title = {}
    for i, (k, t, ctx) in enumerate(toc_seq):
        toc_pos_title.setdefault((t, ctx), i)
    toc_pos_any = {}
    for i, (k, t, ctx) in enumerate(toc_seq):
        toc_pos_any.setdefault(t, i)
    # 目录 OCR 会把页码粘进标题(如 "动物饮用598水"), 磁盘上是清洗过的版本,
    # 所以查表时把 TOC 标题也清洗一遍, 两种形式都存。
    all_pages = {p for _lv, _t, p, _dn, _c, _s in docs if p}
    toc_pos_clean = {}
    for i, (k, t, ctx) in enumerate(toc_seq):
        ct = clean_title(t, None, all_pages)
        if ct != t:
            toc_pos_clean.setdefault((ct, ctx), i)
            toc_pos_clean.setdefault((ct, ""), i)
            toc_pos_any.setdefault(ct, i)

    scopes = []
    for d in sorted(os.listdir(MINIMAX)):
        p = os.path.join(MINIMAX, d)
        if os.path.isdir(p) and any(d.startswith(s) for s in SCOPES):
            scopes.append((d, p))

    items = []
    empty_dirs = []
    for scope, spath in scopes:
        own = {}
        for dp, dns, fns in os.walk(spath):
            rel = os.path.relpath(dp, spath)
            if rel == ".":
                continue
            own[dp] = len([f for f in fns if f.endswith(".md")])
        subtree_md = dict(own)
        for dp, n in own.items():
            rel = os.path.relpath(dp, spath)
            for anc in range(rel.count(os.sep) - 1, -1, -1):
                p = os.path.join(spath, *rel.split(os.sep)[:anc + 1])
                subtree_md[p] = subtree_md.get(p, 0) + n
        for dp, dns, fns in os.walk(spath):
            rel = os.path.relpath(dp, spath)
            if rel == ".":
                continue
            depth = rel.count(os.sep) + 1
            base = os.path.basename(dp)
            bare = strip_prefix(base)
            if subtree_md.get(dp, 0) == 0:
                empty_dirs.append((dp, depth, bare))
                continue
            parts = [strip_prefix(x) for x in rel.split(os.sep)]
            chap = parts[0] if len(parts) >= 1 else ""
            sect = parts[1] if len(parts) >= 2 else ""
            cands = []
            if depth == 1:
                cands = [("章", bare, "")]
            elif depth == 2:
                cands = [("节", bare, chap), ("文件", bare, chap),
                         ("文件", bare, ""), ("节", bare, "")]
            else:
                cands = [("文件", bare, chap + "\x00" + sect),
                         ("文件", bare, chap), ("文件", bare, "")]
            key = None
            kind = {1: "章", 2: "节", 3: "文件"}.get(depth, "文件")
            for k2, t2, c2 in cands:
                if (k2, t2, c2) in toc_pos:
                    key = toc_pos[(k2, t2, c2)]
                    kind = k2
                    break
            if key is None:
                for k2, t2, c2 in cands:
                    if (t2, c2) in toc_pos_title:
                        key = toc_pos_title[(t2, c2)]
                        kind = k2
                        break
            if key is None:
                for k2, t2, c2 in cands:
                    if (t2, c2) in toc_pos_clean:
                        key = toc_pos_clean[(t2, c2)]
                        kind = k2
                        break
            if key is None and bare in toc_pos_any:
                key = toc_pos_any[bare]
            if key is None:
                key = 10 ** 6
            # 父级路径(用裸名拼), 用于分组重置编号
            parent_key = os.path.dirname(rel).replace(os.sep, "\x00")
            items.append({
                "key": key, "sk": sort_key(bare), "path": dp, "depth": depth,
                "kind": kind, "bare": bare, "parent": parent_key,
                "scope": scope, "rel": rel,
            })

    # TOC 顺序
    items.sort(key=lambda it: (it["key"], it["sk"]))

    # ---- 建立 父路径 -> 子项 索引, 用来找每个目录的"直接父章/父节" ----
    # rel 是相对 scope 的路径; 用 (scope, rel) 做 key
    by_rel = {(it["scope"], it["rel"]): it for it in items}
    for it in items:
        parent_rel = os.path.dirname(it["rel"])
        pit = by_rel.get((it["scope"], parent_rel))
        it["parent_item"] = pit

    # ---- 分配编号: 每层各自从 01 开始 ----
    # 章: 全书连续
    chap_counter = 0
    for it in items:
        if it["kind"] == "章":
            chap_counter += 1
            it["num"] = chap_counter
    # 往上传: 任意节点继承祖先章的编号
    for it in items:
        p = it.get("parent_item")
        it["chap_num"] = it["num"] if it["kind"] == "章" else (p["chap_num"] if p else 0)

    # 节: 每个章下重置
    # 坑: 分组 key 必须用 (章号, 节号) 组合, 只用节号会串
    #     (不同章里都可能有 01_（一）xxx)
    sec_counter = {}
    for it in items:
        if it["kind"] != "节":
            continue
        g = it["chap_num"]
        sec_counter[g] = sec_counter.get(g, 0) + 1
        it["num"] = sec_counter[g]
    # 往上传: 任意节点继承祖先节的编号
    for it in items:
        if it["kind"] == "节":
            it["sec_group"] = (it["chap_num"], it["num"])
        else:
            p = it.get("parent_item")
            it["sec_group"] = p["sec_group"] if p else (it["chap_num"], 0)

    # 文件: 每个节下重置(直接挂在章下的按章分组)
    file_counter = {}
    for it in items:
        if it["kind"] != "文件":
            continue
        g = it["sec_group"]
        file_counter[g] = file_counter.get(g, 0) + 1
        it["num"] = file_counter[g]

    # 改名前的显示: 编号顺序 = TOC 顺序
    print("=" * 78)
    print(f"编号 {len(items)} 个目录 (每层各自从 01 开始)")
    print("=" * 78)
    for it in items:
        num = f"{it['num']:02d}_"
        print(f"  {num} [{it['kind']}] {it['rel']}")
        print(f"        -> {num}{it['bare']}")
    if empty_dirs:
        print(f"\n空目录(不在目录里, 未编号): {len(empty_dirs)}")
        for dp, depth, bare in empty_dirs:
            print(f"  [{depth}] {os.path.relpath(dp, MINIMAX)}")

    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")
        return

    if drop_empty:
        for dp, depth, bare in empty_dirs:
            try:
                os.rmdir(dp)
                print(f"  删除空目录: {os.path.relpath(dp, MINIMAX)}")
            except OSError as e:
                print(f"  删除失败 {dp}: {e}")

    # 改名: 深 -> 浅
    by_path = sorted(items, key=lambda it: -it["depth"])
    renamed = 0
    failed = []
    for it in by_path:
        dp = it["path"]
        parent = os.path.dirname(dp)
        num = f"{it['num']:02d}_"
        new = os.path.join(parent, num + it["bare"])
        if os.path.basename(dp) == num + it["bare"]:
            continue
        if os.path.exists(new):
            print(f"  跳过(已存在): {new}")
            continue
        ok = False
        for attempt in range(5):
            try:
                os.rename(dp, new)
                ok = True
                break
            except PermissionError:
                time.sleep(0.4 * (attempt + 1))
            except OSError:
                break
        if ok:
            renamed += 1
        else:
            failed.append((dp, new))
            print(f"  失败: {dp}")
    print(f"\n完成: {renamed} 个目录已改名, 失败 {len(failed)}")
    if failed:
        for dp, new in failed:
            print(f"    {dp}\n      -> {new}")
        sys.exit(1)


if __name__ == "__main__":
    main()
