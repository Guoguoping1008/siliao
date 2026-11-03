#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把人工校核后的 `review_checklist.csv` 回写到生产 D1。

## ⚠️ 有**两道**闸门,不是一道

判定引擎要同时拿到规则和物质目录,两道闸门**任一没开都恒返回 `not_covered`**:

| 表 | 谁在读 | 读取条件 |
|---|---|---|
| `compliance_rules` | `compliance.repository.impl.ts:60` | `review_status='reviewed'` |
| `substance_catalog` | `compliance.repository.impl.ts:67` | `review_status='reviewed'` |

实测证据(2026-11-03):只把 1 条规则置 `reviewed` → 判定**仍是** `not_covered`;
规则 + 目录**同时**置 reviewed → 13/13 全部命中判定。

**只校核规则是不够的** —— 目录那 387 条也得放行,否则规则匹配不到物质。

## 为什么需要这个脚本

`make_review_checklist.py` 生成 CSV 给检测所人员填 `decision` 列,
但**填完还得能写回 D1** —— 否则校核工作只产出了一张表,判定引擎依然看不到规则。

## decision 三态

| decision | 含义 | 动作 |
|---|---|---|
| `ok` | 规则值与原文一致 | `review_status='reviewed'` |
| `fix` | 值错了,fixed_* 列填了正确值 | 先 UPDATE 值,再置 `reviewed` |
| `reject` | 这条规则不该存在 | `review_status='rejected'` |

## ⚠️ 安全纪律

1. **默认 dry-run** —— 不加 `--apply` 只打印将要执行的操作。
2. **必须有 `reviewed_by`** —— 谁校核的要记下来,审计需要。
3. **未填 decision 的行一律跳过**(不算 reject,就是还没看)。
4. **CSV 里的 `rule_id` 必须能在生产 D1 找到** —— 找不到就报错退出,
   **不静默跳过**(静默跳过 = 以为校核完了,实际没写进去)。
5. **写完立即回读校验** —— 打印实际 `review_status` 分布。
6. **只写真实存在的列** —— 实测生产 `compliance_rules` **没有** `reviewed_by`
   也没有 `review_note`(`CREATE TABLE IF NOT EXISTS` 对已存在的表不加列);
   校核人记在 `rule_sets.reviewed_by`。

## 用法

```bash
# 只看要做什么(不改库)
python build/export/apply_review_checklist.py --reviewed-by "张三(检测所)"

# 真的写库
python build/export/apply_review_checklist.py --reviewed-by "张三" --apply

# 同时放行物质目录(387 条)—— ⚠️ 目录是权威清单,
# 放行前应确认「名称/别名」已核过(错了会导致搜不到或匹配错)
python build/export/apply_review_checklist.py --reviewed-by "张三" --apply --also-release-catalog
```

回滚:
```sql
UPDATE compliance_rules SET review_status='pending';
UPDATE substance_catalog SET review_status='pending';
```
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CSV_PATH = os.path.join(REPO, "build", "export", "review_checklist.csv")

ACCOUNT_ID = "1b938cc261b000a03554b506985daabb"
DB_ID = "e406e21e-e770-4c97-822a-57178c347aa6"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 允许的 decision 值
DECISIONS = {"ok", "fix", "reject"}


def load_token() -> str:
    home = os.path.expanduser("~")
    for p in [
        os.path.join(home, "AppData", "Roaming", "xdg.config", ".wrangler", "config", "default.toml"),
        os.path.join(home, ".wrangler", "config", "default.toml"),
    ]:
        if os.path.exists(p):
            m = re.search(r'(?:oauth_token|api_token)\s*=\s*"([^"]+)"',
                          io.open(p, encoding="utf-8").read())
            if m:
                return m.group(1)
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    raise SystemExit("[FAIL] 找不到 Cloudflare token —— 跑 python build/export/refresh_cf_token.py")


