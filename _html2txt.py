"""抽取阿里云开发者社区文章的正文, 保留表格/代码块结构。"""
import html
import re
import sys

path = sys.argv[1]
t = open(path, encoding="utf-8", errors="ignore").read()

# 取 class="article-content" 的 div 内容(用括号配平找结尾)
i = t.find('class="article-content"')
if i < 0:
    print("找不到 article-content")
    sys.exit(1)
start = t.find(">", i) + 1
depth = 1
pos = start
while pos < len(t) and depth > 0:
    nxt_open = t.find("<div", pos)
    nxt_close = t.find("</div>", pos)
    if nxt_close < 0:
        break
    if 0 <= nxt_open < nxt_close:
        depth += 1
        pos = nxt_open + 4
    else:
        depth -= 1
        pos = nxt_close + 6
body = t[start:pos]

body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
body = re.sub(r"<pre[^>]*>", "\n[[CODE]]\n", body)
body = re.sub(r"</pre>", "\n[[/CODE]]\n", body)
body = re.sub(r"<code[^>]*>", "`", body)
body = re.sub(r"</code>", "`", body)
body = re.sub(r"</t[dh]>", " | ", body)
body = re.sub(r"</tr>", "\n", body)
body = re.sub(r"<br\s*/?>", "\n", body)
body = re.sub(r"</(p|div|h[1-6]|li|blockquote)>", "\n", body)
body = re.sub(r"<[^>]+>", "", body)
body = html.unescape(body)
body = re.sub(r"[ \t]+\n", "\n", body)
body = re.sub(r"\n{3,}", "\n\n", body)
print(body.strip()[:12000])
