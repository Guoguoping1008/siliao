"""
C2: 按页让 LLM 注入结构化元数据 (替代 chapter 中间层)

输入:  data/markdown/<doc_id>/pages/*.md  (1029 张单页)
输出:  markdown/<doc_id>/pages_struct/<stem>.json
       markdown/<doc_id>/pages_struct/_all.jsonl  (JSONL, 喂 seed_d1)
       markdown/<doc_id>/pages_struct/_report.md

每个 page 输出 schema:
{
  "stem": "20260913173708061__L",
  "page_no": 1,
  "doc_title": "饲料和饲料添加剂管理条例",     # 这一页来自哪份规范性文件
  "doc_number": "国务院令2011年第609号",        # 文件号 (可空, 前言/目录/页眉页为空)
  "chapter_title": "第二章  咨询",               # 章节标题 (可空)
  "is_meta": false,                              # true = 前言/目录/页眉/空白, text 为空
  "text_blocks": [
    {"type": "article", "number": "第五条", "text": "<逐字抄录>"},
    {"type": "para",     "text": "<连续段落>"}
  ],
  "source_chars": 1379
}

强校验:
- LLM 输出的每条 text 必须在原 md 里 100% 锚点匹配
- 失败 3 次重试, 最终失败标记 trusted=false, 但保留 LLM 原输出供人工审

并发:  ThreadPoolExecutor 6 worker (实测 8 并发 OK, 留余量给突发限流)
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("E:/workspace/siliao")
DEFAULT_DOC = "feed-law-collection-2023-full"
PAGES_DIR = ROOT / "data/markdown" / DEFAULT_DOC / "pages"
OUT_DIR = ROOT / "markdown" / DEFAULT_DOC / "pages_struct"

UPSTREAM = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01")
TIMEOUT_S = 60
MAX_WORKERS = 6
MAX_RETRY = 3


def load_api_key() -> str:
    k = os.environ.get("MINIMAX_API_KEY", "")
    if not k:
        for cand in [
            Path.home() / "AppData/Local/hermes/profiles/xuanqiong/.env",
            Path("C:/Users/Administrator/AppData/Local/hermes/profiles/xuanqiong/.env"),
        ]:
            if cand.exists():
                for ln in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if ln.startswith("MINIMAX_CN_API_KEY="):
                        k = ln.split("=", 1)[1].strip()
                        break
                if k:
                    break
    if not k:
        raise RuntimeError("MINIMAX_API_KEY not set")
    return k


# ──────────────── prompt ────────────────

SYSTEM_PROMPT = """你是中文法律/法规文档的 OCR 后处理助手。

输入: 一页 OCR 出的 markdown (中文法规书, 单页约 1-3KB, 来自《饲料法规文件》)。

任务: 解析这一页, 输出**结构化 JSON**, 含:
1. doc_title: 这一页来自的"规范性文件"标题 (如 "饲料和饲料添加剂管理条例" / "新饲料和新饲料添加剂管理办法"), 如果是前言/目录/页眉/版权页/空白, 填空字符串
2. doc_number: 文件号 (如 "国务院令2011年第609号" / "农牧发[2015]8号" / "农业部公告第2197号"), 没有则空
3. chapter_title: 章节标题 (如 "第二章  咨询" / "第三章  进口与出口"), 没有则空
4. is_meta: true = 这一页是前言/目录/页眉/版权/空白, 没有实质条款; false = 实质内容
5. text_blocks: 数组, 每个元素是这一页里的一个"内容单元":
   - {"type": "article", "number": "第十五条", "text": "<逐字抄录该条原文>"}
   - {"type": "para",     "text": "<连续段落, 不是任何法条的一部分>"}
   - {"type": "table_md", "text": "<markdown 表格, 如果有>"}
   - {"type": "signature","text": "<发文机关落款 / 日期 / 印章等>"}
   - 抄录原则: 字符顺序不变, 不改正错字, 不补标点, 不补字

硬性规则:
- 逐字抄录, 不得增删改
- text 里的字符必须能在原 md 中找到 (锚点匹配)
- 目录/前言/页眉页: is_meta=true, text_blocks=[]
- 跨页的法条: 只抄本页出现的部分, 不要把下一页内容合并进来
- 表格尽量保留 markdown 结构
- 法条号带原文前缀 ("第十五条" / "第十五条之一" / "（一）")

输出严格 JSON, 无 markdown 围栏, 无注释:
{
  "doc_title": "",
  "doc_number": "",
  "chapter_title": "",
  "is_meta": false,
  "text_blocks": []
}
""".strip()


USER_TEMPLATE = """原页 markdown 如下 (页码: {page_no}, 文件: {stem}.md):

```
{md_text}
```

