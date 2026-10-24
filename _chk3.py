
import os, re, sys
sys.path.insert(0, r"E:/workspace/siliao")
sys.argv=["x"]
exec(open(r"E:/workspace/siliao/_toc_tree.py", encoding="utf-8").read().split("def main()")[0])

entries = parse_toc(TOC)
tree = build_tree(entries)
docs = [(t,p,docno) for lv,t,p,docno in tree if lv==4 and p is not None]
# 文档 -> (起始书页, 结束书页)
ranges=[]
for i,(t,start,dn) in enumerate(docs):
    end = (docs[i+1][1]-1) if i+1<len(docs) else 9999
    ranges.append((t,start,end,dn))

# 校验: scan page == book page?
# 取每个文档的首个 scan 页, 看看内容是否对得上该文档标题
def scan_first_pages(dirs):
    out={}
    for d in dirs:
        p=os.path.join(r"E:/workspace/siliao/minimax", d)
        for f in sorted(os.listdir(p)):
            if f.endswith(".md") and f[:-3].isdigit():
                out.setdefault(d, []).append(int(f[:-3]))
    return out

scan = scan_first_pages(["02制度文件","03相关法规法律法规文件","04标准及标准目录"])
print("目录里前 12 个文档 vs scan 页首:")
for i,(t,start,end,dn) in enumerate(ranges[:12]):
    # 找包含 start 的 scan 页(在 02/03/04 目录里)
    cand=None
    for d,ps in scan.items():
        for sp in ps:
            if abs(sp-start)<=1: cand=(d,sp); break
        if cand: break
    # 读那个 scan 页看标题
    head=""
    if cand:
        fp=os.path.join(r"E:/workspace/siliao/minimax", cand[0], f"{cand[1]:04d}.md")
        if os.path.exists(fp):
            head=open(fp,encoding="utf-8").read().strip()[:60].replace("\\n","|")
    print(f"  书页{start:4d} {t[:40]:42s} scan={cand} | {head}")