def d1(token: str, sql: str) -> dict:
    url = (f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
           f"/d1/database/{DB_ID}/query")
    req = urllib.request.Request(url, data=json.dumps({"sql": sql}).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[HTTP {e.code}]\n{e.read().decode('utf-8', 'ignore')[:600]}")


def rows(token: str, sql: str) -> list:
    d = d1(token, sql)
    result = d.get("result") or []
    return result[0].get("results", []) if result else []


def esc(v: str) -> str:
    """SQL 字符串字面量转义。"""
    return "'" + str(v or "").replace("'", "''") + "'"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewed-by", required=True, help="校核人(记入 rule_sets.reviewed_by)")
    ap.add_argument("--apply", action="store_true", help="真正写库(默认只 dry-run)")
    ap.add_argument("--csv", default=CSV_PATH, help="校核后的 CSV 路径")
    ap.add_argument(
        "--also-release-catalog",
        action="store_true",
        help="同时把 substance_catalog 全部置 reviewed(⚠️ 387 条,需已核过名称/别名)",
    )
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit(f"[FAIL] 找不到 {args.csv}")

    token = load_token()

    with io.open(args.csv, encoding="utf-8-sig", newline="") as f:
        rows_in = list(csv.DictReader(f))
    print(f"CSV 行数: {len(rows_in)}")

    # ── 生产 D1 里的真实 rule_id ──
    db = {r["rule_id"]: r for r in rows(
        token, "SELECT rule_id, substance, species, review_status FROM compliance_rules")}
    print(f"D1 规则数: {len(db)}")

    planned: list[tuple[str, dict]] = []
    skipped_no_decision = 0
    skipped_unknown_id = 0
    bad_decision: list[str] = []

    for r in rows_in:
        dec = (r.get("decision") or "").strip().lower()
        if not dec:
            skipped_no_decision += 1
            continue
        if dec not in DECISIONS:
            bad_decision.append(f"{r.get('no')}: {dec!r}")
            continue
        rid = (r.get("rule_id") or "").strip()
        if rid not in db:
            skipped_unknown_id += 1
            print(f"  [WARN] 第 {r.get('no')} 行 rule_id={rid!r} 在 D1 里找不到 —— 跳过")
            continue
        planned.append((dec, r))

    if bad_decision:
        print(f"\n[FAIL] decision 取值非法: {bad_decision}")
        print("       只接受 ok / fix / reject")
        return 1

    print(f"\n待处理: {len(planned)} | 未填 decision 跳过: {skipped_no_decision} "
          f"| rule_id 对不上跳过: {skipped_unknown_id}")

    by_dec = collections.Counter(d for d, _ in planned)
    print(f"  ok={by_dec['ok']}  fix={by_dec['fix']}  reject={by_dec['reject']}")

    if not planned:
        print("\n[SKIP] 没有待应用的行")
        return 0

    print("\n=== 将要执行的操作 ===")
    for dec, r in planned:
        rid = r["rule_id"]
        if dec == "ok":
            print(f"  ok      {rid}  {r['substance']} / {r['species']}  → reviewed")
        elif dec == "reject":
            print(f"  reject  {rid}  {r['substance']} / {r['species']}  → rejected")
        else:
            sets = []
            for col, fixed in [
                ("substance", "fixed_substance"), ("species", "fixed_species"),
                ("min_value", "fixed_min"), ("max_value", "fixed_max"), ("unit", "fixed_unit"),
            ]:
                v = (r.get(fixed) or "").strip()
                if v:
                    sets.append(f"{col}={esc(v)}")
            print(f"  fix     {rid}  {r['substance']} / {r['species']}"
                  f"  → {', '.join(sets) if sets else '(⚠️ 没填 fixed_* 列!)'} → reviewed")

    if not args.apply:
        print("\n[dry-run] 未写库。确认无误后加 --apply。")
        return 0

    # ── 写库 ──
    print("\n=== 写入 ===")
    for dec, r in planned:
        rid = esc(r["rule_id"])
        if dec == "ok":
            status = "reviewed"
            extra = ""
        elif dec == "reject":
            status = "rejected"
            extra = ""
        else:
            status = "reviewed"
            sets = []
            for col, fixed in [
                ("substance", "fixed_substance"), ("species", "fixed_species"),
                ("min_value", "fixed_min"), ("max_value", "fixed_max"), ("unit", "fixed_unit"),
            ]:
                v = (r.get(fixed) or "").strip()
                if v:
                    sets.append(f"{col}={esc(v)}")
            extra = (", " + ", ".join(sets)) if sets else ""

        # ⚠️ **只写真实存在的列** —— 生产 `compliance_rules` 的列是:
        #    rule_id / rule_type / substance / substance_alias / species / stage /
        #    min_value / max_value / unit / condition_text / source_article_id /
        #    source_doc_id / source_excerpt / rule_set_version / extraction_method /
        #    review_status / created_at / updated_at
        #
        #    **没有 `reviewed_by`,也没有 `review_note`** ——
        #    (误以为 migrate_c1.sql 里有,实测 PRAGMA table_info 查不到。
        #     `CREATE TABLE IF NOT EXISTS` 对已存在的表**不会加列**。)
        #    写了不存在的列 → SQL 直接报错,整批回写失败。
        #
        #    校核人记在 `rule_sets.reviewed_by`(那列确实存在)。
        extra = ""
        if dec == "ok":
            status = "reviewed"
        elif dec == "reject":
            status = "rejected"
        else:
            status = "reviewed"
            sets = []
            for col, fixed in [
                ("substance", "fixed_substance"), ("species", "fixed_species"),
                ("min_value", "fixed_min"), ("max_value", "fixed_max"), ("unit", "fixed_unit"),
            ]:
                v = (r.get(fixed) or "").strip()
                if v:
                    sets.append(f"{col}={esc(v)}")
            extra = (", " + ", ".join(sets)) if sets else ""

        sql = (
            f"UPDATE compliance_rules SET review_status={esc(status)}"
            f"{extra}, updated_at=datetime('now')"
            f" WHERE rule_id={rid}"
        )
        d1(token, sql)
        print(f"  ✅ {rid} → {status}")

    # ── 回读校验 ──
    print("\n=== 回读校验 ===")
    for r in rows(token, "SELECT review_status, COUNT(*) AS c FROM compliance_rules GROUP BY review_status"):
        print(f"  {r['review_status']:12} {r['c']}")

    # ⚠️ **第二道闸门**:物质目录也得放行,否则规则匹配不到物质 → 仍 not_covered
    if args.also_release_catalog:
        print("\n=== 放行物质目录(第二道闸门)===")
        d1(token, "UPDATE substance_catalog SET review_status='reviewed', updated_at=datetime('now')")
        for r in rows(token, "SELECT review_status, COUNT(*) AS c FROM substance_catalog GROUP BY review_status"):
            print(f"  {r['review_status']:12} {r['c']}")
    else:
        pend = rows(token, "SELECT COUNT(*) AS c FROM substance_catalog WHERE review_status='pending'")
        n = pend[0]["c"] if pend else 0
        print(f"\n  ⚠️ 物质目录仍有 {n} 条 pending —— **判定仍会返回 not_covered**")
        print("     (第二道闸门:compliance.repository.impl.ts:67)")
        print("     确认目录名称/别名已核过后,加 --also-release-catalog 重跑")

    # 记校核人到 rule_sets
    vers = rows(token, "SELECT version FROM rule_sets ORDER BY version DESC LIMIT 1")
    if vers:
        v = vers[0]["version"]
        d1(token, f"UPDATE rule_sets SET reviewed_by={esc(args.reviewed_by)} WHERE version={esc(v)}")
        print(f"  rule_sets[{v}].reviewed_by = {args.reviewed_by}")

    print("\n[OK] 校核结果已写回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
