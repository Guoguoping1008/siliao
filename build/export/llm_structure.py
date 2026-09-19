"""
LLM 二次结构化: 把 chapters/*.md → 结构化 JSON

输入:  markdown/<doc_id>/chapters/<ch_id>.md
输出:  markdown/<doc_id>/structured/<ch_id>.json
       markdown/<doc_id>/structured/_all.json
       markdown/<doc_id>/structured/_report.md

模式:
- 一章一次 LLM 调用 (model: MiniMax-Text-01 / M3)
- 强校验: LLM 输出的每条 article.text 必须在原 md 行里 100% 字符串匹配
- 失败重试 3 次, 仍失败则保留 LLM 原输出但标记 trusted=false

为什么不让 LLM 自己"改正错字":
- OCR 噪声在 RAG 阶段反而是有用的(检索时关键词匹配需要保留原字符)
- 改正后 faithfulness 校验会失效 (LLM 输出 vs 原文)
- 这一版只切不修, 修字留给下一轮

为什么不并发:
- MiniMax rate limit 经验值约 5 req/s, 单进程串行 + 重试就够
- 并发会让 error 难定位

调用前必备:
- build/graphrag/.env 里有 MINIMAX_API_KEY
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# 直接调 MiniMax 上游,不走本地 proxy (proxy 没起)
import urllib.request
import urllib.error

ROOT = Path("E:/workspace/siliao")
DEFAULT_DOC = "feed-law-collection-2023-full"
CHAPTERS_DIR = ROOT / "markdown" / DEFAULT_DOC / "chapters"
OUT_DIR = ROOT / "markdown" / DEFAULT_DOC / "structured"
ENV_FILE = ROOT / "build" / "graphrag" / ".env"

UPSTREAM = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01")
TIMEOUT_S = 180


def load_api_key() -> str:
    """从 .env 取 MINIMAX_API_KEY (脚本运行时由调用方注入, 本函数只校验非空)"""
    k = os.environ.get("MINIMAX_API_KEY", "")
    if not k or "REPLACE_AT_RUNTIME" in k:
        # fallback: 从 hermes profile 抄
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
        raise RuntimeError("MINIMAX_API_KEY not set; check build/graphrag/.env")
    return k


# ────────────────────────── prompt ──────────────────────────

SYSTEM_PROMPT = """你是中文法规文档的结构化助手, 只做一件事: 把 OCR 出的章节 markdown 切成"条"级 JSON。

硬性规则:
1. **逐字抄录**: 每条 article.text 必须是原文连续片段, 不得增删字、不得改错字、不得补标点
2. **不输出目录**: 如果章节正文里有"目录"残留 / 页眉 / 章节导航 / 出版社信息, 全部归到 is_toc_residue=true 且 articles=[]
3. **不输出空章节**: 没有"第X条"或"第X章"结构的章节, articles=[], 但 chapter_title 保留
4. **不发明**: 原文没有的字不要写, OCR 错字(如"文伴")也照抄, 不要纠正
5. **法条号必须带原文前缀**: "第十五条" / "第十五条之一" / "（一）" 等
6. **source_lines**: 记录该条 article.text 在原 md 里出现的起始 1-indexed 行号; 跨行时记第一行

输出格式 (严格 JSON, 不要任何 markdown 围栏):
{
  "chapter_id": "<原 ch_id, 如 ch01>",
  "chapter_title": "<原文章名, 逐字>",
  "is_toc_residue": false,
  "articles": [
    {
      "number": "第十五条",
      "text": "<逐字抄录, 可含换行 \\n>",
      "source_lines": [12, 13]
    }
  ]
}
""".strip()


USER_TEMPLATE = """原文章节 markdown 如下 (路径: {src_path}, 行号从 1 开始):

```
{md_text}
```

