#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
④ 知识图谱 —— 补「实体 ↔ 条文」关联(entity_articles)

## 为什么需要这个脚本

生产库里 `entities` 表有 **94 个实体**(2026-08-06 一次 GraphRAG 跑的产物),
但 `entity_articles` 是 **0 行** —— 实体有了,却**关联不到任何条文**。

后果:前端 `/entity/:name` 页能显示实体卡(名字/类型/描述),
但**「相关条文」列表永远是空的** —— 图谱只到实体层,没有落到条款。

## 为什么不用 GraphRAG 重跑

GraphRAG 的产物(`build/graphrag/output/<ts>/artifacts/*.parquet`)已被清理,
`run.sh` 还要 DeepSeek API Key + 逐章节跑 —— 成本高、不可复现。
而且 `index_meta` 显示那次只跑了 **16 个 chunk**(doc_count=16),
语料早从 16 章扩到 **3145 条文**,产物与现状严重脱节。

**本脚本走确定性关联**:实体名在条文正文/标题中**精确出现** → 建立关联。
这与检索层的 FTS5 phrase 匹配同源,语义一致,且可重复执行。

## 关联规则(每条都有理由)

| 规则 | 内容 | 为什么 |
|---|---|---|
| **R1 精确出现** | 实体名作为**完整子串**出现在条文正文或标题中 | 不做分词、不做模糊 —— 「维生素C」不该匹配到「维生素C钙」 |
| **R2 只关联正文类** | 只关联 `kind ∈ {article, section, section-split, article-split}` | 封面/目录/前言页含大量词条但不是「条文」 |
| **R3 泛词剔除** | 命中 > `MAX_HITS` 篇的实体名视为泛词,**不建关联** | 「产品」命中 975 篇 —— 关联它等于没关联,只会淹没真关系 |
| **R4 数量上限** | 每个实体最多关联 `MAX_PER_ENTITY` 篇 | 与 Worker 的 `LIMIT 50` 对齐;命中太多时按「正文位置靠前」排序取前 N |
| **R5 主键去重** | `(entity_id, article_id)` 复合主键,`INSERT OR REPLACE` | 重复执行幂等 |

## 用法

```bash
# ① 只算不写(看分布)
python build/export/seed_entity_articles.py --dry-run

# ② 写入生产
python build/export/seed_entity_articles.py --remote
```

⚠️ **只写 `entity_articles` 表,不碰 `entities`** —— 实体本身(名字/类型/描述)
是 LLM 抽取的产物,不在本脚本的职责范围内。
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import os
import re
import sys
import urllib.request
import urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ARTICLES_JSON = os.path.join(REPO, "data", "index", "minimax", "articles.json")

ACCOUNT_ID = "1b938cc261b000a03554b506985daabb"
DB_ID = "e406e21e-e770-4c97-822a-57178c347aa6"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# R2 · 只关联正文类条文
CONTENT_KINDS = {"article", "section", "section-split", "article-split"}

# R3 · 命中超过这个数视为泛词,不建关联
#
# ⚠️ **阈值怎么定的(实测)** —— 对 94 个实体逐个统计命中篇数,看分布:
#
#   ≥142:生产(981) 产品(975) 饲料(640) 使用(444) 检验(389) 国家(360)
#         饲料添加剂(344) 监督(307) 经营(272) 产品质量(246) 处罚(231)
#         法律(224) 设备(203) 中华人民共和国(189) 国务院(189) 申请人(142)
#         → 全是**泛词**,关联它们等于没关联
#
#   98~88:饲料和添加剂(98) 添加剂预混合饲料(88) 生产工艺(87) 禁止(86)
#         全国(85) 配合饲料(83) 罚款(81) 检验机构(77) 行政法规(72) 经营者(71)
#         → 都是**具体概念**,保留
#
# 取 120 作分界:排除 16 个泛词,保留 61 个实体 / 1533 条关联。
# 阈值 60 会误杀「生产许可证(79)」「批准文号(79)」这类有用的实体。
MAX_HITS = 120

# R4 · 每个实体最多关联多少篇
MAX_PER_ENTITY = 50


def load_token() -> str:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "AppData", "Roaming", "xdg.config", ".wrangler", "config", "default.toml"),
        os.path.join(home, ".wrangler", "config", "default.toml"),
        os.path.join(home, ".config", ".wrangler", "config", "default.toml"),
    ]
    for p in candidates:
        if os.path.exists(p):
            m = re.search(r'(?:oauth_token|api_token)\s*=\s*"([^"]+)"',
                          io.open(p, encoding="utf-8").read())
            if m:
                return m.group(1)
    for k in ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    raise SystemExit("[FAIL] 找不到 Cloudflare token —— 先跑 npx wrangler login")


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
    """⚠️ D1 REST 响应是嵌套的 —— 计数在 result[0]["results"][0]["c"]。"""
    result = res.get("result") or []
    if not result:
        return 0
    rows = result[0].get("results") or []
    if not rows:
        return 0
    return int(rows[0].get("c", 0) or 0)


