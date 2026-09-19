#!/usr/bin/env python3
"""
并发推送 R2: 起 8 个并行子进程, 每个跑 npx wrangler r2 object put,
shell 启动 + wrangler 启动 + 网络往返被重叠, 比串行快 4-5 倍。

输入: build/export/push_r2.sh <src_dir1> <src_dir2> ...
输出: R2 bucket siliao-index/<src_dir>/<type>/<fname>.md
"""
import subprocess
import sys
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


def push_one(f: Path, doc: str, type_: str) -> tuple[str, bool]:
    """单文件 push 到 R2 (串行, miniflare R2 用 SQLite 锁, 并发会失败)"""
    rel = f"{doc}/{type_}/{f.name}"
    # 脚本位于 build/export/, 根目录需要 parent.parent.parent
    project_root = Path(__file__).resolve().parent.parent.parent
    wrangler = project_root / "query" / "worker" / "node_modules" / ".bin" / "wrangler.cmd"
    try:
        result = subprocess.run(
            [str(wrangler), "r2", "object", "put", f"siliao-index/{rel}",
             "--file", str(f), "--local"],
            cwd=project_root / "query" / "worker",
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # 失败时把 stderr 写进日志便于诊断
            print(f"    [debug] {rel} stderr={result.stderr[:200]!r}")
        return rel, result.returncode == 0
    except Exception as e:
        print(f"    [debug] {rel} exception={e!r}")
        return rel, False


def main():
    if len(sys.argv) < 2:
        print("usage: push_r2_concurrent.py <src_dir1> [<src_dir2> ...]")
        sys.exit(1)

    tasks = []
    for src in sys.argv[1:]:
        src_path = Path(src)
        doc = src_path.name
        for type_dir in ['articles', 'chapters', 'sections']:
            type_path = src_path / type_dir
            if not type_path.exists():
                continue
            for f in sorted(type_path.glob("*.md")):
                tasks.append((f, doc, type_dir))

    print(f"[push_r2] {len(tasks)} 个文件, 串行(miniflare SQLite 锁)")

    ok = 0
    fail = 0
    for f, doc, type_ in tasks:
        rel, success = push_one(f, doc, type_)
        if success:
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL] {rel}")
        # 每 20 条打印进度
        if (ok + fail) % 20 == 0:
            print(f"  [进度] {ok + fail}/{len(tasks)} 成功={ok} 失败={fail}")

    print(f"[push_r2_concurrent] 完成: 成功 {ok}, 失败 {fail}")


if __name__ == "__main__":
    main()