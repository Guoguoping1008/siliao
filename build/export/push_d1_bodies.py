#!/usr/bin/env python3
"""
用 D1 REST API 的 bound params 灌数据(不拼 SQL 字符串)。

为什么不用 `wrangler d1 execute --file seed.sql`:
  1. wrangler 4.127+ 对「schema 变了」的库会报 `D1_RESET_DO` —— 它想走迁移流程,
     不肯直接灌。
  2. 正文(markdown)含真实换行, 拼进 SQL 字符串字面量会踩 SQLite 的限制:
       - 字符串字面量不能跨行 → 语法错
       - 也不能靠 `\\n` 转义 → 存进去是字面的反斜杠+n
       - 用 `|| char(10) ||` 拼接 → 表达式树深度超 100(SQLITE_TOOBIG)
  3. D1 raw API 支持 bound params: 值不进 SQL 文本, 换行/引号/反斜杠都原样传,
     也绕开表达式深度限制。

用法:
    python build/export/push_d1_bodies.py                 # 灌 body + sort_order
    python build/export/push_d1_bodies.py --check          # 只查当前状态
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "1b938cc261b000a03554b506985daabb")
DB_ID = os.environ.get("CLOUDFLARE_D1_ID", "e406e21e-e770-4c97-822a-57178c347aa6")
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/raw"
# D1 raw API 的参数上限是 **100 个变量**(SQLITE_MAX_VARIABLE_NUMBER=100),
# 不是 SQLite 默认的 999/32766。每行 8 个参数 → 最多 12 行/请求。
MAX_VARS = 100
COLS = 8
BATCH = MAX_VARS // COLS  # = 12


def wrangler_token() -> str:
    """从 wrangler 的 OAuth 配置里拿 token。

    ⚠️ 不走 `wrangler d1 execute` —— 那条路会撞 D1_RESET_DO。
    """
    cfg = Path(
        os.environ.get("APPDATA", "")
    ) / "xdg.config" / ".wrangler" / "config" / "default.toml"
    text = cfg.read_text(encoding="utf-8")
    marker = 'oauth_token = "'
    if marker not in text:
        raise SystemExit(f"找不到 wrangler token: {cfg}")
    return text.split(marker)[1].split('"')[0]


def make_opener():
    """系统代理(国内访问 Cloudflare API 需要)。"""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


OPENER = make_opener()


def raw(sql: str, params: list | None = None, timeout: int = 180, retries: int = 4) -> dict:
    """调 D1 raw API(带重试)。

    ⚠️ 走系统代理时偶发 `SSL: UNEXPECTED_EOF_WHILE_READING` —— 代理连接被
       复用后掐断。这是网络抖动不是请求错误, 重试即可。
    """
    body: dict = {"sql": sql}
    if params:
        body["params"] = params
    payload = json.dumps(body).encode("utf-8")
    last: dict = {}
    for attempt in range(retries):
        req = urllib.request.Request(
            API,
            data=payload,
            headers={
                "Authorization": f"Bearer {wrangler_token()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with OPENER.open(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # 4xx 是请求本身的问题(参数错/约束冲突), 重试没意义
            return {"http_error": e.code, "body": e.read()[:400].decode("utf-8", "replace")}
        except Exception as e:  # noqa: BLE001
            last = {"err": str(e)}
            time.sleep(1.5 * (attempt + 1))
    return last


def ok(d: dict) -> bool:
    """D1 raw API 成功判定。

    响应形态:
      {"result": [{"results": {"success": true, "rows": [...]}, "success": true, ...}], ...}
    注意 `success` 出现在**两层** —— 顶层 result 数组的每一项里
    既有 `x["success"]`, 也有 `x["results"]["success"]`。
    """
    if d.get("http_error") or d.get("err"):
        return False
    res = d.get("result")
    if not res:
        return False
    for x in res:
        if x.get("success") is False:
            return False
        inner = x.get("results")
        if isinstance(inner, dict) and inner.get("success") is False:
            return False
    return True


def query(sql: str) -> list:
    d = raw(sql)
    if not ok(d):
        raise SystemExit(f"查询失败: {str(d)[:300]}")
    return d["result"][0]["results"]["rows"]


def load_r2_keys() -> dict[str, str]:
    """从 seed.sql 提取 article_id → r2_object_key。

    articles.json 里没有 r2_object_key(那是 ingest 写 SQL 时才拼的),
    但 articles.r2_object_key 是 NOT NULL, 灌库必须带上。
    """
    import re

    seed = (ROOT / "build" / "export" / "seed.sql").read_text(encoding="utf-8")
    pat = re.compile(
        r"INSERT INTO articles\(article_id, chapter_id, doc_id, number, title,"
        r" r2_object_key, body, sort_order\) VALUES"
        r"\('((?:[^']|'')*)', '(?:[^']|'')*', '(?:[^']|'')*', '(?:[^']|'')*',"
        r" '(?:[^']|'')*', '((?:[^']|'')*)'"
    )
    out: dict[str, str] = {}
    for m in pat.finditer(seed):
        aid = m.group(1).replace("''", "'")
        key = m.group(2).replace("''", "'")
        out[aid] = key
    return out


def load_articles() -> list[dict]:
    """从索引产物读条文(含正文与章内顺序)。"""
    p = ROOT / "data" / "index" / "minimax" / "articles.json"
    arts = json.loads(p.read_text(encoding="utf-8"))
    # 章内顺序: articles.json 是 ingest 按原文顺序写的, 文件下标即原文序。
    # ⚠️ 不能靠 article_id 排序 —— 字典序会打乱原文顺序
    #    (实测 95/529 个章节的条文顺序与 ingest 写的章节 md 不一致)。
    r2 = load_r2_keys()
    for i, a in enumerate(arts):
        a["_ord"] = i
        a["r2_object_key"] = r2.get(a["article_id"], a["article_id"] + ".md")
    missing = sum(1 for a in arts if a["article_id"] not in r2)
    if missing:
        print(f"[d1] ⚠ {missing} 条没匹配到 r2_object_key(用占位)")
    return arts


def chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def local_db_path() -> Path:
    """本地 miniflare D1 的 sqlite 文件。

    wrangler dev 用的是 .wrangler/state/v3/d1/miniflare-D1DatabaseObject/ 下
    某个 hash 命名的 .sqlite —— hash 由 database_id 决定, 不直观。
    这里直接找出**含 articles 表**的那个。
    """
    d = ROOT / "query" / "worker" / ".wrangler" / "state" / "v3" / "d1" / "miniflare-D1DatabaseObject"
    cands = []
    for f in d.glob("*.sqlite"):
        if f.name == "metadata.sqlite":
            continue
        try:
            import sqlite3

            c = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True)
            n = c.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='articles'"
            ).fetchone()[0]
            c.close()
            if n:
                cands.append(f)
        except Exception:  # noqa: BLE001
            continue
    if not cands:
        raise SystemExit(f"找不到本地 D1: {d}")
    if len(cands) == 1:
        return cands[0]

    # ⚠️ 可能有多个本地 D1(database_id 改过 → miniflare 另建了一个)。
    #    必须挑**当前 wrangler.toml 的 database_id 对应的那个** ——
    #    挑错会导致「灌了但 dev server 读的是另一个库」。
    #
    #    认法: 当前库里 articles 的 chapter_id/doc_id 与最新语料一致,
    #    且它的 r2_object_key 带**当前**短前缀(d + sha1(doc_id)[:10])。
    #    简化判据: 取**最近修改**的那个(mtime 最大)。
    cands.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    newest = cands[0]
    print(f"[d1-local] 有 {len(cands)} 个本地 D1, 取最近修改的: {newest.name[:20]}…")
    for f in cands:
        try:
            import sqlite3

            c = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True)
            nb = c.execute(
                "SELECT COUNT(*) FROM articles WHERE body IS NOT NULL AND body!=''"
            ).fetchone()[0]
            c.close()
            print(f"[d1-local]   {f.name[:20]}… 带正文 {nb}")
        except Exception:  # noqa: BLE001
            pass
    return newest


def push_local() -> int:
    """灌本地 miniflare D1(直接写 sqlite 文件, 不走 API)。

    本地 D1 是普通 sqlite, 换行用参数绑定就天然安全, 没有那些 SQLite 限制。
    """
    import sqlite3

    f = local_db_path()
    print(f"[d1-local] {f.name}")
    arts = load_articles()
    con = sqlite3.connect(f)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(articles)")]
        for need in ("body", "sort_order"):
            if need not in cols:
                typ = "TEXT" if need == "body" else "INTEGER NOT NULL DEFAULT 0"
                con.execute(f"ALTER TABLE articles ADD COLUMN {need} {typ}")
                print(f"[d1-local] 加列 {need}")
        have = con.execute("SELECT COUNT(*) FROM articles WHERE body IS NOT NULL AND body!=''").fetchone()[0]
        print(f"[d1-local] 已有正文: {have}/{len(arts)}")
        if have >= len(arts):
            print("[d1-local] 无需重灌")
            return 0
        con.executemany(
            "UPDATE articles SET body=?, sort_order=? WHERE article_id=?",
            [(a.get("text") or "", a.get("_ord", 0), a["article_id"]) for a in arts],
        )
        con.commit()
        n, b = con.execute(
            "SELECT COUNT(*), SUM(LENGTH(body)) FROM articles WHERE body IS NOT NULL AND body!=''"
        ).fetchone()
        print(f"[d1-local] ✅ {n} 条带正文, 共 {b / 1024 / 1024:.2f} MB")
    finally:
        con.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只查当前状态")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--local", action="store_true", help="灌本地 miniflare D1")
    args = ap.parse_args()

    if args.local:
        return push_local()
    print(f"[d1] target: {DB_ID[:12]}…")

    # 当前状态
    rows = query(
        "SELECT (SELECT COUNT(*) FROM documents) d,"
        " (SELECT COUNT(*) FROM chapters) c,"
        " (SELECT COUNT(*) FROM articles) a,"
        " (SELECT COUNT(*) FROM articles_fts) f"
    )
    d, c, a, f = rows[0]
    print(f"[d1] 现状: documents={d} chapters={c} articles={a} fts={f}")

    if args.check:
        return 0

    arts = load_articles()
    print(f"[d1] 待灌正文: {len(arts)} 条")

    # 断点续灌: 已存在的跳过(重跑脚本不用从头来)
    if d > 0 or a > 0:
        existing = set()
        for row in query("SELECT article_id FROM articles"):
            existing.add(row[0])
        if existing:
            before = len(arts)
            arts = [x for x in arts if x["article_id"] not in existing]
            print(
                f"[d1] 断点续灌: 已有 {before - len(arts)} 条, 待灌 {len(arts)} 条"
            )
    if not arts:
        print("[d1] 无需灌入")
        return 0

    # 分批: 多行 INSERT, 全部值走 bound params。
    #
    # ⚠️ articles 表的 chapter_id / doc_id / number / title / r2_object_key
    #    都是 NOT NULL, 必须一起灌 —— 远端 D1 被 D1_RESET_DO 重置过, 表是空的。
    # 参数顺序: article_id, chapter_id, doc_id, number, title, r2_object_key, body, sort_order
    cols = COLS
    # ⚠️ 占位符个数必须**按实际批大小**生成 —— 模板固定 12 行时,
    #    最后一批只有 1 行会报 "Wrong number of parameter bindings"。
    def sql_for(n: int) -> str:
        ph = ", ".join(
            "(" + ", ".join(f"?{i * cols + j + 1}" for j in range(cols)) + ")"
            for i in range(n)
        )
        return (
            "INSERT INTO articles(article_id, chapter_id, doc_id, number, title,"
            " r2_object_key, body, sort_order) VALUES " + ph
        )

    t0 = time.time()
    done = 0
    batch_size = min(args.batch, MAX_VARS // cols)
    if batch_size < args.batch:
        print(f"[d1] 批大小 {args.batch} → {batch_size}({MAX_VARS} 变量上限 / {cols} 列)")
    for batch in chunked(arts, batch_size):
        params: list = []
        for art in batch:
            params.extend(
                [
                    art["article_id"],
                    art["chapter_id"],
                    art["doc_id"],
                    art.get("number") or "",
                    art.get("title") or "",
                    # r2_object_key: NOT NULL, 但正文已不走 R2 了,
                    # 留个占位(将来开 R2 可以再补)。
                    art.get("r2_object_key") or (art["article_id"] + ".md"),
                    art.get("text") or "",
                    art.get("_ord", 0),
                ]
            )
        r = raw(sql_for(len(batch)), params, timeout=300)
        if not ok(r):
            print(f"[d1] ❌ 批次失败(已完成 {done}): {str(r)[:300]}")
            return 1
        done += len(batch)
        if done % 500 == 0 or done == len(arts):
            print(f"[d1]   {done}/{len(arts)}  {time.time() - t0:.0f}s")

    # 校验
    rows = query(
        "SELECT COUNT(*) total,"
        " SUM(CASE WHEN body IS NOT NULL AND body != '' THEN 1 ELSE 0 END) with_body,"
        " SUM(LENGTH(body)) bytes FROM articles"
    )
    total, with_body, nbytes = rows[0]
    print(
        f"[d1] ✅ 完成: articles={total} 带正文={with_body} "
        f"正文总长={nbytes / 1024 / 1024:.2f} MB  用时 {time.time() - t0:.0f}s"
    )

    # 抽一条看换行是否正确
    rows = query(
        "SELECT article_id, substr(body, 1, 90) FROM articles "
        "WHERE body LIKE '%兽药注册工作程序%' LIMIT 1"
    )
    if rows:
        print(f"[d1] 样例: {rows[0][0][-40:]} → {rows[0][1]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