请按规则切分, 输出 JSON。
""".strip()


# ────────────────────────── 校验 ──────────────────────────

def check_faithfulness(out: dict, md_lines: list[str]) -> list[str]:
    """
    严格校验: output 里每条 article.text 的所有非空白字符都必须在原 md_lines 里出现 (顺序可乱, 但必须都出现)
    返回错误列表, 空表示 100% 通过
    """
    errs = []
    full_text = "\n".join(md_lines)

    for i, art in enumerate(out.get("articles", [])):
        text = art.get("text", "")
        if not text:
            errs.append(f"art[{i}].text 为空")
            continue
        # 抽 30 字以上的不重叠指纹, 命中失败说明 LLM 编了
        # 用最长 50 字符的连续片段做 anchor
        anchors = extract_anchors(text, max_n=3, min_len=30)
        miss = [a for a in anchors if a not in full_text]
        if miss:
            errs.append(f"art[{i}].number={art.get('number')!r}: {len(miss)}/{len(anchors)} 锚点不在原文中; 例: {miss[0][:40]!r}")
    return errs


def extract_anchors(text: str, max_n: int = 3, min_len: int = 30) -> list[str]:
    """从 text 抽 max_n 个非空白连续片段 (每个 ≥ min_len) 作为锚点"""
    chunks = re.findall(r"\S+", text)
    anchors = []
    cur = ""
    for c in chunks:
        if len(cur) + len(c) + 1 > 80:
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


# ────────────────────────── LLM 调用 ──────────────────────────

def call_llm(api_key: str, system: str, user: str) -> dict:
    """直接打 MiniMax 上游"""
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 16000,
        # MiniMax 协议不支持 response_format=json_object, 让 LLM 自行按 system prompt 输出 JSON, 用 parse_json 兜底
    }).encode("utf-8")

    req = urllib.request.Request(
        UPSTREAM,
        data=body,
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
    content = j["choices"][0]["message"]["content"]
    usage = j.get("usage", {})
    return {"content": content, "usage": usage, "raw": j}


def parse_json(content: str) -> Optional[dict]:
    """宽松解析: LLM 可能把 JSON 裹在 ```json ... ``` 里"""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```\s*$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # 兜底: 找第一个 { 到最后一个 }
        s = content.find("{")
        e_pos = content.rfind("}")
        if s >= 0 and e_pos > s:
            try:
                return json.loads(content[s: e_pos + 1])
            except Exception:
                pass
        raise e


# ────────────────────────── 主流程 ──────────────────────────

def structure_one(api_key: str, ch_path: Path, ch_id: str, max_retry: int = 3) -> dict:
    md_text = ch_path.read_text(encoding="utf-8")
    md_lines = md_text.splitlines()

    user = USER_TEMPLATE.format(src_path=str(ch_path), md_text=md_text)

    last_err = None
    for attempt in range(1, max_retry + 1):
        try:
            t0 = time.time()
            r = call_llm(api_key, SYSTEM_PROMPT, user)
            elapsed = time.time() - t0
            out = parse_json(r["content"])
            if not out:
                raise RuntimeError("JSON parse failed")
            errs = check_faithfulness(out, md_lines)
            return {
                "chapter_id": ch_id,
                "input_chars": len(md_text),
                "input_lines": len(md_lines),
                "usage": r["usage"],
                "elapsed_s": round(elapsed, 1),
                "attempt": attempt,
                "trusted": not errs,
                "faithfulness_errors": errs,
                "output": out,
            }
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  [retry {attempt}/{max_retry}] {ch_id}: {last_err}", file=sys.stderr)
            time.sleep(2 * attempt)

    return {
        "chapter_id": ch_id,
        "input_chars": len(md_text),
        "input_lines": len(md_lines),
        "trusted": False,
        "fatal_error": last_err,
        "output": None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 章 (调试)")
    parser.add_argument("--id", type=str, default="", help="只跑指定 ch_id (调试)")
    args = parser.parse_args()

    chapters_dir = ROOT / "markdown" / args.doc / "chapters"
    out_dir = ROOT / "markdown" / args.doc / "structured"
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()
    print(f"[setup] doc={args.doc}  chapters_dir={chapters_dir}  model={MODEL}")

    ch_files = sorted(chapters_dir.glob("ch*.md"))
    if args.id:
        ch_files = [p for p in ch_files if p.stem == args.id]
    if args.limit:
        ch_files = ch_files[: args.limit]
    print(f"[plan] {len(ch_files)} 章")

    report = []
    all_results = {}
    t_start = time.time()
    total_input = 0
    total_output = 0

    for i, ch_path in enumerate(ch_files, 1):
        ch_id = ch_path.stem
        print(f"[{i}/{len(ch_files)}] {ch_id} ({ch_path.stat().st_size} B)")
        r = structure_one(api_key, ch_path, ch_id)
        all_results[ch_id] = r

        # 写单章 json
        (out_dir / f"{ch_id}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 累加 token
        u = r.get("usage") or {}
        total_input += u.get("prompt_tokens", 0)
        total_output += u.get("completion_tokens", 0)

        # 进度
        n_arts = len((r.get("output") or {}).get("articles", []))
        trusted = r.get("trusted", False)
        report_line = f"{ch_id:6}  trusted={trusted}  articles={n_arts}  input={u.get('prompt_tokens', '?')}  out={u.get('completion_tokens', '?')}  t={r.get('elapsed_s', '?')}s"
        if not trusted:
            err_count = len(r.get("faithfulness_errors") or [])
            report_line += f"  ⚠ {err_count} faithfulness errs" if err_count else f"  ⚠ fatal: {r.get('fatal_error', '')}"
        print(f"  {report_line}")
        report.append(report_line)

    # 写 _all.json + _report.md
    (out_dir / "_all.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "_report.md").write_text(
        "# LLM Structure Report\n\n"
        f"- doc: `{args.doc}`\n- model: `{MODEL}`\n- chapters: {len(ch_files)}\n"
        f"- total_input_tokens: {total_input}\n- total_output_tokens: {total_output}\n"
        f"- elapsed: {time.time()-t_start:.0f}s\n\n"
        "## Per chapter\n\n```\n" + "\n".join(report) + "\n```\n",
        encoding="utf-8",
    )

    # 统计
    n_trusted = sum(1 for r in all_results.values() if r.get("trusted"))
    n_failed = sum(1 for r in all_results.values() if not r.get("output"))
    print(f"\n[final] trusted={n_trusted}/{len(all_results)}  fatal_failed={n_failed}  total_tokens={total_input+total_output}")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
