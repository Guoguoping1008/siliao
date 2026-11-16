#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比对生产 D1 与本地新语料,算出**精确差集**,并把差集灌回去。

## 为什么不能直接用 push_d1_bodies.py

那个脚本是「只 INSERT 新条文,已存在的跳过」(断点续灌设计)。
但本次是**覆盖**:GB 10648 的 31 条已有条文**正文变了**
(修了 6 处原文错误 + 改了标题结构),光跳过等于旧错字还在生产上。

所以这里要三件事:
  1. 新增的条文 -> INSERT
  2. 正文变了的条文 -> UPDATE body/title/number
  3. 语料里没有的条文 -> 报告(不自动删 —— 删除是不可逆操作,必须人工确认)

## 为什么不用 wrangler d1 execute --file

  - wrangler 4.127+ 对「schema 变了」的库报 D1_RESET_DO,**会清空远端表**
  - 正文含真实换行,拼进 SQL 字面量会踩 SQLite 限制
  - D1 raw API 支持 bound params,值不进 SQL 文本

## 用法

  python build/export/sync_d1_corpus.py --check     # 只算差集,不写
  python build/export/sync_d1_corpus.py --apply      # 写(先跑 --check 确认)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SCHEMA = ROOT / "query/worker/schema.sql"
SEED = ROOT / "build/export/seed.sql"

ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "1b938cc261b000a03554b506985daabb")
DB_ID = os.environ.get("CLOUDFLARE_D1_ID", "e406e21e-e770-4c97-822a-57178c347aa6")
API = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/raw"

MAX_VARS = 100          # D1 raw API 变量上限
COLS = 8
BATCH = MAX_VARS // COLS


