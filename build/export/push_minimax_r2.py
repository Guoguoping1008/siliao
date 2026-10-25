#!/usr/bin/env python3
"""
push_minimax_r2.py —— 把 data/index/minimax 的条文/章节 markdown 推到 R2
==========================================================

R2 key 约定 (与 Worker 一致):
    <doc_id>/articles/<r2_object_key>
    <doc_id>/chapters/<r2_object_key>

r2_object_key 来自 D1 的 articles.r2_object_key / chapters.r2_object_key,
即 ingest_minimax.py 写盘时用的 safe_name() 文件名。

用法:
    python build/export/push_minimax_r2.py                    # local (miniflare)
    python build/export/push_minimax_r2.py --remote           # 真 Cloudflare (走 S3 API)
    python build/export/push_minimax_r2.py --limit 50         # 只推前 50 个 (冒烟测试)

性能:
    - local: 每个 object 一次 `wrangler r2 object put`, 并发 8。
      miniflare R2 底层是 SQLite, 并发太高会 BUSY —— 实测 4-8 安全。
    - remote: 走 Cloudflare S3 API (boto3/r2put), 单次可批量, 快 10x+。
      需要环境变量 R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ACCOUNT_ID。
      没配就自动回落到 wrangler 逐个传。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "query" / "worker"
IDX = REPO / "data" / "index" / "minimax"
BUCKET = "siliao-index"


def build_task_list(index_dir: Path, limit: int | None = None) -> list[tuple[str, Path]]:
    """
    读 articles.json / chapters.json, 产出 [(r2_key, 本地文件路径), ...]。
    r2_key = <doc_id>/articles|r2_object_key
    """
    tasks: list[tuple[str, Path]] = []

    arts = json.loads((index_dir / "articles.json").read_text(encoding="utf-8"))
    for a in arts:
        r2_key = a.get("r2_object_key") or f"{a['article_id']}.md"
        fname = r2_key if r2_key.endswith(".md") else r2_key + ".md"
        # ingest 写盘用的 safe_name: <stem>__<hash8>.md
        h = __import__("hashlib").sha1(a["article_id"].encode("utf-8")).hexdigest()[:8]
        import re as _re
        stem = _re.sub(r'[\\/:*?"<>|]+', "_", a["article_id"])[:120].strip("_")
        local = index_dir / "articles" / f"{stem}__{h}.md"
        if not local.exists():
            continue
        tasks.append((f"{a['doc_id']}/articles/{fname}", local))

    chaps = json.loads((index_dir / "chapters.json").read_text(encoding="utf-8"))
    for c in chaps:
        if c.get("kind") == "section":
            continue  # 节级章节没有独立正文
        r2_key = c.get("r2_object_key") or f"{c['chapter_id']}.md"
        fname = r2_key if r2_key.endswith(".md") else r2_key + ".md"
        h = __import__("hashlib").sha1(c["chapter_id"].encode("utf-8")).hexdigest()[:8]
        import re as _re
        stem = _re.sub(r'[\\/:*?"<>|]+', "_", c["chapter_id"])[:120].strip("_")
        local = index_dir / "chapters" / f"{stem}__{h}.md"
        if not local.exists():
            continue
        tasks.append((f"{c['doc_id']}/chapters/{fname}", local))

    if limit:
        tasks = tasks[:limit]
    return tasks


def push_local(key: str, path: Path, retries: int = 3) -> tuple[str, bool]:
    """
    miniflare 本地 R2: 每个 object 一次 wrangler 调用。

    ⚠️ miniflare 的 R2 底层是 SQLite, **并发写会 BUSY**。
       实测 8 并发时 ~80% 失败, 串行 100% 成功。
       对策: 默认低并发(2) + 失败重试 + 退避。
    """
    wrangler = WORKER / "node_modules" / ".bin" / "wrangler.cmd"
    last_err = ""
    for attempt in range(retries):
        try:
            r = subprocess.run(
                [str(wrangler), "r2", "object", "put", f"{BUCKET}/{key}",
                 "--file", str(path), "--local"],
                cwd=WORKER, capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                return key, True
            last_err = (r.stderr or r.stdout)[-300:]
        except Exception as e:
            last_err = repr(e)
        # 退避: miniflare 锁是短期的, 等一下再试
        time.sleep(0.5 * (attempt + 1))
    print(f"  [ERR] {key}: {last_err}")
    return key, False


def push_remote_s3(tasks: list[tuple[str, Path]]) -> tuple[int, int]:
    """真 Cloudflare: 走 S3 兼容 API, boto3 批量上传。"""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("  [SKIP] boto3 未安装, 回落 wrangler")
        return 0, 0

    key_id = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    account = os.environ.get("R2_ACCOUNT_ID")
    if not (key_id and secret and account):
        print("  [SKIP] R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ACCOUNT_ID 未配")
        return 0, 0

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"},
                      max_pool_connections=32),
    )
    ok = fail = 0
    for i, (key, path) in enumerate(tasks, 1):
        try:
            s3.upload_file(str(path), BUCKET, key, ExtraArgs={"ContentType": "text/markdown; charset=utf-8"})
            ok += 1
        except Exception as e:
            fail += 1
            print(f"  [FAIL] {key}: {e}")
        if i % 100 == 0:
            print(f"  [进度] {i}/{len(tasks)} 成功={ok} 失败={fail}")
    return ok, fail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(IDX))
    ap.add_argument("--remote", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=2,
                    help="本地 miniflare R2 底层是 SQLite, 并发>2 会 BUSY")
    args = ap.parse_args()

    index_dir = Path(args.index)
    if not index_dir.exists():
        print(f"[ERR] index dir not found: {index_dir}")
        return 1

    tasks = build_task_list(index_dir, args.limit)
    print(f"[push_r2] {len(tasks)} objects → bucket {BUCKET}"
          f"{' (remote)' if args.remote else ' (local)'}")

    if args.remote:
        ok, fail = push_remote_s3(tasks)
        if ok == 0 and fail == 0:
            print("[push_r2] S3 不可用, 回落 wrangler 逐个传")
            args.remote = False
        else:
            print(f"[push_r2] 完成: 成功 {ok}, 失败 {fail}")
            return 0 if fail == 0 else 1

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (key, success) in enumerate(ex.map(lambda t: push_local(*t), tasks), 1):
            if success:
                ok += 1
            else:
                fail += 1
                print(f"  [FAIL] {key}")
            if i % 200 == 0:
                print(f"  [进度] {i}/{len(tasks)} 成功={ok} 失败={fail}")

    print(f"[push_r2] 完成: 成功 {ok}, 失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
