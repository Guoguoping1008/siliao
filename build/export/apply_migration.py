#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性迁移执行器 —— 把 .sql 文件按语句拆开, 用 D1 REST API /query 端点执行。

⚠️ **为什么不用 `wrangler d1 execute --file`**
    wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO, **会清空远端表**。
    生产库有 3145 条条文 —— 绝不能冒这个险。
    DDL 走 REST /query 端点(它不支持 bound params, 所以 DDL 与 DML 分开处理)。

⚠️ **只建表,不碰已有表**
    所有语句都是 CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS,
    对已存在的表是 no-op。

用法:
    python apply_migration.py <sql文件> [<sql文件> ...]
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

ACCOUNT_ID = "1b938cc261b000a03554b506985daabb"
DB_ID = "e406e21e-e770-4c97-822a-57178c347aa6"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_token() -> str:
    """从 wrangler 的认证文件里取 token(Windows 路径)。"""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".wrangler", "config", "default.toml"),
        os.path.join(home, ".config", ".wrangler", "config", "default.toml"),
        os.path.join(
            home, "AppData", "Roaming", "xdg.config", ".wrangler", "config", "default.toml"
        ),
    ]
    for p in candidates:
        if os.path.exists(p):
            content = io.open(p, encoding="utf-8").read()
            m = re.search(r'(?:oauth_token|api_token)\s*=\s*"([^"]+)"', content)
            if m:
                return m.group(1)
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    raise SystemExit("[FAIL] 找不到 Cloudflare token —— 先跑 npx wrangler login")


def exec_sql(token: str, sql: str) -> dict:
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
        f"/d1/database/{DB_ID}/query"
    )
    req = urllib.request.Request(url, data=json.dumps({"sql": sql}).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(f"[HTTP {e.code}] {sql[:120]}...\n{detail[:600]}")


def split_statements(path: str) -> list[str]:
    """拆 SQL: 去整行注释, 按分号切。"""
    content = io.open(path, encoding="utf-8").read()
    lines = [ln for ln in content.split("\n") if not ln.strip().startswith("--")]
    sql = "\n".join(lines)
    return [p.strip() for p in sql.split(";") if p.strip()]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    token = load_token()
    for path in sys.argv[1:]:
        if not os.path.exists(path):
            print(f"[FAIL] 文件不存在: {path}")
            return 1
        stmts = split_statements(path)
        print(f"\n=== {os.path.basename(path)} — {len(stmts)} 条语句 ===")
        for i, st in enumerate(stmts, 1):
            head = " ".join(st.split())[:78]
            exec_sql(token, st)
            print(f"  [{i}/{len(stmts)}] ✅ {head}")
    print("\n[OK] 迁移完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
