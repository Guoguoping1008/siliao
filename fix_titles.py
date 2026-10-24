"""对已生成的 .md 重跑标题判定: 若当前 H1 不合规则提升更合适的行作为 H1。"""
import os, re, sys, json, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ocr_batch as ob


def fix_file(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    lines = raw.split("\n")
    # 去掉现有 H1
    body = [l for l in lines if not l.startswith("# ")]
    paras = [p.strip() for p in "\n".join(body).split("\n\n") if p.strip()]
    if not paras:
        return False, "empty"
    title = ob.pick_title(paras)
    out = []
    if title:
        out += [f"# {title}", ""]
    seen = set()
    for p in paras:
        if p == title or p in seen:
            continue
        seen.add(p)
        out += [p, ""]
    new = "\n".join(out).rstrip() + "\n"
    if new == raw:
        return False, "unchanged"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)
    return True, f"title={title!r}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="E:/workspace/siliao/Markdown")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    n = ch = 0
    for dp, _, fs in os.walk(args.root):
        for fn in sorted(fs):
            if not fn.endswith(".md") or fn.startswith("_"):
                continue
            n += 1
            if args.dry_run:
                continue
            ok, msg = fix_file(os.path.join(dp, fn))
            if ok:
                ch += 1
    print(f"[titles] scanned={n} changed={ch}")


if __name__ == "__main__":
    main()