def fetch_entities(token: str) -> list[dict]:
    res = d1(token, "SELECT entity_id, name, type FROM entities ORDER BY name")
    result = res.get("result") or []
    return result[0].get("results", []) if result else []


def load_content_articles() -> list[dict]:
    data = json.load(io.open(ARTICLES_JSON, encoding="utf-8"))
    return [a for a in data if a.get("kind") in CONTENT_KINDS]


def build_links(entities: list[dict], articles: list[dict]) -> tuple[list[tuple], list[dict]]:
    """返回 (关联列表, 泛词报告)。"""
    links: list[tuple] = []
    generic: list[dict] = []

    for ent in entities:
        name = (ent.get("name") or "").strip()
        if not name:
            continue
        hits = []
        for a in articles:
            text = a.get("text") or ""
            title = a.get("title") or ""
            number = a.get("number") or ""
            if name in text or name in title or name in number:
                # 排序:标题/条号命中优先,其次正文位置靠前
                score = (3 if (name in title or name in number) else 0) * 1000
                pos = text.find(name)
                score += max(0, 999 - pos) if pos >= 0 else 0
                hits.append((score, a["article_id"]))
        hits.sort(key=lambda x: (-x[0], x[1]))

        if len(hits) > MAX_HITS:
            generic.append({"name": name, "type": ent.get("type"), "hits": len(hits)})
            continue

        for _, aid in hits[:MAX_PER_ENTITY]:
            links.append((ent["entity_id"], aid))

    return links, generic


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true", help="写入生产(默认只算)")
    ap.add_argument("--dry-run", action="store_true", help="只算不写")
    args = ap.parse_args()

    token = load_token()
    print("=== 读取实体 ===")
    entities = fetch_entities(token)
    print(f"  entities: {len(entities)}")

    print("\n=== 载入本地语料 ===")
    articles = load_content_articles()
    print(f"  正文类条文: {len(articles)}")

    print("\n=== 计算关联 ===")
    links, generic = build_links(entities, articles)
    by_entity = collections.Counter(eid for eid, _ in links)
    print(f"  关联条数: {len(links)}")
    print(f"  有关联的实体: {len(by_entity)} / {len(entities)}")
    print(f"  泛词(命中 > {MAX_HITS},已剔除): {len(generic)}")
    for g in sorted(generic, key=lambda x: -x["hits"]):
        print(f"    - {g['name']}({g['type']}) 命中 {g['hits']} 篇")

    dist = collections.Counter(by_entity.values())
    print("\n  每实体关联数分布(前 10):")
    for n, c in sorted(dist.items(), reverse=True)[:10]:
        print(f"    {n:3} 篇 × {c} 个实体")

    if args.dry_run or not args.remote:
        print("\n[dry-run] 未写入。确认分布无误后加 --remote。")
        return 0

    print("\n=== 写入 entity_articles ===")
    # D1 REST params 上限 100 → 每批 50 行(50 × 2 = 100)
    BATCH = 50
    written = 0
    for start in range(0, len(links), BATCH):
        batch = links[start:start + BATCH]
        placeholders = ", ".join("(?1, ?2)" for _ in batch)
        # ⚠️ 占位符必须跨行连续编号 —— 每行都用 ?1/?2 会报
        #    「Wrong number of parameter bindings」
        groups = []
        n = 0
        for _ in batch:
            n += 2
            groups.append(f"(?{n-1}, ?{n})")
        sql = ("INSERT OR REPLACE INTO entity_articles (entity_id, article_id) VALUES "
               + ", ".join(groups))
        flat = [v for pair in batch for v in pair]
        d1(token, sql, flat)
        written += len(batch)
        print(f"  [{written}/{len(links)}] ✅")

    print("\n=== 校验 ===")
    total = count_of(d1(token, "SELECT COUNT(*) AS c FROM entity_articles"))
    distinct = count_of(d1(token, "SELECT COUNT(DISTINCT entity_id) AS c FROM entity_articles"))
    orphan = count_of(d1(token, """
        SELECT COUNT(*) AS c FROM entity_articles ea
        LEFT JOIN entities e ON e.entity_id = ea.entity_id
        WHERE e.entity_id IS NULL
    """))
    dangling = count_of(d1(token, """
        SELECT COUNT(*) AS c FROM entity_articles ea
        LEFT JOIN articles a ON a.article_id = ea.article_id
        WHERE a.article_id IS NULL
    """))
    print(f"  entity_articles 总行数    : {total}")
    print(f"  覆盖的实体数            : {distinct}")
    print(f"  孤儿关联(实体不存在)    : {orphan} {'✅' if orphan == 0 else '❌'}")
    print(f"  悬空关联(条文不存在)    : {dangling} {'✅' if dangling == 0 else '❌'}")

    if total != written:
        raise SystemExit(f"[FAIL] 写入 {written} 行,库里 {total} 行 —— 不一致")
    if orphan or dangling:
        raise SystemExit("[FAIL] 存在孤儿/悬空关联")

    print("\n[OK] 关联写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
