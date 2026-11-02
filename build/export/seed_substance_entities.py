#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
④ 知识图谱 —— 把《饲料添加剂品种目录》的 387 条物质**补进实体层**并建立关联

## 为什么需要这个脚本

生产 `entities` 表有 94 个实体,但**全是 GraphRAG 抽的通用法律概念**
(ACTION / PARTY / DOCUMENT / PENALTY …),**没有一条是「物质」**。

实测:`substance_catalog` 的 387 条物质与 `entities` 重名 **0 条** —— 
《饲料添加剂品种目录》这份权威清单,在图谱里**完全缺席**。

后果:合规速查(C1)知道「维生素C 猪 150~300mg/kg」,但图谱查不到「维生素C」
这个实体 —— **图谱与业务主语脱节**。

## 为什么不重跑 GraphRAG

GraphRAG 产物(`build/graphrag/output/*/artifacts/*.parquet`)已清理,
run.sh 要 LLM key 逐章节跑;而且那次只跑了 **16 个 chunk**,
语料早扩到 3145 条文,产物与现状严重脱节。

## 关联策略:权威出处 + 三路变体

| 来源 | 内容 | 性质 |
|---|---|---|
| **① 权威出处** | `substance_catalog.source_article_id` —— 每条物质在《品种目录》里的出处条文 | **零猜测**,不变量 2 的溯源字段 |
| **② 括号别名** | `核黄素(维生素B2)` → `维生素B2` | 长名字在正文里写的是简称 |
| **③ 英文名** | `name_en` | 目录是双语的,正文可能是英文 |
| **④ 显式别名** | `substance_alias` | 人工补的同义词 |

**为什么必须以①为主**:实测 387 条里 **387 条**都有 `source_article_id`,
且全部指向《饲料添加剂品种目录》的 4 个条文 —— 那是**权威出处**。
②③④ 只是补充「正文里还提到它」的条文。

**为什么不只靠正文匹配**:目录里的名字是「通用名称」,
正文里可能写简称;而且带规格的长名字
(`液体L-赖氨酸(L-赖氨酸含量不低于50%)`)在正文里**根本不会出现**。

## 用法

```bash
python build/export/seed_substance_entities.py --dry-run   # 只算不写
python build/export/seed_substance_entities.py --remote    # 写入生产
```

## ⚠️ 幂等

`entities.entity_id` 用 **`sub_` + name_cn 的 sha1[:12]**(与 `substance_catalog.substance_id`
同一算法)—— 重复执行不会产生重复实体,也不会与既有实体冲突
(实测 387 条与现有 94 个实体的 name 重名 0 条)。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOG_JSON = os.path.join(REPO, "build", "export", "substance_catalog.json")
ARTICLES_JSON = os.path.join(REPO, "data", "index", "minimax", "articles.json")

ACCOUNT_ID = "1b938cc261b000a03554b506985daabb"
DB_ID = "e406e21e-e770-4c97-822a-57178c347aa6"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

CONTENT_KINDS = {"article", "section", "section-split", "article-split"}
MAX_PER_ENTITY = 50

# 实体类型:目录里的物质 —— 与 GraphRAG 的 SUBSTANCE 一致
ENTITY_TYPE = "SUBSTANCE"


def load_token() -> str:
    home = os.path.expanduser("~")
    for p in [
        os.path.join(home, "AppData", "Roaming", "xdg.config", ".wrangler", "config", "default.toml"),
        os.path.join(home, ".wrangler", "config", "default.toml"),
        os.path.join(home, ".config", ".wrangler", "config", "default.toml"),
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


def d1(token: str, sql: str, params: list | None = None) -> dict:
    payload: dict = {"sql": sql}
    if params:
        payload["params"] = params
    url = (f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}"
           f"/d1/database/{DB_ID}/query")
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise SystemExit(f"[HTTP {e.code}]\n{detail[:800]}")


def count_of(res: dict) -> int:
    result = res.get("result") or []
    if not result:
        return 0
    rows = result[0].get("results") or []
    if not rows:
        return 0
    return int(rows[0].get("c", 0) or 0)


def make_entity_id(name_cn: str) -> str:
    """与 substance_catalog.substance_id 同一算法 —— 保证两侧 id 对齐。"""
    return "sub_" + hashlib.sha1(str(name_cn).encode("utf-8")).hexdigest()[:12]


def variants(c: dict) -> list[str]:
    """三路变体:括号别名 / 英文名 / 显式别名。"""
    out: list[str] = []
    m = re.search(r"[（(]([^）)]+)[）)]", c.get("name_cn") or "")
    if m:
        out.append(m.group(1))
    if c.get("name_en"):
        out.append(c["name_en"])
    if c.get("substance_alias"):
        out.append(c["substance_alias"])
    # 长度 < 2 的变体(如「β」「4」)会误命中大量无关条文 —— 丢弃
    return [v for v in dict.fromkeys(out) if v and len(v) >= 2]


