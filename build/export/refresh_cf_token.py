#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare OAuth token 自动续期 —— 把「每小时重登一次」变成一条命令。

## 为什么需要这个脚本

wrangler 的 OAuth token **TTL 只有 1 小时**。过期后:

- `npx wrangler login` 要开浏览器点「Authorize」—— **headless/自动化环境做不了**
- refresh 看似可行,但 **Cloudflare 每次刷新都轮换 refresh_token**,
  旧的立刻失效(`invalid_grant`)→ **必须把新的 refresh_token 一起写回配置**
- 只写 access token 不写 refresh token → 下次 refresh 必然失败

实测踩过的坑都封在这个脚本里了:

| 坑 | 症状 | 本脚本的处理 |
|---|---|---|
| token 端点搞错 | `api.cloudflare.com/client/v4/oauth2/token` → **404 No route** | 用 `dash.cloudflare.com/oauth2/token` |
| 参数格式错 | 传 JSON → **400 invalid_request** | 用 **form-encoded** |
| client_id 猜错 | **400 invalid_request** | 从 wrangler 的 cli.js 里挖出真实值 |
| urllib 默认 UA 被拦 | **403 error code 1010** | 带浏览器样 User-Agent |
| refresh_token 没写回 | 下次 refresh 报 **invalid_grant** | **两个 token 一起写回** + 校验 |

## 用法

```bash
python build/export/refresh_cf_token.py            # 刷新(过期也能用)
python build/export/refresh_cf_token.py --check    # 只检查当前是否有效
```

## ⚠️ 什么时候仍需人工介入

refresh token 本身也被作废时(比如手动 `wrangler login` 覆盖了配置,
或 refresh_token 被用过一次而新的没写回),这时**只能重跑 `npx wrangler login`
并人工点 Authorize**。本脚本会明确告诉你这种情况。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# wrangler 内置的 OAuth client_id(从 node_modules/wrangler/wrangler-dist/cli.js 里挖出来的)
CLIENT_ID = "54d11594-84e4-41aa-b438-e81b8fa78ee7"
TOKEN_URL = "https://dash.cloudflare.com/oauth2/token"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# wrangler 的配置目录**不是** ~/.wrangler —— Windows 上在 xdg.config 下
CONFIG_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "xdg.config",
                 ".wrangler", "config", "default.toml"),
    os.path.join(os.path.expanduser("~"), ".wrangler", "config", "default.toml"),
    os.path.join(os.path.expanduser("~"), ".config", ".wrangler", "config", "default.toml"),
]


def find_config() -> pathlib.Path:
    for p in CONFIG_CANDIDATES:
        if os.path.exists(p):
            return pathlib.Path(p)
    raise SystemExit(
        "[FAIL] 找不到 wrangler 配置文件 —— 先跑 npx wrangler login"
        f"\n       找过: {CONFIG_CANDIDATES}"
    )


def read_field(text: str, key: str) -> str | None:
    m = re.search(rf'{re.escape(key)}\s*=\s*"([^"]*)"', text)
    return m.group(1) if m else None


def swap_field(text: str, key: str, value: str) -> str:
    """替换 TOML 里的字段;不存在就追加。"""
    pat = re.compile(rf'({re.escape(key)}\s*=\s*)"[^"]*"')
    if pat.search(text):
        return pat.sub(lambda m: f'{m.group(1)}"{value}"', text, count=1)
    return text + f'\n{key} = "{value}"\n'


def http_get_token(token: str) -> tuple[int, str]:
    """用 access token 打 /accounts 验活。"""
    req = urllib.request.Request("https://api.cloudflare.com/client/v4/accounts")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def refresh(refresh_token: str) -> dict:
    """用 refresh_token 换新的 token。⚠️ 失败通常意味着 refresh_token 已被作废。"""
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(
            f"[FAIL] refresh 失败(HTTP {e.code})\n{detail[:400]}\n"
            "  → refresh_token 已失效。**只能人工重登**:\n"
            "     npx wrangler login  (浏览器点 Authorize)"
        )
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"[FAIL] refresh 请求异常: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查当前 token 是否有效")
    ap.add_argument("--force", action="store_true", help="即使有效也强制刷新")
    args = ap.parse_args()

    cfg_path = find_config()
    cfg = cfg_path.read_text(encoding="utf-8")
    oauth = read_field(cfg, "oauth_token")
    rtok = read_field(cfg, "refresh_token")
    exp = read_field(cfg, "expiration_time")

    print(f"配置: {cfg_path}")
    print(f"当前过期时间: {exp or 'N/A'}")

    if not oauth:
        raise SystemExit("[FAIL] 配置里没有 oauth_token —— 先跑 npx wrangler login")

    status, _ = http_get_token(oauth)
    print(f"当前 access token: HTTP {status} {'✅ 有效' if status == 200 else '❌ 无效'}")

    if args.check:
        return 0 if status == 200 else 1

    if status == 200 and not args.force:
        print("\n✅ token 仍有效,无需刷新(要强制刷新加 --force)")
        return 0

    if not rtok:
        raise SystemExit("[FAIL] 配置里没有 refresh_token —— 只能人工 npx wrangler login")

    print("\n=== 刷新中 ===")
    new = refresh(rtok)

    access = new.get("access_token")
    new_refresh = new.get("refresh_token")
    expires_in = int(new.get("expires_in", 3600))

    if not access:
        raise SystemExit(f"[FAIL] 响应里没有 access_token: {list(new.keys())}")

    # ⚠️ **两个 token 都必须写回** ——
    # Cloudflare 每次刷新都轮换 refresh_token,旧的立刻失效。
    # 只写 access token → 下次 refresh 报 invalid_grant。
    cfg = swap_field(cfg, "oauth_token", access)
    if new_refresh:
        cfg = swap_field(cfg, "refresh_token", new_refresh)
    exp_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=expires_in)
    cfg = swap_field(cfg, "expiration_time", exp_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    cfg_path.write_text(cfg, encoding="utf-8")

    print(f"  ✅ access_token  已更新({expires_in}s)")
    print(f"  ✅ refresh_token {'已更新(轮换)' if new_refresh and new_refresh != rtok else '未变'}")
    print(f"  ✅ expiration    {exp_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    status, _ = http_get_token(access)
    print(f"\n验证: HTTP {status} {'✅' if status == 200 else '❌'}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
