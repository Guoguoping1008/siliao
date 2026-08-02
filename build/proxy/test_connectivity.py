"""
最小连通性测试: 验证 MiniMax key 是否能通过代理正常工作。

用法:
    1. cp build/graphrag/.env.example build/graphrag/.env
    2. 编辑 .env 把 PASTE_YOUR_KEY_HERE 替换为真实 key
    3. 启动代理:  export GRAPHRAG_API_KEY=$(grep GRAPHRAG_API_KEY build/graphrag/.env | cut -d= -f2) && python build/proxy/openai_to_minimax.py &
    4. 跑测试:    python build/proxy/test_connectivity.py

成功:  打印 1 条 MiniMax 回复 + token 用量
失败:  打印 HTTP code + 错误详情
"""

from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error


def read_key() -> str:
    """从 .env 读 key,绝不打印 key 明文"""
    env_path = os.path.join(os.path.dirname(__file__), "..", "graphrag", ".env")
    env_path = os.path.abspath(env_path)
    if not os.path.exists(env_path):
        print(f"[ERR] {env_path} 不存在,先 cp .env.example .env 并填 key", file=sys.stderr)
        sys.exit(1)
    for line in open(env_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("GRAPHRAG_API_KEY=") and not line.startswith("#"):
            key = line.split("=", 1)[1].strip()
            if not key or key == "PASTE_YOUR_KEY_HERE":
                print("[ERR] .env 里 key 还是占位符,请先填真实 key", file=sys.stderr)
                sys.exit(1)
            return key
    print("[ERR] .env 里没找到 GRAPHRAG_API_KEY", file=sys.stderr)
    sys.exit(1)


def main():
    api_key = read_key()

    # 极简 prompt,只为了验证 key 通路,消耗 < 100 tokens
    body = json.dumps({
        "model": "MiniMax-Text-01",
        "messages": [{"role": "user", "content": "用一句话回答: 1+1=?"}],
        "max_tokens": 50,
        "temperature": 0,
    }).encode()

    # 注意: 这里调的是真实 MiniMax endpoint(不是本地代理),因为是单次验证
    url = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    print(f"[test] POST {url}")
    print(f"[test] model: MiniMax-Text-01, prompt: 1+1=? (50 token cap)")
    print(f"[test] key prefix: {api_key[:6]}...{api_key[-4:]}")
    print(f"[test] sending...")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            usage = data.get("usage", {})
            print(f"\n[OK] HTTP {resp.status}")
            print(f"[OK] reply: {msg.get('content', '')[:200]}")
            print(f"[OK] usage: {usage.get('total_tokens', '?')} tokens")
            return 0
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        print(f"\n[FAIL] HTTP {e.code}")
        print(f"[FAIL] body: {body}")
        return 1
    except urllib.error.URLError as e:
        print(f"\n[FAIL] network: {e.reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())