def build(catalog: list[dict], articles: list[dict]) -> tuple[list[dict], list[tuple[str, str]], list[str], list[tuple[str, str, str]]]:
    """返回 (实体列表, 关联列表, 零关联名单, 别名列表)。"""
    by_id = {a["article_id"]: a for a in articles}
    content = [a for a in articles if a.get("kind") in CONTENT_KINDS]

    entities: list[dict] = []
    links: list[tuple[str, str]] = []
    zero: list[str] = []

    for c in catalog:
        name = (c.get("name_cn") or "").strip()
        if not name:
            continue
        eid = make_entity_id(name)
        entities.append({
            "entity_id": eid,
            "name": name,
            "type": ENTITY_TYPE,
            # 描述用目录里的规格/适用范围原文 —— 不编造
            "description": (c.get("scope_text") or c.get("spec") or "") or None,
            "doc_id": c.get("source_doc_id"),
        })

        hits: set[str] = set()
        # ① 权威出处 —— 必连
        src = c.get("source_article_id")
        if src and src in by_id:
            hits.add(src)
        # ②③④ 三路变体 —— 补充「正文里还提到它」的条文
        for v in variants(c):
            for a in content:
                if (v in (a.get("text") or "") or v in (a.get("title") or "")
                        or v in (a.get("number") or "")):
                    hits.add(a["article_id"])
                    if len(hits) >= MAX_PER_ENTITY:
                        break
            if len(hits) >= MAX_PER_ENTITY:
                break

        if not hits:
            zero.append(name)
        for h in sorted(hits)[:MAX_PER_ENTITY]:
            links.append((eid, h))

    return entities, links, zero, build_aliases(catalog)


def build_aliases(catalog: list[dict]) -> list[tuple[str, str, str]]:
    """构建别名表。

    ⚠️ **一个别名指向多个实体时一律不入库** —— 查到了也只能随便挑一个,
    那是在猜。实测 7 个这样的别名(维生素B1 → 盐酸硫胺/硝酸硫胺;螯合物 → 9 个络合物)。

    这与 ② 合规规则的 `alignSubstanceName` 是同一条纪律:**候选不唯一就不采用**。
    宁可「查不到」,也不给错答案。

    ⚠️ **别名也不能与任何主名冲突** —— 否则「维生素C」到底指向谁说不清。
    """
    names = {c["name_cn"] for c in catalog}

    # 第一遍:收集每个别名指向哪些实体
    candidates: dict[str, list[tuple[str, str]]] = {}
    for c in catalog:
        eid = make_entity_id(c["name_cn"])
        for alias, kind in alias_candidates(c):
            if not alias or len(alias) < 2:
                continue
            if alias in names:
                continue  # 与主名冲突 → 跳过
            candidates.setdefault(alias, []).append((eid, kind))

    out: list[tuple[str, str, str]] = []
    for alias, lst in candidates.items():
        targets = {eid for eid, _ in lst}
        if len(targets) != 1:
            continue  # ⚠️ 一对多 → 不收录
        eid = targets.pop()
        kind = next(k for e, k in lst if e == eid)
        out.append((alias, eid, kind))
    return out


