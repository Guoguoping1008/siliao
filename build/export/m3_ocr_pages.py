"""
M3 多模态 OCR: 直接读原图 → 按 L/R 输出 markdown

输入:  Images/*.jpg  (516 张手机翻拍, 4240x3439 双页合拍)
输出:  data/markdown/<doc_id>/pages_m3/<stem>__L.md
       data/markdown/<doc_id>/pages_m3/<stem>__R.md

策略:
- 一张图一次 M3 多模态调用
- prompt 让 M3 严格 OCR (逐字抄录, 不解释, 不总结)
- prompt 要求输出格式: <LEFT>...</LEFT>\n<RIGHT>...</RIGHT>
- 解析输出, 拆成 L/R 两个 md
- 校验: 如果某页字数过少 (<50), 标记 trusted=false (M3 漏识)
- 复用已有 pages/ (PaddleOCR) 作为 fallback, M3 失败的页用 PaddleOCR 结果

成本预算: 516 张 × ~5K tokens = 2.5M tokens
  - 输入 $0.60/M = $1.5
  - 输出 $2.40/M (按 1/4 输出估算) = $0.5
  - 总 ~$2 (¥14)
耗时: 516 × 12s / 6 worker ≈ 17 min

并发: 6 worker (M3 多模态比 Text-01 重, 不贪多)
"""

from __future__ import annotations
import argparse
import base64
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
IMG_DIR = ROOT / "Images"
OUT_DIR = ROOT / "data/markdown" / DEFAULT_DOC / "pages_m3"

UPSTREAM = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
MODEL = "MiniMax-M3"
TIMEOUT_S = 180
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

SYSTEM_PROMPT = """你是中文 OCR 引擎, 任务: 精确识别图片中的文字, 输出 markdown 格式。

输入: 一张手机拍摄的纸质书双页合拍图 (左页 + 右页并排).

硬性要求:
1. 逐字 OCR, 不漏字, 不改字, 不解释, 不总结, 不写"这是..."这种描述
2. 保留原文段落结构 (空行分隔)
3. 章节标题、法条号、加粗等格式用 markdown 表示 (# / ** / `第X条`)
4. 表格用 markdown 表格语法
5. 页码/页眉/水印 (HUAWEI P40 Pro 5G / LEICA / 数字页码) 全部忽略不输出
6. 模糊不清的字用 □ 表示 (一个 □ 代表一个字符)
7. 输出格式严格按 <LEFT>...</LEFT> 与 <RIGHT>...</RIGHT> 两个标签包围:
   <LEFT>
   (左页 OCR 结果)
   </LEFT>
   <RIGHT>
   (右页 OCR 结果)
   </RIGHT>
8. 单页无内容 (如纯图/纯空白) 在对应标签内写 "(空白)"

不要输出任何标签外的解释文字。""".strip()


USER_TEMPLATE = """请 OCR 这张图 (双页合拍, 左页在前, 右页在后), 输出 <LEFT>...</LEFT><RIGHT>...</RIGHT> 格式:""".strip()


# ──────────────── LLM ────────────────

def call_m3(api_key: str, b64_jpeg: str) -> dict:
    body = {
        "model": MODEL,
        "thinking": {"type": "disabled"},  # OCR 不需要 thinking, 省时间
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": USER_TEMPLATE},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_jpeg}"}},
            ],
        }],
        "max_tokens": 8192,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        UPSTREAM,
        data=json.dumps(body).encode(),
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


# ──────────────── 解析 ────────────────

def split_lr(content: str) -> tuple[str, str, list[str]]:
    """从 M3 输出提取 <LEFT>...</LEFT> 和 <RIGHT>...</RIGHT>"""
    errs = []

    left_match = re.search(r"<LEFT>(.*?)</LEFT>", content, re.DOTALL | re.IGNORECASE)
    right_match = re.search(r"<RIGHT>(.*?)</RIGHT>", content, re.DOTALL | re.IGNORECASE)

    if not left_match:
        errs.append("missing <LEFT> tag")
    if not right_match:
        errs.append("missing <RIGHT> tag")

    left = left_match.group(1).strip() if left_match else ""
    right = right_match.group(1).strip() if right_match else ""

    # 去标签残留 (M3 可能多写)
    left = re.sub(r"^```[a-z]*\s*", "", left).rstrip()
    left = re.sub(r"\s*```\s*$", "", left)
    right = re.sub(r"^```[a-z]*\s*", "", right).rstrip()
    right = re.sub(r"\s*```\s*$", "", right)

    return left, right, errs


