
import os, json
base = r"C:/Users/Administrator/AppData/Local/hermes/profiles/qingmang/skills"
for root, dirs, files in os.walk(base):
    for f in files:
        if f in ("SKILL.md", ".skill.json", "skill.json", "meta.json"):
            p = os.path.join(root, f)
            print(p.replace(base, ""))
            if f == "SKILL.md":
                continue
            print("   ", open(p, encoding="utf-8").read()[:400])
