#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生产响应基线 —— 抓取真实 API 响应, 用于重构前后逐字段比对
================================================================

## 为什么需要

ADR-004 M1 的教训(记录在 `docs/adr/0004-ddd-bounded-contexts.md`):

> M1 重构抓到两个回归 —— `chapter_number` 从 `""` 变 `null`、
> `is_toc` 字段凭空多出。
> **两者都逃过了所有本地测试**: 类型系统不报错、单测不失败、
> eval 门禁照样绿(eval 是 Python 复刻, e2e 走 mock 模式,
> 都不碰真实 Worker 的映射层)。
> **只有拿生产 API 的实际响应做前后比对才抓到。**

M3(路由层抽离)是同类重构 —— 路由顺序、参数 decode、SSE 帧格式、
错误响应形状都可能悄悄变。所以流程固化:

    ① 重构前抓生产基线  →  ② 重构后抓新的  →  ③ 逐字段比对

## 用法

    # 抓基线
    python evals/capture_api_baseline.py --out evals/api_baseline.json

    # 跟基线比(默认比当前生产 vs 仓库里的基线)
    python evals/capture_api_baseline.py --compare

## 比对什么

对每个端点:
  · **字段集合** —— 顶层与嵌套对象的键集合(不多不少)
  · **标量值** —— 非列表的字段值(列表只比长度与首元素)
  · **状态码**
  · **SSE 事件序列** —— 流式端点的事件名顺序

⚠️ **不比列表内容** —— 检索结果每次都不同(向量检索有微小浮动),
   比内容会一直假失败。比「结构」不比「数据」。
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "evals" / "api_baseline.json"

# ⚠️ API_BASE **不带** /api 后缀 —— 下面的端点路径自带 /api/xxx
API_BASE = "https://siliao-web.pages.dev"

# 浏览器样 UA —— urllib 默认 UA 会被 Cloudflare 拦(403 error code 1010)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def _req(url: str, method: str = "GET", body: dict | None = None) -> urllib.request.Request:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")
    return req


def _read(resp: urllib.error.HTTPError | http.client.HTTPResponse) -> dict[str, Any]:
    """读响应体(成功与错误都要读)。"""
    raw = resp.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"__raw__": raw[:500]}


def get_json(path: str) -> dict[str, Any]:
    """GET 一个 JSON 端点。

    ⚠️ **4xx 也要抓** —— 「缺 query → 400」本身就是一个响应契约,
    重构后必须仍是同样的错误形状。
    """
    try:
        with urllib.request.urlopen(_req(f"{API_BASE}{path}"), timeout=60) as resp:
            return {"status": resp.status, "body": _read(resp)}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": _read(e)}


def post_json(path: str, body: dict) -> dict[str, Any]:
    """POST 一个 JSON 端点(4xx 也要抓)。"""
    try:
        with urllib.request.urlopen(
            _req(f"{API_BASE}{path}", "POST", body), timeout=60
        ) as resp:
            return {"status": resp.status, "body": _read(resp)}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": _read(e)}


def post_sse(path: str, body: dict) -> dict[str, Any]:
    """POST 一个 SSE 端点, 抽事件名序列。

    ⚠️ **读到 `done` 事件就停** —— 与前端 `consumeQAStream` 的行为一致。
       上游 LLM 的 SSE 连接不一定发 `[DONE]` 就关闭, 一直读到 EOF 会超时。
    """
    req = _req(f"{API_BASE}{path}", "POST", body)
    req.add_header("Accept", "text/event-stream")
    events: list[str] = []
    with urllib.request.urlopen(req, timeout=90) as resp:
        buf = ""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "ignore")
            # 只消费完整的帧(以空行结尾)
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                for line in frame.split("\n"):
                    if line.startswith("event:"):
                        name = line.split(":", 1)[1].strip()
                        events.append(name)
                        if name in ("done", "error"):
                            return {"status": 200, "events": events}
                        break
    return {"status": 200, "events": events}


# ─────────────────────────────────────────────────────────────
# 端点清单
# ─────────────────────────────────────────────────────────────


