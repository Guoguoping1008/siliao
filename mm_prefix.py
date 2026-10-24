"""把章/节/文件 三层目录的前缀从 "_" 改成 "xx_"。

范围: 只改 minimax/01法规 02制度文件 03 04 下我生成的那三层,
不动顶层 01法规/ 02制度文件/ 03/ 04/ 和 000封面/ 001目录/。

坑: 从深往浅改名, 否则父目录改名后子目录路径就找不到了。
坑: Windows 上目录可能被杀毒/索引临时锁住 -> PermissionError 重试。
"""
import os
import sys
import time

MINIMAX = r"E:/workspace/siliao/minimax"
SCOPES = ["01", "02", "03", "04"]

OLD = "_"
NEW = "xx_"


def find_scope_dirs():
    out = []
    for d in sorted(os.listdir(MINIMAX)):
        p = os.path.join(MINIMAX, d)
        if os.path.isdir(p) and any(d.startswith(s) for s in SCOPES):
            out.append((d, p))
    return out


def collect_targets(scope_path):
    """scope 下所有子目录 -> [(路径, 深度)]  深度1=章 2=节 3=文件"""
    targets = []
    for dp, dns, fns in os.walk(scope_path):
        rel = os.path.relpath(dp, scope_path)
        if rel == ".":
            continue
        targets.append((dp, rel.count(os.sep) + 1))
    return targets


def main():
    apply = "--apply" in sys.argv

    all_targets = []
    for name, path in find_scope_dirs():
        for dp, depth in collect_targets(path):
            all_targets.append((dp, depth, name))

    # 只处理带 OLD 前缀的; 已经是 NEW 的跳过
    todo = []
    already = 0
    for dp, depth, scope in all_targets:
        b = os.path.basename(dp)
        if b.startswith(NEW) and not b.startswith(OLD):
            already += 1
            continue
        if not b.startswith(OLD):
            print(f"  跳过(无 '{OLD}' 前缀): {os.path.relpath(dp, MINIMAX)}")
            continue
        todo.append((dp, depth, scope))

    # 深 -> 浅
    todo.sort(key=lambda x: -x[1])

    print("=" * 78)
    print(f"计划: 改名 {len(todo)} 个目录 ('{OLD}' -> '{NEW}'), 已是 '{NEW}' 的 {already} 个")
    print("=" * 78)
    for dp, depth, scope in todo:
        parent = os.path.basename(os.path.dirname(dp))
        base = os.path.basename(dp)
        tag = {1: "章", 2: "节", 3: "文件"}.get(depth, "?")
        print(f"  [{tag}] {scope}\\{parent}\\{base}")
        print(f"        -> {NEW + base[1:]}")

    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")
        return

    renamed = 0
    failed = []
    for dp, depth, scope in todo:
        parent = os.path.dirname(dp)
        base = os.path.basename(dp)
        new = os.path.join(parent, NEW + base[len(OLD):])
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
