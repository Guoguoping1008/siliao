#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C1 · 合规规则灌库 —— 把抽取候选写进 D1

用法
----
    # 本地
    python build/export/seed_compliance.py --local
    # 生产
    python build/export/seed_compliance.py --remote

⚠️ **审核闸门**
    抽取产物默认 `review_status='pending'` —— **不参与判定**。
    本脚本支持 `--mark-reviewed` 把全部规则标成已审核,
    但**只应在人工逐条校核之后**才用。

    生产默认灌 `pending`(安全); 校核完成后用
    `python build/export/seed_compliance.py --remote --mark-reviewed` 提升。

⚠️ **D1 灌库方式**
    用 D1 REST API 的 bound params(和 push_d1_bodies.py 一样)——
    不用 `wrangler d1 execute --file`:
      - wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO, 还会清空远端表
      - 正文含换行, 拼进 SQL 字符串会踩 SQLite 限制
"""

import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXPORT = os.path.join(REPO, "build", "export")
WORKER = os.path.join(REPO, "query", "worker")

RULES_JSON = os.path.join(EXPORT, "compliance_rules.json")
CATALOG_JSON = os.path.join(EXPORT, "substance_catalog.json")
SCHEMA_SQL = os.path.join(WORKER, "migrate_c1.sql")

ACCOUNT_ID = "1b938cc261b000a03554b506985daabb"
DB_ID = "e406e21e-e770-4c97-822a-57178c347aa6"
DB_NAME = "siliao-db"


def load_account_token():
    """从 wrangler 认证信息里拿 token。

    ⚠️ wrangler 的配置目录**不是** ~/.wrangler —— 实测在
       ~/AppData/Roaming/xdg.config/.wrangler/config/default.toml (Windows)。
    """
    candidates = [
        os.path.join(os.path.expanduser("~"), ".wrangler", "config", "default.toml"),
        os.path.join(os.path.expanduser("~"), ".config", ".wrangler", "config", "default.toml"),
        # Windows: wrangler 用 XDG 风格路径
        os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming", "xdg.config",
            ".wrangler", "config", "default.toml",
        ),
    ]
    for p in candidates:
        if os.path.exists(p):
            content = io.open(p, encoding="utf-8").read()
            m = re.search(r'(?:oauth_token|api_token)\s*=\s*"([^"]+)"', content)
            if m:
                return m.group(1)
    # 环境变量
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    return None


def api_request(path, token, method="GET", body=None):
    url = f"https://api.cloudflare.com/client/v4{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        # ⚠️ 把 Cloudflare 的错误码打全 —— 401 是「token 没 D1 权限」,
        #    403 是「权限不够」, 两者要区分开, 否则 CI 日志只一句 SystemExit
        #    看不出是 token 问题还是 SQL 问题。
        print(f"[HTTP {e.code}] {method} {path}", file=sys.stderr)
        print(f"[BODY] {detail[:1200]}", file=sys.stderr)
        if e.code in (401, 403):
            print(
                "[提示] 灌库需要 **D1 写权限**。deploy.yml 用的 token 是最小权限的, "
                "实测 /d1/database 返回 401 —— 需要一个有 D1 编辑权限的 token。",
                file=sys.stderr,
            )
        raise SystemExit(f"[HTTP {e.code}] {path}\n{detail[:600]}")


def exec_sql(token, statements):
    """用 D1 REST API 执行 SQL(bound params)。"""
    path = f"/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/query"
    result = api_request(path, token, "POST", {"sql": statements})
    return result


def load_sql_file(path):
    """读 .sql 文件, 按分号切分(忽略注释行)。"""
    content = io.open(path, encoding="utf-8").read()
    # 去行注释
    lines = [ln for ln in content.split("\n") if not ln.strip().startswith("--")]
    sql = "\n".join(lines)
    # 按分号切 —— 简单语句, 不含分号字面量
    parts = [p.strip() for p in sql.split(";") if p.strip()]
    return parts


def bind_rows(table, cols, rows):
    """生成批量 INSERT 的 SQL + bound params。"""
    if not rows:
        return None, []
    placeholders = ",".join(f"?{i + 1}" for i in range(len(cols)))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    return sql, rows


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    remote = "--remote" in sys.argv
    mark_reviewed = "--mark-reviewed" in sys.argv

    token = load_account_token()
    if not token:
        print("[FAIL] 找不到 Cloudflare token。设置 CLOUDFLARE_API_TOKEN 环境变量,")
        print("       或先跑 npx wrangler login")
        sys.exit(1)

    # ── 1. 建表 ──
    print("[1/4] 建表 (migrate_c1.sql)")
    for stmt in load_sql_file(SCHEMA_SQL):
        exec_sql(token, stmt)
    print("       ✅ 3 张表就绪")

    # ── 2. 读抽取产物 ──
    rules_data = json.load(io.open(RULES_JSON, encoding="utf-8"))
    cat_data = json.load(io.open(CATALOG_JSON, encoding="utf-8"))
    version = rules_data.get("rule_set_version", "v2026.10")
    rules = rules_data.get("rules", [])
    catalog = cat_data.get("substances", [])

    print("[2/4] 载入抽取产物")
    print("       规则 %d 条 | 物质目录 %d 条 | 版本 %s" % (len(rules), len(catalog), version))
    if not rules:
        print("[FAIL] 没有规则。先跑 python build/export/extract_compliance_rules.py")
        sys.exit(1)

    # ── 3. 审核状态 ──
    status = "reviewed" if mark_reviewed else "pending"
    if mark_reviewed:
        print("[3/4] ⚠️  标记为 reviewed —— **应已完成人工逐条校核**")
    else:
        print("[3/4] 标记为 pending(未审核规则不参与判定)")

    # ── 4. 灌库 ──
    print("[4/4] 灌数据")

    # rule_sets
    # 用 bound params 逐条写
    path = f"/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/query"

    def exec_bound(sql, params):
        api_request(path, token, "POST", {"sql": sql, "params": params})

    exec_bound(
        "INSERT OR REPLACE INTO rule_sets (version, note, rules_count) VALUES (?1, ?2, ?3)",
        [version, f"C1 自动抽取导入 ({len(rules)} 条规则)", len(rules)],
    )
    print(f"       rule_sets: 1 条 (版本 {version})")

    # compliance_rules —— 逐条写, 因为每行列数不同
    rule_cols = [
        "rule_id", "rule_type", "substance", "substance_alias",
        "species", "stage", "min_value", "max_value", "unit",
        "condition_text", "source_article_id", "source_doc_id", "source_excerpt",
        "rule_set_version", "extraction_method", "review_status",
    ]
    n = 0
    for r in rules:
        rid = r.get("rule_id") or make_rule_id(r)
        exec_bound(
            f"INSERT OR REPLACE INTO compliance_rules ({','.join(rule_cols)}) "
            f"VALUES ({','.join('?' + str(i + 1) for i in range(len(rule_cols)))})",
            [
                rid, r.get("rule_type", "limit"), r.get("substance"),
                r.get("substance_alias"), r.get("species"), r.get("stage"),
                r.get("min_value"), r.get("max_value"), r.get("unit"),
                r.get("condition_text"), r.get("source_article_id", ""),
                r.get("source_doc_id", ""), r.get("source_excerpt"),
                version, r.get("extraction_method", "auto"), status,
            ],
        )
        n += 1
    print(f"       compliance_rules: {n} 条")

    # substance_catalog
    cat_cols = [
        "substance_id", "name_cn", "name_en", "substance_alias",
        "formula", "source", "spec", "category", "scope_text",
        "source_article_id", "source_doc_id", "rule_set_version", "review_status",
    ]
    m = 0
    for c in catalog:
        exec_bound(
            f"INSERT OR REPLACE INTO substance_catalog ({','.join(cat_cols)}) "
            f"VALUES ({','.join('?' + str(i + 1) for i in range(len(cat_cols)))})",
            [
                c.get("substance_id") or make_substance_id(c), c.get("name_cn", ""),
                c.get("name_en") or None, c.get("substance_alias") or None,
                c.get("formula") or None, c.get("source") or None,
                c.get("spec") or None, c.get("category") or None,
                c.get("scope_text") or None, c.get("source_article_id", ""),
                c.get("source_doc_id", ""), version, status,
            ],
        )
        m += 1
    print(f"       substance_catalog: {m} 条")

    # ── 校验 ──
    print("\n=== 校验 ===")
    res = api_request(path, token, "POST", {
        "sql": "SELECT COUNT(*) as c FROM compliance_rules WHERE review_status = ?1",
        "params": [status],
    })
    cnt = res.get("result", [{}])[0].get("c", 0)
    print(f"  compliance_rules (review_status={status}): {cnt}")

    res = api_request(path, token, "POST", {
        "sql": "SELECT COUNT(*) as c FROM substance_catalog",
    })
    print(f"  substance_catalog: {res.get('result', [{}])[0].get('c', 0)}")

    # 溯源完整性
    res = api_request(path, token, "POST", {
        "sql": "SELECT COUNT(*) as c FROM compliance_rules WHERE source_article_id IS NULL OR source_article_id = ''",
    })
    bad = res.get("result", [{}])[0].get("c", 0)
    print(f"  无溯源的规则: {bad} {'✅' if bad == 0 else '❌'}")

    print("\n[OK] 灌库完成")


def make_rule_id(r):
    """稳定 rule_id —— 同样的规则每次生成同样的 id。"""
    import hashlib
    key = "|".join([
        str(r.get("substance")), str(r.get("species")), str(r.get("stage")),
        str(r.get("min_value")), str(r.get("max_value")), str(r.get("unit")),
        str(r.get("source_article_id")),
    ])
    return "r_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def make_substance_id(c):
    import hashlib
    key = str(c.get("name_cn"))
    return "s_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


if __name__ == "__main__":
    main()
