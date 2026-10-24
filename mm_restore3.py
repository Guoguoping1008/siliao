"""重建 章/节/文件 三层结构, 并把第三层(文件)改成"从 01 开始、不重置"。

规则:
  第一层(章): 不改编号  -> 01_ 02_ 03_ .. (全书连续)
  第二层(节): 不改编号  -> 01_ 02_ 03_ .. (每个章下重置)
  第三层(文件): 改编号 -> 01_ 02_ 03_ .. **不重置**(按 scope 各自连续)

  02制度文件/ 里的文件: 01_ .. 139_
  03相关法律法规文件/ 里的文件: 01_ .. 29_

依据 = 目录合并.md 的章节结构(权威), 用标题匹配磁盘上的目录。

坑1: 磁盘上现在可能已经被别的流程改过(章层没了, 变成两层), 所以不能靠
     "当前深度" 判断一个目录是章还是节还是文件, 得靠**标题**去目录里查。
坑2: 目录 OCR 会把页码粘进标题("动物饮用598水"), 磁盘上是清洗过的版本,
     查表时要把目录标题也清洗一遍。
坑3: 目录结构是 目录合并.md 的**层级**, 但磁盘上文件名要跟目录里的**裸标题**匹配,
     而不是跟目录里的标题(含页码)匹配。
坑4: 改名要从深往浅做。
坑5: 编号顺序(目录顺序) 和 改名顺序(深度倒序) 是两回事。
"""
import os
import re
import shutil
import sys
import time

sys.path.insert(0, r"E:/workspace/siliao")
exec(open(r"E:/workspace/siliao/mm_reorg.py", encoding="utf-8").read().split("def main()")[0])

MINIMAX = r"E:/workspace/siliao/minimax"
SCOPES = ["01", "02", "03", "04"]
_ALL_PREFIX_RE = re.compile(r"^(?:(?:\d{2,3}|xx|x)_)+")


def strip_prefix(name):
    return _ALL_PREFIX_RE.sub("", name)


