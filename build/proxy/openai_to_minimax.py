"""
OpenAI ↔ MiniMax 协议桥接代理
=============================

为什么需要这个代理:
- graphrag 走的是 OpenAI 客户端(会硬编码 POST /v1/chat/completions)
- MiniMax 用的路径是 POST /v1/text/chatcompletion_v2
- 字段格式恰好兼容,只需要"路径重写 + 头部透传"

启动:
    export MINIMAX_API_KEY=eyJhb...
    python build/proxy/openai_to_minimax.py

监听:  127.0.0.1:7891

上游:  https://api.minimaxi.com/v1/text/chatcompletion_v2
"""

from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

UPSTREAM = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
API_KEY = os.environ.get("MINIMAX_API_KEY") or os.environ.get("GRAPHRAG_API_KEY", "")
PORT = int(os.environ.get("PROXY_PORT", "7891"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简化日志
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")

    def do_POST(self):  # noqa: N802
        if self.path not in ("/v1/chat/completions", "/v1/chat/completions/"):
            self.send_error(404, f"unknown path: {self.path}")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        # 上游请求
        req = urllib.request.Request(
            UPSTREAM,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                upstream_body = resp.read()
                self.send_response(resp.status)
                # 透传上游 content-type
                ct = resp.headers.get("Content-Type", "application/json")
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(upstream_body)))
                self.end_headers()
                self.wfile.write(upstream_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
        except urllib.error.URLError as e:
            self.send_error(502, f"upstream_unreachable: {e.reason}")

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "upstream": UPSTREAM}).encode())
            return
        self.send_error(404)


def main():
    if not API_KEY:
        print("[ERR] MINIMAX_API_KEY / GRAPHRAG_API_KEY 环境变量未设置", file=sys.stderr)
        sys.exit(1)
    print(f"[proxy] listening on 127.0.0.1:{PORT}")
    print(f"[proxy] upstream: {UPSTREAM}")
    print(f"[proxy] key prefix: {API_KEY[:8]}...{API_KEY[-4:]}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()