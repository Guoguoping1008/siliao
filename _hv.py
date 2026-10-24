
import os, re, html.parser
base = r"E:/workspace/siliao/minimax"
# 用 HTMLParser 校验生成的 table 结构
class V(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack=[]; self.err=[]; self.ntbl=0
    def handle_starttag(self, tag, attrs):
        if tag=="table": self.ntbl+=1
        if tag in ("tr","td","th"): self.stack.append(tag)
    def handle_endtag(self, tag):
        if tag in ("tr","td","th"):
            if not self.stack: self.err.append(f"多余闭合 {tag}")
            elif self.stack[-1]!=tag: self.err.append(f"闭合不匹配 {self.stack[-1]}!={tag}")
            else: self.stack.pop()
v=V()
# 从 0108 里取
for dp,dns,fns in os.walk(base):
    if "0108.md" in fns:
        t=open(os.path.join(dp,"0108.md"),encoding="utf-8").read()
        for m in re.finditer(r"<table.*?</table>", t, re.S):
            v.feed(m.group(0))
        break
print("table 数:", v.ntbl, " 未闭合:", v.stack, " 错误:", v.err[:5])
