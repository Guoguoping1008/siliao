import os
import re

p = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "a_1135400.html")
t = open(p, encoding="utf-8", errors="ignore").read()
for m in re.finditer(r"api/", t):
    print("  api/ @", m.start(), repr(t[m.start() - 180:m.start() + 140]))
    print()
