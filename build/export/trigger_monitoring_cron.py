"""
手动触发生产 Worker's Cron scheduled event —— 验证 ⑤ 定时抓取真的能跑。

用法:
    python build/export/trigger_monitoring_cron.py

原理: Cloudflare API 的 `PUT /accounts/{id}/workers/scripts/{name}/schedules` 不行,
      手动触发 scheduled event 用的是:
      POST /accounts/{account_id}/workers/scripts/{script_name}/scheduled
      —— 但这个端点需要 script 名,且 Cloudflare 未公开稳定的「手动触发 cron」API。

      所以本脚本走 **wrangler dev --test-scheduled** 同款的机制不行(那是本地),
      生产只能靠等真实 cron 到达。

      替代方案:本脚本**读 D1 的 monitoring_runs**,确认 cron 是否跑过;
      并可选地调 POST /api/monitoring/collect 做一次手动抓取作为对照。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
WORKER = ROOT / "query" / "worker"

# 生产 API(走 Pages 代理,直连 workers.dev 在部分网络环境不通)
API = "https://siliao-web.pages.dev"


def call(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main() -> int:
    print("=== ① 查最近的 cron 运行记录 ===")
    status, text = call("/api/monitoring/runs?limit=10")
    if status != 200:
        print(f"❌ 查询失败 HTTP {status}: {text[:200]}")
        return 1
    try:
        runs = json.loads(text).get("runs", [])
    except json.JSONDecodeError:
        print(f"❌ 响应不是 JSON: {text[:200]}")
        return 1

    if not runs:
        print("(还没有任何运行记录)")
    for r in runs:
        print(
            f"  {r['runId']:24} {r['status']:8} pages={r['pages']} "
            f"found={r['found']} ok={r['bodiesOk']} fail={r['bodiesFail']} "
            f"new={r['newCount']} revised={r['revisedCount']}"
        )

    # cron 触发的 run,run_id 形如 run_20261111060014(无后缀区分),
    # 手动 collect 也是同一个格式 —— 所以这里只能靠时间与频率判断。
    print("\n=== ② 手动触发一次抓取(对照组) ===")
    status, text = call("/api/monitoring/collect", "POST", {"pages": 1, "maxBodies": 3})
    if status != 200:
        print(f"❌ 触发失败 HTTP {status}: {text[:300]}")
        return 1
    try:
        res = json.loads(text)
    except json.JSONDecodeError:
        print(f"❌ 响应不是 JSON: {text[:300]}")
        return 1

    print(
        f"  runId={res.get('runId')} found={res.get('found')} "
        f"new={res.get('newCount')} revised={res.get('revisedCount')} "
        f"impacted={len(res.get('impacted', []))}"
    )
    for r in res.get("impacted", []):
        print(f"   ✔ {r['releaseKey']} {r['title'][:40]} → {r['affectedAssets']}")

    print("\n=== ③ 当前部署的 cron 配置 ===")
    try:
        toml = (WORKER / "wrangler.toml").read_text(encoding="utf-8")
        m = re.search(r"\[triggers\]\s*\ncrons\s*=\s*\[([^\]]+)\]", toml)
        if m:
            crons = [c.strip().strip('"') for c in m.group(1).split(",")]
            for c in crons:
                print(f"  cron {c}  (UTC)")
            print("  说明:crontab 按 UTC 解析,不是北京时间")
        else:
            print("  (未找到 [triggers] 配置)")
    except Exception as e:  # noqa: BLE001
        print(f"  (读取 wrangler.toml 失败: {e})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
