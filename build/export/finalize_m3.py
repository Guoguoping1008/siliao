"""
finalize_m3.py: 收尾 M3 OCR 任务

干三件事:
1. 读 m3_ocr_pages.py 写的 _report.json, 找出 fatal_failed 的图
2. 对每张 fatal_failed 再单独跑一次 (更长超时 300s, 关 thinking, 更小 max_tokens)
3. 仍失败的给出最终列表: data/markdown/<doc>/pages_m3/_final_failures.json

用法:
    python build/export/finalize_m3.py  # 自动从 _report.json 读
    python build/export/finalize_m3.py --retry  # 对 fatal_failed 再跑一次
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
from pathlib import Path

ROOT = Path("E:/workspace/siliao")
DEFAULT_DOC = "feed-law-collection-2023-full"
IMG_DIR = ROOT / "Images"
OUT_DIR = ROOT / "data/markdown" / DEFAULT_DOC / "pages_m3"

UPSTREAM = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
MODEL = "MiniMax-M3"
TIMEOUT_S = 300  # 比主任务更长
MAX_RETRY = 3

SYSTEM_PROMPT = """你是中文 OCR 引擎, 精确识别图片中的文字, 输出 markdown 格式。
输入: 一张手机拍摄的纸质书双页合拍图.
硬性要求:
1. 逐字 OCR, 不漏字, 不改字, 不解释, 不总结
2. 保留原文段落结构 (空行分隔)
3. 章节标题、法条号用 markdown 表示 (# / ** / 第X条)
4. 页码/页眉/水印全部忽略
5. 输出格式严格按 <LEFT>...</LEFT> 与 <RIGHT>...</RIGHT> 两个标签包围:
   <LEFT>...</LEFT><RIGHT>...</RIGHT>
不要输出标签外的任何文字。""".strip()


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


def call_m3(api_key: str, b64_jpeg: str) -> dict:
    body = {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "请 OCR 这张图, 输出 <LEFT>...</LEFT><RIGHT>...</RIGHT>"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_jpeg}"}},
            ]},
        ],
        "max_tokens": 8192,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        UPSTREAM,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8")
    j = json.loads(raw)
    if j.get("base_resp", {}).get("status_code") not in (0, None):
        raise RuntimeError(f"upstream error: {j.get('base_resp')}")
    return j["choices"][0]["message"]["content"]


def split_lr(content: str) -> tuple[str, str]:
    left = re.search(r"<LEFT>(.*?)</LEFT>", content, re.DOTALL | re.IGNORECASE)
    right = re.search(r"<RIGHT>(.*?)</RIGHT>", content, re.DOTALL | re.IGNORECASE)
    return (left.group(1).strip() if left else "",
            right.group(1).strip() if right else "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default=DEFAULT_DOC)
    parser.add_argument("--retry", action="store_true", help="对 fatal_failed 再单独重试")
    parser.add_argument("--report", type=str, default="")
    args = parser.parse_args()

    global OUT_DIR
    OUT_DIR = ROOT / "data/markdown" / args.doc / "pages_m3"
    report_path = Path(args.report) if args.report else OUT_DIR / "_report.json"

    if not report_path.exists():
        print(f"[ERR] 找不到 {report_path}, 主任务还没跑完?")
        return 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    results = report.get("results", [])
    fatals = [r for r in results if r.get("fatal_error") or not (OUT_DIR / f"{r['stem']}__L.md").exists()]
    print(f"[scan] 总图 {report.get('imgs', '?')}, 已处理 {len(results)}, fatal {len(fatals)}")

    # 列出 (即使不重试也打印)
    print("\n=== 当前失败列表 ===")
    for r in fatals:
        print(f"  {r['stem']}.jpg  → {r.get('fatal_error', 'NO_OUTPUT')}")

    if not args.retry:
        # 只列出失败, 不重试
        out = {
            "imgs_total": report.get("imgs"),
            "processed": len(results),
            "failed_count": len(fatals),
            "failed": fatals,
        }
        (OUT_DIR / "_final_failures.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[done] 失败列表已写到 {OUT_DIR}/_final_failures.json")
        return 0

    # 重试
    api_key = load_api_key()
    print(f"\n[retry] 开始重试 {len(fatals)} 张 (单张超时 {TIMEOUT_S}s, 单线程)...")
    retried_ok = []
    still_failed = []

    for i, r in enumerate(fatals, 1):
        stem = r["stem"]
        img_path = IMG_DIR / f"{stem}.jpg"
        if not img_path.exists():
            still_failed.append({**r, "final_error": "IMG_NOT_FOUND"})
            continue

        last_err = None
        for attempt in range(1, MAX_RETRY + 1):
            try:
                b64 = base64.b64encode(img_path.read_bytes()).decode()
                content = call_m3(api_key, b64)
                left, right = split_lr(content)
                if not left and not right:
                    raise RuntimeError("empty L/R after parse")
                (OUT_DIR / f"{stem}__L.md").write_text(left + "\n", encoding="utf-8")
                (OUT_DIR / f"{stem}__R.md").write_text(right + "\n", encoding="utf-8")
                retried_ok.append(stem)
                print(f"  [{i}/{len(fatals)}] {stem}: ✓ (attempt {attempt})")
                break
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                print(f"    [retry {attempt}/{MAX_RETRY}] {stem}: {last_err[:80]}")
                time.sleep(5 * attempt)  # 拉长间隔, 给上游恢复时间
        else:
            still_failed.append({**r, "final_error": last_err})
            print(f"  [{i}/{len(fatals)}] {stem}: ✗ {last_err}")

    # 写最终失败列表
    out = {
        "imgs_total": report.get("imgs"),
        "processed": len(results),
        "retried_ok_count": len(retried_ok),
        "retried_ok": retried_ok,
        "final_failed_count": len(still_failed),
        "final_failed": still_failed,
    }
    (OUT_DIR / "_final_failures.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n[final] 重试成功 {len(retried_ok)}, 仍失败 {len(still_failed)}")
    print(f"[final] 最终失败列表已写到 {OUT_DIR}/_final_failures.json")
    return 0 if not still_failed else 2


if __name__ == "__main__":
    sys.exit(main())
