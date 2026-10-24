
import os, json
p = r"E:/workspace/siliao/_tbl_list.json"
print("json 存在:", os.path.exists(p), os.path.getsize(p) if os.path.exists(p) else 0)
if os.path.exists(p):
    d = json.load(open(p, encoding="utf-8"))
    print("页数:", len(d))
    stems = [x["stem"] for x in d]
    for s in ("0217","0061","0108","0031"):
        print("  ", s, "在清单里:", s in stems)