def main():
    apply = "--apply" in sys.argv

    docs = build_docs(parse_toc(TOC))
    all_pages = {p for _lv, _t, p, _dn, _c, _s in docs if p}

    # ---- 目录结构: 裸标题 -> (kind, 父链) ----
    # 章: kind="章", 父=None
    # 节: kind="节", 父=章裸标题
    # 文件: kind="文件", 父=(章, 节)
    # 坑: 有的 ### 条目本身就是整部文件(下面没有 #### 子条目)
    has_child = set()
    for i, (lv, t, p, dn, c, s) in enumerate(docs):
        if lv == 4:
            has_child.add(section_of(docs, i))

    chap_of = {}      # 节裸标题 -> 章裸标题
    file_of = {}      # 文件裸标题 -> (章, 节)
    chap_list = []
    cur_chap = ""
    cur_sec = ""
    for i, (lv, t, p, dn, c, s) in enumerate(docs):
        bare = strip_prefix(clean_title(t, None, all_pages))
        if lv == 2:
            cur_chap = bare
            cur_sec = ""      # 坑: 换章必须清空 cur_sec
            chap_list.append(bare)
        elif lv == 3:
            cur_sec = bare
            if bare not in has_child:
                # 本身就是整部文件
                chap_of[bare] = cur_chap
                file_of[bare] = (cur_chap, "")
                cur_sec = ""
            else:
                chap_of[bare] = cur_chap
        elif lv == 4:
            file_of[bare] = (cur_chap, cur_sec)

    # ---- 章/节的最终名(带编号前缀) 从 git HEAD 读, 保持"前面层级不修改" ----
    # 用户要求: 第一层(章)/第二层(节) 的编号不动, 只改第三层(文件)。
    # 所以这里不自己重新编号, 而是沿用 HEAD 里已有的名字(带前缀)。
    import subprocess
    out = subprocess.run(
        ["git", "-C", "E:/workspace/siliao", "-c", "core.quotepath=false",
         "ls-tree", "-r", "--name-only", "-z", "HEAD", "minimax"],
        capture_output=True).stdout.decode("utf-8", "ignore")
    head_dirs = set()
    for p in out.split("\0"):
        if not p:
            continue
        parts = p.split("/")
        for i in range(2, len(parts)):
            head_dirs.add("/".join(parts[:i + 1]))
    # 裸标题 -> 带前缀的名字 (scope, 章裸名/节裸名) -> HEAD 里的名字
    head_name = {}
    for d in head_dirs:
        rel = d[len("minimax/"):]
        scope, rest = rel.split("/", 1)
        base = os.path.basename(rest)
        bare = strip_prefix(base)
        if bare in file_of or bare in chap_of or bare in chap_list:
            head_name[(scope, bare)] = base

    # 磁盘上每个 scope 下的现有目录 -> 裸标题
    scope_dirs = {}      # scope -> [(path, rel, bare, depth)]
    for d in sorted(os.listdir(MINIMAX)):
        p = os.path.join(MINIMAX, d)
        if not os.path.isdir(p) or not any(d.startswith(s) for s in SCOPES):
            continue
        lst = []
        for dp, dns, fns in os.walk(p):
            rel = os.path.relpath(dp, p)
            if rel == ".":
                continue
            lst.append((dp, rel, strip_prefix(os.path.basename(dp)),
                        rel.count(os.sep) + 1))
        scope_dirs[d] = lst

    # ---- 给每个目录定"身份"(章/节/文件) + 目标路径 ----
    # 目标结构:
    #   <scope>/<章名>/<节名>/<文件裸名>
    # 章/节 用 HEAD 里已有的名字(带编号前缀), 文件用裸名(编号后面加)
    plans = []   # (src_path, dst_path, kind, scope, bare)
    for scope, lst in scope_dirs.items():
        for dp, rel, bare, depth in lst:
            if bare in file_of:
                kind = "文件"
                ch, se = file_of[bare]
                parts = []
                if ch:
                    parts.append(head_name.get((scope, ch), ch))
                if se:
                    parts.append(head_name.get((scope, se), se))
                parts.append(bare)
                dst = os.path.join(MINIMAX, scope, *parts)
            elif bare in chap_of:
                kind = "节"
                ch = chap_of[bare]
                parts = [head_name.get((scope, ch), ch)]
                parts.append(head_name.get((scope, bare), bare))
                dst = os.path.join(MINIMAX, scope, *parts)
            elif bare in chap_list:
                kind = "章"
                dst = os.path.join(MINIMAX, scope, head_name.get((scope, bare), bare))
            else:
                # 不在目录里 -> 保持原样, 不动
                continue
            plans.append((dp, dst, kind, scope, bare))

    # ---- 目标路径去重检查 ----
    seen = {}
    dup = []
    for dp, dst, kind, scope, bare in plans:
        if dst in seen:
            dup.append((dst, seen[dst], dp))
        else:
            seen[dst] = dp

    # ---- 第三层(文件)编号: 每个 scope 内连续, 不重置 ----
    # 顺序 = 目录合并.md 的阅读顺序
    toc_rank = {}
    for i, (lv, t, p, dn, c, s) in enumerate(docs):
        bare = strip_prefix(clean_title(t, None, all_pages))
        toc_rank.setdefault(bare, i)

    file_plans = [pl for pl in plans if pl[2] == "文件"]
    file_plans.sort(key=lambda pl: (toc_rank.get(pl[4], 10 ** 6), pl[4]))
    file_num = {}
    per_scope = {}
    for dp, dst, kind, scope, bare in file_plans:
        per_scope[scope] = per_scope.get(scope, 0) + 1
        file_num[dp] = per_scope[scope]

    print("=" * 78)
    print("计划")
    print("=" * 78)
    for dp, dst, kind, scope, bare in plans:
        num = f"{file_num[dp]:02d}_" if kind == "文件" else ""
        target = os.path.join(os.path.dirname(dst), num + os.path.basename(dst))
        cur = os.path.relpath(dp, MINIMAX)
        if os.path.normpath(target) != os.path.normpath(dp):
            print(f"  [{kind}] {cur}")
            print(f"        -> {os.path.relpath(target, MINIMAX)}")
    if dup:
        print(f"\n目标路径冲突 {len(dup)} 个:")
        for a, b, c in dup[:10]:
            print(f"    {os.path.relpath(a, MINIMAX)}\n      <- {os.path.relpath(b, MINIMAX)}\n      <- {os.path.relpath(c, MINIMAX)}")

    print("\n第三层编号分配(按 scope 连续, 不重置):")
    for s, n in sorted(per_scope.items()):
        print(f"    {s}: 01_ .. {n:02d}_  ({n} 个)")

    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")
        return

    # ---- 执行: 先把文件搬到目标位置(不删原目录, 用 rename) ----
    # 深 -> 浅: 文件先动, 节再动, 章最后
    order = sorted(range(len(plans)),
                   key=lambda i: -plans[i][0].count(os.sep))
    moved = 0
    failed = []
    for i in order:
        dp, dst, kind, scope, bare = plans[i]
        num = f"{file_num[dp]:02d}_" if kind == "文件" else ""
        target = os.path.join(os.path.dirname(dst), num + os.path.basename(dst))
        if os.path.normpath(target) == os.path.normpath(dp):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            # 目标已存在 -> 合并(把 src 里的文件搬过去)
            for f in os.listdir(dp):
                s = os.path.join(dp, f)
                t = os.path.join(target, f)
                if os.path.isfile(s):
                    if os.path.exists(t):
                        os.remove(s)
                    else:
                        shutil.move(s, t)
            try:
                os.rmdir(dp)
            except OSError:
                pass
            moved += 1
            continue
        ok = False
        for attempt in range(5):
            try:
                os.rename(dp, target)
                ok = True
                break
            except PermissionError:
                time.sleep(0.4 * (attempt + 1))
            except OSError:
                break
        if ok:
            moved += 1
        else:
            failed.append((dp, target))
            print(f"  失败: {dp} -> {target}")
    print(f"\n完成: {moved} 个目录已调整, 失败 {len(failed)}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