def wrangler_token() -> str:
    cfg = Path.home() / ".wrangler" / "config" / "default.toml"
    if not cfg.exists():
        cfg = Path(os.environ.get("WRANGLER_CONFIG", "")) if os.environ.get("WRANGLER_CONFIG") else cfg
    for p in (
        Path.home() / ".wrangler" / "config" / "default.toml",
        Path.home() / ".config" / ".wrangler" / "config" / "default.toml",
        Path(os.environ.get("APPDATA", "")) / "xdg.config" / ".wrangler" / "config" / "default.toml",
    ):
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("oauth_token"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("找不到 wrangler OAuth token")


def raw(sql: str, params: list | None = None, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"sql": sql, "params": params or []}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {wrangler_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read()[:600].decode("utf-8", "replace")
        return {"http_error": e.code, "body": body}


def query(sql: str, params: list | None = None) -> list[tuple]:
    """D1 raw API 的响应是嵌套的: result[0].results.rows。

    实测返回形状:
      {"result": [{"results": {"columns": [...], "rows": [[...]]}, "success": true}], "success": true}
    注意 rows 里每行是**数组**,不是 dict。
    """
    r = raw(sql, params)
    if not r.get("success"):
        raise SystemExit(f"query failed: {str(r)[:500]}")
    try:
        rows = r["result"][0]["results"]["rows"]
    except (KeyError, IndexError, TypeError):
        raise SystemExit(f"unexpected response shape: {str(r)[:500]}")
    return [tuple(row) for row in rows]


def load_local_chapters() -> dict[str, dict]:
    """读本地 chapters。

    ⚠️ articles.chapter_id 有外键指向 chapters.chapter_id,
    articles.doc_id 有外键指向 documents.doc_id。
    所以灌库顺序必须是: documents → chapters → articles。
    (实测:先灌 articles 会报 SQLITE_CONSTRAINT_FOREIGNKEY)

    ⚠️ 生产 D1 的 chapters 表比本地 schema.sql **多一列 body**
    (实测:CREATE TABLE chapters 有 `body TEXT`)。
    所以列集合必须**按生产实际列**来取,不能照抄本地 schema。
    """
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    cols = [r[1] for r in con.execute("PRAGMA table_info(chapters)").fetchall()]
    rows = con.execute(
        "SELECT " + ", ".join(cols) + " FROM chapters"
    ).fetchall()
    return {r[0]: dict(zip(cols, r)) for r in rows}


def load_local_fts() -> dict[str, dict]:
    """读本地 articles_fts。

    FTS 的 text 不是正文,是**上下文增强版**:
        {chapter_number} {chapter_title} {doc_title} {正文(换行替换成空格)}

    见 ingest_minimax.py:826-834。
    ⚠️ 灌 FTS 必须用这个增强版,不能用 articles.body ——
       少了章节名/文档名注入,搜「总则」「饲料标签」就召回不到。
    """
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    rows = con.execute(
        "SELECT article_id, chapter_id, doc_id, number, title, text FROM articles_fts"
    ).fetchall()
    return {
        r[0]: {
            "article_id": r[0], "chapter_id": r[1], "doc_id": r[2],
            "number": r[3], "title": r[4], "text": r[5],
        }
        for r in rows
    }


def remote_columns(table: str) -> list[str]:
    """读生产 D1 该表的实际列(不含 sqlite 内部列)。"""
    rows = query(f"PRAGMA table_info({table})")
    return [r[1] for r in rows]


def load_local_documents() -> dict[str, dict]:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    cols = [r[1] for r in con.execute("PRAGMA table_info(documents)").fetchall()]
    rows = con.execute(
        "SELECT " + ", ".join(cols) + " FROM documents"
    ).fetchall()
    return {r[0]: dict(zip(cols, r)) for r in rows}


def load_local_articles() -> dict[str, dict]:
    """读本地新语料。

    ⚠️ **不能直接用 seed.sql 里的 body** ——
    ingest_minimax.py 写 seed.sql 时会把 `\` 转义成 `\\`
    (SQL 字面量转义,见 ingest_minimax.py:731)。
    所以从 seed.sql 读出来的 body 里是 `\\\\frac`,
    而生产 D1 里是真正的单反斜杠 `\\frac`。
    直接比会把 2 条**没改过**的条文误判成「正文变更」。

    正确做法:body 从 seed.sql 取(转义态)→ 用同样的规则反转义回来,
    再和生产比。反转义规则: `\\` -> `\`、`''` -> `'`。
    """
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executescript(SEED.read_text(encoding="utf-8"))
    rows = con.execute(
        "SELECT article_id, chapter_id, doc_id, number, title, r2_object_key, body, sort_order "
        "FROM articles"
    ).fetchall()
    out = {}
    for r in rows:
        body = r[6] or ""
        # 反转义(与 ingest_minimax.py:731 的 sql_escape 对称)
        body = body.replace("\\\\", "\x00").replace("\\'", "'").replace("\x00", "\\")
        out[r[0]] = {
            "article_id": r[0], "chapter_id": r[1], "doc_id": r[2], "number": r[3],
            "title": r[4], "r2_object_key": r[5], "body": body, "sort_order": r[7],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只算差集,不写")
    ap.add_argument("--apply", action="store_true", help="写生产")
    ap.add_argument("--batch", type=int, default=BATCH)
    args = ap.parse_args()

    if not args.check and not args.apply:
        print("[ERROR] 必须指定 --check 或 --apply")
        return 2

    local = load_local_articles()
    local_ch = load_local_chapters()
    local_doc = load_local_documents()
    local_fts = load_local_fts()
    print(
        f"[local] {len(local)} articles · {len(local_ch)} chapters · "
        f"{len(local_doc)} documents · {len(local_fts)} fts"
    )

    rows = query(
        "SELECT article_id, number, title, body FROM articles"
    )
    remote = {r[0]: {"number": r[1] or "", "title": r[2] or "", "body": r[3] or ""} for r in rows}
    print(f"[remote] {len(remote)} articles")

    rem_ch = {r[0] for r in query("SELECT chapter_id FROM chapters")}
    rem_doc = {r[0] for r in query("SELECT doc_id FROM documents")}
    rem_fts = {r[0] for r in query("SELECT article_id FROM articles_fts")}

    to_insert = [a for aid, a in local.items() if aid not in remote]
    to_update = []
    for aid, a in local.items():
        if aid not in remote:
            continue
        r = remote[aid]
        if a["body"] != r["body"] or a["title"] != r["title"] or a["number"] != r["number"]:
            to_update.append(a)
    orphans = [aid for aid in remote if aid not in local]

    ch_to_insert = [c for cid, c in local_ch.items() if cid not in rem_ch]
    doc_to_insert = [d for did, d in local_doc.items() if did not in rem_doc]

    # FTS 差集:新增的 + **内容变了**的。
    #
    # ⚠️ 必须比**内容**,不能只比存在与否 ——
    #    article_id 会被复用!实测:
    #      旧 p001 = 修改单全文      → 新 p001 = 封面(21 字)
    #      旧 a030 = 5.11 行政许可证  → 新 a030 = 5.4.1 原料组成
    #    这两条 id 一直「存在」,只查存在性就漏掉了 —— 结果生产 FTS 里
    #    留着旧文(「醒目字体」「许可证证明文件」这些错字),
    #    搜「本品含有允许添加」还能命中修改单里的旧错字。
    fts_to_insert = [f for aid, f in local_fts.items() if aid not in rem_fts]
    fts_to_update = []
    if rem_fts:
        # 一次拉全量生产 FTS 的 (article_id, title, text) 做比对
        remote_fts = {
            r[0]: {"title": r[1] or "", "text": r[2] or ""}
            for r in query("SELECT article_id, title, text FROM articles_fts")
        }
        for aid, f in local_fts.items():
            if aid not in remote_fts:
                continue
            rf = remote_fts[aid]
            if rf["text"] != f["text"] or rf["title"] != f["title"]:
                fts_to_update.append(f)

    print()
    print(
        f"[diff] 新增 {len(to_insert)} · 正文变更 {len(to_update)} · 生产有语料无 {len(orphans)}"
    )
    print(
        f"       补章节 {len(ch_to_insert)} · 补文档 {len(doc_to_insert)}"
        f"（FK 顺序: documents → chapters → articles）"
    )
    print(
        f"       FTS: 新增 {len(fts_to_insert)} · 变更 {len(fts_to_update)}"
        f"（生产现有 {len(rem_fts)}）"
    )
    for c in ch_to_insert:
        print(f"       +chapter {c}")
    if to_insert:
        print(f"       +{to_insert[0]['article_id']}")
        if len(to_insert) > 1:
            print(f"       +{to_insert[-1]['article_id']}")
    for a in to_update[:10]:
        print(f"       ~{a['article_id'][-46:]}  body {len(remote[a['article_id']]['body'])} -> {len(a['body'])}")
    if len(to_update) > 10:
        print(f"       ... 还有 {len(to_update)-10} 条")
    if orphans:
        print(f"       ! 生产有语料无: {orphans[:5]}{' ...' if len(orphans)>5 else ''}")
        print("         (不自动删 —— 删除不可逆,需人工确认)")

    if args.check:
        print("\n[CHECK] 未写入")
        return 0

    # ---- 写:顺序必须是 documents → chapters → articles(FK 约束) ----
    t0 = time.time()

    # 1) documents
    if doc_to_insert:
        rcols = remote_columns("documents")
        for d in doc_to_insert:
            cols = [c for c in rcols if c in d]
            vals = [d[c] for c in cols]
            ph = ", ".join(f"?{i+1}" for i in range(len(cols)))
            sql = f"INSERT INTO documents({', '.join(cols)}) VALUES ({ph})"
            r = raw(sql, vals)
            if not r.get("success"):
                print(f"[d1] INSERT documents 失败 {d.get('doc_id')}: {str(r)[:300]}")
                return 1
        print(f"[d1] INSERT documents {len(doc_to_insert)}  {time.time()-t0:.0f}s")

    # 2) chapters
    if ch_to_insert:
        rcols = remote_columns("chapters")
        for c in ch_to_insert:
            cols = [k for k in rcols if k in c]
            vals = [c[k] for k in cols]
            ph = ", ".join(f"?{i+1}" for i in range(len(cols)))
            sql = f"INSERT INTO chapters({', '.join(cols)}) VALUES ({ph})"
            r = raw(sql, vals)
            if not r.get("success"):
                print(f"[d1] INSERT chapters 失败 {c.get('chapter_id')}: {str(r)[:300]}")
                return 1
        print(f"[d1] INSERT chapters {len(ch_to_insert)}  {time.time()-t0:.0f}s")

    # 3) articles:先 UPDATE(改正文),再 INSERT(加新条文)
    done = 0
    for a in to_update:
        sql = (
            "UPDATE articles SET number=?, title=?, body=?, chapter_id=?, doc_id=?, "
            "r2_object_key=?, sort_order=? WHERE article_id=?"
        )
        params = [
            a["number"] or "", a["title"] or "", a["body"] or "",
            a["chapter_id"], a["doc_id"], a["r2_object_key"] or (a["article_id"] + ".md"),
            a["sort_order"], a["article_id"],
        ]
        r = raw(sql, params)
        if not r.get("success"):
            print(f"[d1] UPDATE 失败 {a['article_id']}: {str(r)[:300]}")
            return 1
        done += 1
        if done % 20 == 0 or done == len(to_update):
            print(f"[d1] UPDATE {done}/{len(to_update)}  {time.time()-t0:.0f}s")

    def sql_for(n: int) -> str:
        ph = ", ".join(
            "(" + ", ".join(f"?{i*COLS+j+1}" for j in range(COLS)) + ")"
            for i in range(n)
        )
        return (
            "INSERT INTO articles(article_id, chapter_id, doc_id, number, title,"
            " r2_object_key, body, sort_order) VALUES " + ph
        )

    done = 0
    for i in range(0, len(to_insert), args.batch):
        chunk = to_insert[i : i + args.batch]
        params = []
        for a in chunk:
            params.extend([
                a["article_id"], a["chapter_id"], a["doc_id"], a["number"] or "",
                a["title"] or "", a["r2_object_key"] or (a["article_id"] + ".md"),
                a["body"] or "", a["sort_order"],
            ])
        r = raw(sql_for(len(chunk)), params)
        if not r.get("success"):
            print(f"[d1] INSERT 失败: {str(r)[:300]}")
            return 1
        done += len(chunk)
        print(f"[d1] INSERT {done}/{len(to_insert)}  {time.time()-t0:.0f}s")

    # 4) articles_fts:必须**删了重插**,不能 UPDATE ——
    #    FTS5 虚拟表没有普通 UPDATE 语义(改内容要走 delete+insert),
    #    而且生产没有触发器(实测 sqlite_master type='trigger' 为空),
    #    所以 articles 改了正文,FTS 不会自动跟着变 —— 得手动重灌。
    if fts_to_update or fts_to_insert:
        fts_all = fts_to_update + fts_to_insert
        for f in fts_all:
            r = raw("DELETE FROM articles_fts WHERE article_id = ?", [f["article_id"]])
            if not r.get("success"):
                print(f"[d1] FTS DELETE 失败 {f['article_id']}: {str(r)[:300]}")
                return 1
        print(f"[d1] FTS DELETE {len(fts_all)}  {time.time()-t0:.0f}s")

        def fts_sql_for(n: int) -> str:
            ph = ", ".join(
                "(" + ", ".join(f"?{i*6+j+1}" for j in range(6)) + ")"
                for i in range(n)
            )
            return (
                "INSERT INTO articles_fts(article_id, chapter_id, doc_id, number,"
                " title, text) VALUES " + ph
            )

        done = 0
        for i in range(0, len(fts_all), args.batch):
            chunk = fts_all[i : i + args.batch]
            params = []
            for f in chunk:
                params.extend([
                    f["article_id"], f["chapter_id"], f["doc_id"], f["number"] or "",
                    f["title"] or "", f["text"] or "",
                ])
            r = raw(fts_sql_for(len(chunk)), params)
            if not r.get("success"):
                print(f"[d1] FTS INSERT 失败: {str(r)[:300]}")
                return 1
            done += len(chunk)
            print(f"[d1] FTS INSERT {done}/{len(fts_all)}  {time.time()-t0:.0f}s")

    # ---- 校验 ----
    rows = query(
        "SELECT (SELECT COUNT(*) FROM articles) a, (SELECT COUNT(*) FROM articles_fts) f"
    )
    print(f"\n[d1] 写入后: articles={rows[0][0]} fts={rows[0][1]}")
    print(f"[d1] 耗时 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
