import os
import re

p = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "a_1135400.html")
t = open(p, encoding="utf-8", errors="ignore").read()

for pat in [r"window\.__[A-Z_]+__\s*=", r"__INITIAL_STATE__",
            r'"articleId"\s*:', r"lark-content", r"api/", r"contentUrl"]:
    ms = list(re.finditer(pat, t))
    print(f"{pat}: {len(ms)} hits", [m.start() for m in ms[:3]])

print()
# script 里的 json
for m in re.finditer(r'<script[^>]*>(.*?)</script>', t, re.S):
    s = m.group(1)
    if "1135400" in s and len(s) > 2000:
        i = s.find("1135400")
        print("script 含 id, len:", len(s))
        print(repr(s[max(0, i - 300):i + 500]))
        break