def alias_candidates(c: dict) -> list[tuple[str, str]]:
    """(别名, 种类) 列表:括号别名 / 显式别名 / 英文名。"""
    out: list[tuple[str, str]] = []
    m = re.search(r"[（(]([^）)]+)[）)]", c.get("name_cn") or "")
    if m:
        out.append((m.group(1).strip(), "bracket"))
    if c.get("substance_alias"):
        out.append((str(c["substance_alias"]).strip(), "alias"))
    if c.get("name_en"):
        out.append((str(c["name_en"]).strip(), "en"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true", help="写入生产")
    ap.add_argument("--dry-run", action="store_true", help="只算不写")
    args = ap.parse_args()

    token = load_token()
    catalog = json.load(io.open(CATALOG_JSON, encoding="utf-8"))["substances"]
    articles = json.load(io.open(ARTICLES_JSON, encoding="utf-8"))
    print(f"目录条目: {len(catalog)} | 全部条文: {len(articles)}")

    entities, links, zero, aliases = build(catalog, articles)
    print(f"\n实体: {len(entities)} | 关联: {len(links)} | 零关联: {len(zero)}")
    print(f"别名: {len(aliases)} 条(一对多的已剔除)")
    kinds = collections.Counter(k for _, _, k in aliases)
    print(f"  别名种类: {dict(kinds)}")
    print(f"  样例: {[(a, k) for a, _, k in aliases[:6]]}")

    # 现有实体里已有的名字(避免重复插入)
    res = d1(token, "SELECT name FROM entities")
    result = res.get("result") or []
    existing = {r["name"] for r in (result[0].get("results", []) if result else [])}
    dup = [e["name"] for e in entities if e["name"] in existing]
    if dup:
        print(f"⚠️ 已存在同名实体 {len(dup)} 条(将跳过): {dup[:5]}")
        entities = [e for e in entities if e["name"] not in existing]

    dist = collections.Counter(n for n, _ in links)
    print(f"每实体关联数: 最多 {max(dist.values())} 最少 {min(dist.values())}")
    print(f"分布: {dict(collections.Counter('1' if v == 1 else ('2-5' if v <= 5 else '6+') for v in dist.values()))}")

    if args.dry_run or not args.remote:
        print("\n[dry-run] 未写入。确认无误后加 --remote。")
        return 0

    # ── 写实体 ──
    print("\n=== 写 entities ===")
    BATCH = 50  # 5 列 × 50 = 250 变量 —— ⚠️ 超了 D1 的 100 上限,要用 20
    BATCH = 20
    total = 0
    for start in range(0, len(entities), BATCH):
        batch = entities[start:start + BATCH]
        groups = []
        n = 0
        for _ in batch:
            n += 5
            groups.append("(" + ", ".join(f"?{i}" for i in range(n - 4, n + 1)) + ")")
        sql = ("INSERT OR REPLACE INTO entities "
               "(entity_id, name, type, description, doc_id) VALUES " + ", ".join(groups))
        flat = [v for e in batch for v in
                [e["entity_id"], e["name"], e["type"], e["description"], e["doc_id"]]]
        d1(token, sql, flat)
        total += len(batch)
        print(f"  [{total}/{len(entities)}] ✅")

    # ── 写关联 ──
    print("\n=== 写 entity_articles ===")
    BATCH2 = 50  # 2 列 × 50 = 100 变量 —— 正好卡上限
    total = 0
    for start in range(0, len(links), BATCH2):
        batch = links[start:start + BATCH2]
        groups = []
        n = 0
        for _ in batch:
            n += 2
            groups.append(f"(?{n-1}, ?{n})")
        sql = ("INSERT OR REPLACE INTO entity_articles (entity_id, article_id) VALUES "
               + ", ".join(groups))
        flat = [v for pair in batch for v in pair]
        d1(token, sql, flat)
        total += len(batch)
        print(f"  [{total}/{len(links)}] ✅")

    # ── 写别名 ──
    print("\n=== 写 entity_aliases ===")
    # 清掉本脚本管的别名(别名表是本脚本独占的)
    d1(token, "DELETE FROM entity_aliases")
    BATCH3 = 33  # 3 列 × 33 = 99 变量 ≤ 100
    total = 0
    for start in range(0, len(aliases), BATCH3):
        batch = aliases[start:start + BATCH3]
        groups = []
        n = 0
        for _ in batch:
            n += 3
            groups.append("(" + ", ".join(f"?{i}" for i in range(n - 2, n + 1)) + ")")
        sql = ("INSERT OR REPLACE INTO entity_aliases (alias, entity_id, alias_kind) VALUES "
               + ", ".join(groups))
        flat = [v for a in batch for v in a]
        d1(token, sql, flat)
        total += len(batch)
        print(f"  [{total}/{len(aliases)}] ✅")

    # ── 校验 ──
    print("\n=== 校验 ===")
    print(f"  entities 总数        : {count_of(d1(token, 'SELECT COUNT(*) AS c FROM entities'))}")
    print(f"  SUBSTANCE 类型实体   : {count_of(d1(token, 'SELECT COUNT(*) AS c FROM entities WHERE type=?1', ['SUBSTANCE']))}")
    print(f"  entity_aliases 总数  : {count_of(d1(token, 'SELECT COUNT(*) AS c FROM entity_aliases'))}")
    print(f"  entity_articles 总数 : {count_of(d1(token, 'SELECT COUNT(*) AS c FROM entity_articles'))}")
    orphan = count_of(d1(token, """
        SELECT COUNT(*) AS c FROM entity_articles ea
        LEFT JOIN entities e ON e.entity_id = ea.entity_id
        WHERE e.entity_id IS NULL"""))
    dangling = count_of(d1(token, """
        SELECT COUNT(*) AS c FROM entity_articles ea
        LEFT JOIN articles a ON a.article_id = ea.article_id
        WHERE a.article_id IS NULL"""))
    alias_orphan = count_of(d1(token, """
        SELECT COUNT(*) AS c FROM entity_aliases a
        LEFT JOIN entities e ON e.entity_id = a.entity_id
        WHERE e.entity_id IS NULL"""))
    print(f"  孤儿关联             : {orphan} {'✅' if orphan == 0 else '❌'}")
    print(f"  悬空关联             : {dangling} {'✅' if dangling == 0 else '❌'}")
    print(f"  孤儿别名             : {alias_orphan} {'✅' if alias_orphan == 0 else '❌'}")
    if orphan or dangling or alias_orphan:
        raise SystemExit("[FAIL] 存在孤儿/悬空引用")
    print("\n[OK] 物质实体与关联写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