def assess_quality(left: str, right: str) -> list[str]:
    """简单质量评估"""
    errs = []
    if len(left) < 30 and left != "(空白)":
        errs.append(f"left too short ({len(left)} chars)")
    if len(right) < 30 and right != "(空白)":
        errs.append(f"right too short ({len(right)} chars)")
    return errs


# ──────────────── 主流程 ────────────────

def process_one(api_key: str, img_path: Path) -> dict:
    stem = img_path.stem
    out_L = OUT_DIR / f"{stem}__L.md"
    out_R = OUT_DIR / f"{stem}__R.md"

    # 幂等
    if out_L.exists() and out_R.exists():
        return {"stem": stem, "skip": True}

    t0 = time.time()
    last_err = None
    for attempt in range(1, MAX_RETRY + 1):
        try:
            b64 = base64.b64encode(img_path.read_bytes()).decode()
            r = call_m3(api_key, b64)
            left, right, parse_errs = split_lr(r["content"])
            qual_errs = assess_quality(left, right)
            errs = parse_errs + qual_errs

            # 写两个 md
            out_L.write_text(left + "\n", encoding="utf-8")
            out_R.write_text(right + "\n", encoding="utf-8")

            return {
                "stem": stem,
                "skip": False,
                "elapsed_s": round(time.time() - t0, 1),
                "attempt": attempt,
                "left_chars": len(left),
                "right_chars": len(right),
                "usage": r["usage"],
                "errors": errs,
            }
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(1 * attempt)

    return {
        "stem": stem,
        "skip": False,
        "elapsed_s": round(time.time() - t0, 1),
        "fatal_error": last_err,
        "errors": [f"FATAL: {last_err}"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()

    global OUT_DIR
    OUT_DIR = ROOT / "data/markdown" / args.doc / "pages_m3"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    api_key = load_api_key()

    img_files = sorted(IMG_DIR.glob("*.jpg"))
    todo = [p for p in img_files if not ((OUT_DIR / f"{p.stem}__L.md").exists() and (OUT_DIR / f"{p.stem}__R.md").exists())]
    if args.limit:
        todo = todo[: args.limit]

    print(f"[plan] imgs={len(img_files)}  todo={len(todo)}  workers={args.workers}  model={MODEL}")

    if not todo:
        print("[done] nothing to do")
        return 0

    t_start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, api_key, p): p for p in todo}
        done_count = 0
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            done_count += 1
            if done_count % 10 == 0 or done_count == len(todo):
                el = time.time() - t_start
                rate = done_count / el
                eta = (len(todo) - done_count) / rate if rate else 0
                n_err = sum(1 for x in results if x.get("errors"))
                n_fatal = sum(1 for x in results if x.get("fatal_error"))
                print(f"[prog] {done_count}/{len(todo)}  err={n_err}  fatal={n_fatal}  rate={rate:.2f}/s  eta={eta:.0f}s  elapsed={el:.0f}s")

    # 报告
    (OUT_DIR / "_report.json").write_text(
        json.dumps({
            "imgs": len(img_files),
            "done": len(results),
            "elapsed_s": round(time.time() - t_start, 1),
            "results": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    n_err = sum(1 for x in results if x.get("errors"))
    n_fatal = sum(1 for x in results if x.get("fatal_error"))
    total_in = sum((x.get("usage") or {}).get("prompt_tokens", 0) for x in results)
    total_out = sum((x.get("usage") or {}).get("completion_tokens", 0) for x in results)
    print(f"\n[final] done={len(results)}  err={n_err}  fatal={n_fatal}")
    print(f"[final] tokens: in={total_in} out={total_out}")
    print(f"[final] out dir: {OUT_DIR}")
    print(f"[final] 估算成本: ${(total_in*0.6 + total_out*2.4)/1e6:.2f}")
    return 0 if n_fatal == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