def capture() -> dict[str, Any]:
    """抓所有端点的响应。"""
    out: dict[str, Any] = {}

    print("[1/8] GET /api/documents")
    out["GET /api/documents"] = get_json("/api/documents")

    print("[2/8] GET /api/catalog")
    out["GET /api/catalog"] = get_json("/api/catalog")

    print("[3/8] GET /api/search?q=审定")
    out["GET /api/search"] = get_json("/api/search?q=%E5%AE%A1%E5%AE%9A&limit=5")

    print("[4/8] GET /api/entity/农业农村部")
    out["GET /api/entity"] = get_json("/api/entity/%E5%86%9C%E4%B8%9A%E5%86%9C%E6%9D%91%E9%83%A8")

    print("[5/8] POST /api/qa")
    out["POST /api/qa"] = post_json("/api/qa", {"q": "饲料添加剂审定需要哪些材料"})

    print("[6/8] POST /api/qa (缺 query → 400)")
    out["POST /api/qa missing"] = post_json("/api/qa", {})

    print("[7/8] POST /api/compliance/usage (参数错 → 400)")
    out["POST /api/compliance invalid"] = post_json(
        "/api/compliance/usage", {"substance": "", "species": "", "value": 0, "unit": ""}
    )

    print("[8/8] POST /api/qa?stream=true (SSE 事件序列)")
    out["POST /api/qa stream"] = post_sse(
        "/api/qa?stream=true", {"q": "饲料添加剂审定需要哪些材料", "stream": True}
    )

    return out


# ─────────────────────────────────────────────────────────────
# 结构化 —— 只比结构, 不比数据
# ─────────────────────────────────────────────────────────────


def shape(value: Any, depth: int = 0) -> Any:
    """把响应转成「结构」(字段集合 + 标量值), 列表只留长度与首元素形状。"""
    if depth > 6:
        return "<deep>"
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in sorted(value.items())}
    if isinstance(value, list):
        if not value:
            return {"__list__": 0}
        return {"__list__": len(value), "__first__": shape(value[0], depth + 1)}
    if isinstance(value, str):
        # 长文本会每次变 —— 只留长度与类型
        return f"<str:{len(value)}>"
    return value


def diff_shapes(a: Any, b: Any, path: str = "") -> list[str]:
    """比对两个形状, 返回差异描述列表。"""
    diffs: list[str] = []
    if type(a) is not type(b) and not (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
    ):
        return [f"{path or '<root>'}: 类型不同 {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        ka, kb = set(a), set(b)
        for k in sorted(ka - kb):
            diffs.append(f"{path}.{k}: 基线有, 现在没有")
        for k in sorted(kb - ka):
            diffs.append(f"{path}.{k}: 现在多出来")
        for k in sorted(ka & kb):
            diffs.extend(diff_shapes(a[k], b[k], f"{path}.{k}"))
        return diffs
    if isinstance(a, dict) and "__list__" in a:
        if a["__list__"] != b["__list__"]:
            # 长度可以差(检索结果浮动), 只提示
            diffs.append(f"{path}: 列表长度 {a['__list__']} → {b['__list__']}(允许浮动)")
        return diffs
    if a != b:
        diffs.append(f"{path}: 值 {a!r} → {b!r}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BASELINE), help="基线输出路径")
    ap.add_argument("--compare", action="store_true", help="抓当前并与基线比对")
    args = ap.parse_args()

    print(f"[capture] {API_BASE}\n")
    try:
        current = capture()
    except urllib.error.HTTPError as e:
        print(f"❌ 抓取失败: HTTP {e.code} — {e.read().decode('utf-8', 'ignore')[:300]}")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"❌ 抓取失败: {e}")
        return 2

    out_path = Path(args.out)
    if not args.compare:
        out_path.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n✅ 基线 → {out_path}")
        return 0

    # ── 比对 ──
    if not BASELINE.exists():
        print(f"❌ 没有基线: {BASELINE}\n   先跑 --out 抓一份")
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    all_diffs: list[str] = []
    for endpoint, want in baseline.items():
        got = current.get(endpoint)
        if got is None:
            all_diffs.append(f"{endpoint}: 现在没有这个端点")
            continue
        if "status" in want and want["status"] != got.get("status"):
            all_diffs.append(
                f"{endpoint}: 状态码 {want['status']} → {got.get('status')}"
            )
        if "events" in want:
            if want["events"] != got.get("events"):
                all_diffs.append(
                    f"{endpoint}: SSE 事件序列 {want['events']} → {got.get('events')}"
                )
            continue
        d = diff_shapes(shape(want.get("body")), shape(got.get("body")))
        all_diffs.extend(f"{endpoint}{x}" for x in d)

    if all_diffs:
        print(f"\n❌ 发现 {len(all_diffs)} 处结构差异:\n")
        for x in all_diffs:
            print(f"  {x}")
        return 1

    print("\n✅ 结构完全一致 —— 重构未改变任何响应契约")
    return 0


if __name__ == "__main__":
    sys.exit(main())
