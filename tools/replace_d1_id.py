#!/usr/bin/env python3
"""
replace_d1_id.py — 非交互式把 wrangler d1 create 的输出写回 wrangler.toml

[2026-10-06 玄穹 CEO 部署工具]
部署 runbook §3 跑 `wrangler d1 create siliao-db` 后,把整段输出 pipe 给本脚本,
自动解析 database_id 写到 query/worker/wrangler.toml,可选自动 commit。

  # 1. 跑 wrangler 拿输出
  cd query/worker
  npx wrangler d1 create siliao-db > /tmp/d1.out 2>&1
  cd ../..

  # 2. 替换 + commit
  python tools/replace_d1_id.py --from-file /tmp/d1.out \
      --target query/worker/wrangler.toml --commit --branch deploy/c-b-hybrid

  # 或直接 pipe:
  cd query/worker && npx wrangler d1 create siliao-db 2>&1 | \
    python tools/replace_d1_id.py --target query/worker/wrangler.toml --commit
"""
import argparse
import re
import sys
import subprocess
from pathlib import Path

DID_PATTERN = re.compile(
    r'database_id\s*=\s*["\']?'
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"[\"']?",
    re.IGNORECASE,
)
PLACEHOLDER = "REPLACE_AFTER_WRANGLER_D1_CREATE"


def extract_d1_id(text: str) -> str:
    m = DID_PATTERN.search(text)
    if not m:
        raise SystemExit(
            "❌ 找不到 database_id。请确认输入是 std::wrangler d1 create 的完整输出。\n"
            "   期望形如:  database_id = \"xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx\""
        )
    return m.group(1)


def replace_in_file(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)} (cwd={cwd})")
    r = subprocess.run(cmd, cwd=cwd, check=False)
    if r.returncode != 0:
        raise SystemExit(f"❌ 命令失败 exit={r.returncode}")


def main() -> None:
    p = argparse.ArgumentParser(description="Siliao Cloudflare 部署工具")
    p.add_argument(
        "--from-file", type=Path, help="含 wrangler d1 create 输出的文件路径"
    )
    p.add_argument(
        "--target",
        type=Path,
        default=Path("query/worker/wrangler.toml"),
        help="要改的 wrangler.toml 路径(默认 query/worker/wrangler.toml)",
    )
    p.add_argument("--commit", action="store_true", help="替换后自动 git add + commit")
    p.add_argument("--branch", help="commit 时指定分支(不指定就当前分支)")
    args = p.parse_args()

    # 1. 取输入文本
    if args.from_file:
        text = args.from_file.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SystemExit("❌ 必须 --from-file 或 stdin 输入 wrangler d1 create 输出")

    # 2. 解析 ID
    d1_id = extract_d1_id(text)
    print(f"✅ 解析到 database_id = {d1_id}")

    # 3. 替换
    target = args.target
    if not target.exists():
        raise SystemExit(f"❌ 找不到 {target}")

    if not replace_in_file(target, PLACEHOLDER, d1_id):
        if d1_id in target.read_text(encoding="utf-8"):
            print(f"ℹ️  {target} 里 database_id 已是 {d1_id},无需替换")
        else:
            raise SystemExit(
                f"❌ {target} 里找不到占位符 {PLACEHOLDER},且当前 ID 也已不是它。\n"
                "   请手动确认 wrangler.toml 状态(可能已经替换过了)"
            )
    else:
        print(f"✅ {target} 占位符 → {d1_id}")

    # 4. 可选 commit
    if args.commit:
        repo = Path(__file__).resolve().parent.parent  # 仓库根
        run(["git", "add", str(target)], cwd=repo)
        msg = f"chore(worker): wrangler.toml 写入真 D1 database_id {d1_id[:8]}..."
        run(["git", "commit", "-m", msg], cwd=repo)
        print(f"✅ 已 commit: {msg}")
        if args.branch:
            print(f"   提示: 当前在分支 {args.branch},记得 git push origin {args.branch}")


if __name__ == "__main__":
    main()