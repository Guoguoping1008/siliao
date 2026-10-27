#!/usr/bin/env python3
"""
把目录树灌进 D1 的 catalog 表。

用法:
  # 生成 catalog.json(从 minimax/001目录/目录合并.md 解析)
  python build/export/build_catalog.py

  # 灌远端 D1
  python build/export/push_catalog.py --remote

  # 灌本地 miniflare D1
  python build/export/push_catalog.py --local

⚠️ 别用 `wrangler d1 execute --file`:
   schema 变过之后 wrangler 4.127+ 会走 D1_RESET_DO 迁移流程,
   实测**把远端表清空**了, 得重建 schema + 重灌全量。
   这里走 D1 REST raw API + bound params, 不碰迁移流程。
"""

import argparse
import json
import os
import sqlite3
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_JSON = ROOT / "data" / "index" / "minimax" / "catalog.json"

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "1b938cc261b000a03554b506985daabb")
DB_ID = os.environ.get("CLOUDFLARE_D1_ID", "e406e21e-e770-4c97-822a-57178c347aa6")

# D1 raw API 的参数上限是 100 个变量, 这里只有 3 个 —— 绰绰有余。
# 但 SQL 字面量不能跨行, 也不认 \n 转义 → 必须用 bound params。
INSERT_SQL = (
    "INSERT INTO catalog (id, tree, stats) VALUES (?1, ?2, ?3) "
    "ON CONFLICT(id) DO UPDATE SET tree=excluded.tree, stats=excluded.stats, "
    "updated_at=datetime('now')"
)


def get_cf_token() -> str:
    """从 wrangler 配置文件读 OAuth token。"""
    # ⚠️ APPDATA 本身已经是 ...\AppData\Roaming, 别再拼一层 "Roaming"
    appdata = os.environ.get("APPDATA") or ""
    cfg = Path(appdata) / "xdg.config" / ".wrangler" / "config" / "default.toml"
    if not cfg.exists():
        raise SystemExit(f"找不到 wrangler 配置: {cfg}  (先跑 npx wrangler login)")
    text = cfg.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("oauth_token"):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("wrangler 配置里没有 oauth_token")


def _cf_post(token: str, endpoint: str, payload: dict, proxy: str | None):
    """调 Cloudflare D1 API。

    ⚠️ `/raw` 与 `/query` 两个端点行为不同:
       - `/raw`  → 执行单条语句, 支持 bound params(灌数据用这个)
       - `/query` → 执行 DDL / 任意语句, **但不支持 params**
       建表(CREATE TABLE)必须走 `/query` —— 走 `/raw` 报 "incomplete input"。
    """
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
        f"/d1/database/{DB_ID}/{endpoint}"
    )
    body = json.dumps(payload).encode("utf-8")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
            )
        )
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with opener.open(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"success": False, "errors": [{"message": e.read()[:400].decode("utf-8", "replace")}]}


def push_remote(tree: str, stats: str):
    token = get_cf_token()
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    # 1) 建表 —— 必须走 /query 端点(不支持 params)
    ddl = (
        "CREATE TABLE IF NOT EXISTS catalog ("
        "id INTEGER PRIMARY KEY, tree TEXT NOT NULL, stats TEXT, "
        "updated_at TEXT DEFAULT (datetime('now')))"
    )
    body = _cf_post(token, "query", {"sql": ddl}, proxy)
    if not body.get("success"):
        print(f"❌ 建表失败: {body.get('errors')}")
        sys.exit(1)
    print("✅ 表已就绪")

    # 2) 写入 —— 走 /raw 端点(支持 bound params)
    payload = {"sql": INSERT_SQL, "params": [1, tree, stats]}
    try:
        body = _cf_post(token, "raw", payload, proxy)
    except Exception as e:
        # SSL 偶发 UNEXPECTED_EOF —— 网络抖动, 重试
        print(f"⚠️  {e} —— 重试一次")
        import time

        time.sleep(3)
        body = _cf_post(token, "raw", payload, proxy)

    if not body.get("success"):
        print(f"❌ {body}")
        sys.exit(1)
    print(f"✅ 远端 D1 已写入 catalog 表 ({len(tree)/1024:.1f} KB tree)")


def push_local(tree: str, stats: str):
    """本地 miniflare D1 —— 直接写 sqlite 文件。"""
    state = ROOT / "query" / "worker" / ".wrangler" / "state" / "v3" / "d1"
    if not state.exists():
        raise SystemExit(f"找不到本地 D1 目录: {state}  (先跑 wrangler dev)")

    # ⚠️ .wrangler/state 下**可能有多个** sqlite(database_id 改过会另建),
    #    必须挑 dev server 正在读的那个 —— 按 wrangler.local.toml 里的
    #    database_id 推导文件名前缀, 再按 mtime 取最新的。
    local_cfg = ROOT / "query" / "worker" / "wrangler.local.toml"
    prefix = None
    if local_cfg.exists():
        for line in local_cfg.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("database_id"):
                prefix = line.split("=", 1)[1].strip().strip('"')

    cands = sorted(state.glob("*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    if prefix:
        pref = [c for c in cands if c.name.startswith(prefix)]
        if pref:
            cands = pref
    if not cands:
        raise SystemExit(f"本地 D1 里没有 sqlite 文件: {state}")

    target = cands[0]
    print(f"→ 本地 D1: {target.name}")
    con = sqlite3.connect(str(target))
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS catalog ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), tree TEXT NOT NULL, "
            "stats TEXT, updated_at TEXT DEFAULT (datetime('now')))"
        )
        con.execute(INSERT_SQL, (1, tree, stats))
        con.commit()
        n = con.execute("SELECT length(tree) FROM catalog WHERE id=1").fetchone()
        print(f"✅ 本地 D1 已写入 catalog 表 (tree {n[0]/1024:.1f} KB)")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--remote", action="store_true", help="灌远端 D1")
    g.add_argument("--local", action="store_true", help="灌本地 miniflare D1")
    args = ap.parse_args()

    if not CATALOG_JSON.exists():
        raise SystemExit(
            f"找不到 {CATALOG_JSON}\n先跑: python build/export/build_catalog.py"
        )

    data = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    tree = json.dumps(data["scopes"], ensure_ascii=False, separators=(",", ":"))
    stats = json.dumps(data.get("stats", {}), ensure_ascii=False)

    s = data.get("stats", {})
    print(
        f"目录: scope {s.get('scopes')} · section {s.get('sections')} · "
        f"文件 {s.get('docs')} (匹配 {s.get('matched')} / 未匹配 {s.get('unmatched')})"
    )

    if args.remote:
        push_remote(tree, stats)
    else:
        push_local(tree, stats)


if __name__ == "__main__":
    main()