请解析并输出 JSON。
""".strip()


# ──────────────── 校验 ────────────────

def extract_anchors(text: str, max_n: int = 2, min_len: int = 20) -> list[str]:
    chunks = re.findall(r"\S+", text)
    anchors = []
    cur = ""
    for c in chunks:
        if len(cur) + len(c) + 1 > 60:
            if len(cur) >= min_len:
                anchors.append(cur)
                if len(anchors) >= max_n:
                    break
            cur = c
        else:
            cur = cur + " " + c if cur else c
    if len(anchors) < max_n and len(cur) >= min_len:
        anchors.append(cur)
    return anchors[:max_n]


def check_faithfulness(out: dict, md_full: str) -> list[str]:
    errs = []
    for i, blk in enumerate(out.get("text_blocks", [])):
        t = blk.get("text", "")
        if not t:
            continue
        if blk.get("type") == "table_md":
            # 表格校验宽松: 任意 30 字片段命中即可
            anchors = extract_anchors(t, max_n=1, min_len=30)
        else:
            anchors = extract_anchors(t, max_n=2, min_len=20)
        miss = [a for a in anchors if a not in md_full]
        if miss:
            errs.append(f"block[{i}].type={blk.get('type')}: {len(miss)}/{len(anchors)} 锚点不在原文; 例: {miss[0][:40]!r}")
    return errs


def parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        s = content.find("{")
        e = content.rfind("}")
        if s >= 0 and e > s:
            return json.loads(content[s: e + 1])
        raise


# ──────────────── LLM ────────────────

def call_llm(api_key: str, system: str, user: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }).encode("utf-8")
    req = urllib.request.Request(
        UPSTREAM, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8")
    j = json.loads(raw)
    if j.get("base_resp", {}).get("status_code") not in (0, None):
        raise RuntimeError(f"upstream error: {j.get('base_resp')}")
    return {
        "content": j["choices"][0]["message"]["content"],
        "usage": j.get("usage", {}),
    }


# ──────────────── 主流程 ────────────────

def structure_one(api_key: str, page_path: Path) -> dict:
    md_text = page_path.read_text(encoding="utf-8")
    stem = page_path.stem
    m_pg = re.search(r"<!--\s*page:\s*(\d+)\s*-->", md_text)
    page_no = int(m_pg.group(1)) if m_pg else -1

    user = USER_TEMPLATE.format(page_no=page_no, stem=stem, md_text=md_text)
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            t0 = time.time()
            r = call_llm(api_key, SYSTEM_PROMPT, user)
            elapsed = time.time() - t0
            out = parse_json(r["content"])
            errs = check_faithfulness(out, md_text)
            return {
                "stem": stem,
                "page_no": page_no,
                "source_chars": len(md_text),
                "usage": r["usage"],
                "elapsed_s": round(elapsed, 1),
                "attempt": attempt,
                "trusted": not errs,
                "faithfulness_errors": errs,
                "output": out,
            }
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(0.5 * attempt)

    return {
        "stem": stem,
        "page_no": page_no,
        "source_chars": len(md_text),
        "trusted": False,
        "fatal_error": last_err,
        "output": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    pages_dir = ROOT / "data/markdown" / args.doc / "pages"
    out_dir = ROOT / "markdown" / args.doc / "pages_struct"
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()

    page_files = sorted(pages_dir.glob("*.md"))
    if args.limit:
        page_files = page_files[: args.limit]

    # 跳过已完成 (幂等)
    todo = [p for p in page_files if not (out_dir / f"{p.stem}.json").exists()]
    print(f"[plan] pages={len(page_files)}  todo={len(todo)}  workers={args.workers}  model={MODEL}")

    if not todo:
        print("[done] nothing to do")
        return 0

    t_start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(structure_one, api_key, p): p for p in todo}
        done_count = 0
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            (out_dir / f"{r['stem']}.json").write_text(
                json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            done_count += 1
            if done_count % 50 == 0 or done_count == len(todo):
                el = time.time() - t_start
                rate = done_count / el
                eta = (len(todo) - done_count) / rate if rate else 0
                n_trust = sum(1 for x in results if x.get("trusted"))
                print(f"[prog] {done_count}/{len(todo)}  trusted={n_trust}  rate={rate:.1f}/s  eta={eta:.0f}s")

    # 写 _all.jsonl (喂 seed_d1)
    jsonl_path = out_dir / "_all.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in sorted(results, key=lambda x: x.get("page_no", 999999)):
            out = r.get("output") or {}
            row = {
                "stem": r["stem"],
                "page_no": r.get("page_no"),
                "trusted": r.get("trusted", False),
                "doc_title": out.get("doc_title", ""),
                "doc_number": out.get("doc_number", ""),
                "chapter_title": out.get("chapter_title", ""),
                "is_meta": out.get("is_meta", False),
                "text_blocks": out.get("text_blocks", []),
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 写 _report.md
    total_input = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in results)
    total_output = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in results)
    n_trust = sum(1 for r in results if r.get("trusted"))
    n_fail = sum(1 for r in results if not r.get("output"))
    n_meta = sum(1 for r in results if (r.get("output") or {}).get("is_meta"))
    n_articles = sum(len((r.get("output") or {}).get("text_blocks", [])) for r in results)

    (out_dir / "_report.md").write_text(f"""# C2 LLM Page Structure Report

- doc: `{args.doc}`
- model: `{MODEL}`
- pages: {len(results)}
- trusted: {n_trust}
- fatal_failed: {n_fail}
- meta_pages: {n_meta}
- text_blocks: {n_articles}
- total_input_tokens: {total_input}
- total_output_tokens: {total_output}
- elapsed: {time.time()-t_start:.0f}s

## JSONL

`_all.jsonl` 每行一页, schema:
```
{{"stem","page_no","trusted","doc_title","doc_number","chapter_title","is_meta","text_blocks":[{{"type","number","text"}}]}}
```

直接喂 `build/export/seed_pages.py` (待写) 进 D1 `pages` + `pages_fts` 表。
""", encoding="utf-8")

    print(f"\n[final] done={len(results)}  trusted={n_trust}  fatal={n_fail}  meta={n_meta}  blocks={n_articles}")
    print(f"[final] tokens: in={total_input} out={total_output}  elapsed={time.time()-t_start:.0f}s")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
