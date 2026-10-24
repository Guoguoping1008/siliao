"""给已生成的 章/节/文件 三层目录加 "_" 前缀。

范围: 只改我建的那三层(章 ##/ 节 ###/ 文件 ####), 不动顶层 01法规/02制度文件/,
也不动 000封面/001目录/。

坑: 目录名里带 "、" 和 "（）" 都不是非法字符, 直接拼 "_" 就行。
    但要**从深往浅**改名, 否则父目录改名后子目录的路径就找不到了。
"""
import os
import sys
import time

MINIMAX = r"E:/workspace/siliao/minimax"

# 顶层目录 -> 里面要改名的层数上限
# 01/02/03/04 都是 章/节/文件 三层
SCOPES = ["01", "02", "03", "04"]


def find_scope_dirs():
    """返回 [(scope名, 绝对路径)]"""
    out = []
    for d in sorted(os.listdir(MINIMAX)):
        p = os.path.join(MINIMAX, d)
        if os.path.isdir(p) and any(d.startswith(s) for s in SCOPES):
            out.append((d, p))
    return out


def collect_targets(scope_path):
    """收集 scope 下所有需要加前缀的目录(章/节/文件), 返回 [(路径, 深度)]"""
    targets = []
    for dp, dns, fns in os.walk(scope_path):
        rel = os.path.relpath(dp, scope_path)
        if rel == ".":
            continue
        # rel 的深度就是层级: 1=章, 2=节, 3=文件
        depth = rel.count(os.sep) + 1
        targets.append((dp, depth))
    return targets


def main():
    apply = "--apply" in sys.argv

    all_targets = []
    for name, path in find_scope_dirs():
        for dp, depth in collect_targets(path):
            all_targets.append((dp, depth, name))

    # 从深往浅排序: 先改文件层(最深), 再改节, 最后改章
    all_targets.sort(key=lambda x: -x[1])

    print("=" * 78)
    print(f"计划: 改名 {len(all_targets)} 个目录")
    print("=" * 78)
    for dp, depth, scope in all_targets:
        parent = os.path.basename(os.path.dirname(dp))
        base = os.path.basename(dp)
        new = "_" + base
        tag = {1: "章", 2: "节", 3: "文件"}.get(depth, "?")
        print(f"  [{tag}] {scope}\\{parent}\\{base}")
        print(f"        -> {new}")

    if not apply:
        print("\n[DRY RUN] 加 --apply 执行")
        return

    # 执行: 深 -> 浅
    renamed = 0
    failed = []
    for dp, depth, scope in all_targets:
        parent = os.path.dirname(dp)
        base = os.path.basename(dp)
        if base.startswith("_"):
            continue
        new = os.path.join(parent, "_" + base)
        if os.path.exists(new):
            print(f"  跳过(已存在): {new}")
            continue
        # Windows 上目录可能被杀毒/索引临时锁住 -> 重试
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
        print("  失败清单:")
        for dp, new in failed:
            print(f"    {dp}\n      -> {new}")
        sys.exit(1)


if __name__ == "__main__":
    main()
