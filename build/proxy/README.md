build/proxy/
└── openai_to_minimax.py   # OpenAI 客户端 → MiniMax 协议桥接

启动:
    export MINIMAX_API_KEY=eyJhb...
    python build/proxy/openai_to_minimax.py
    # 监听 127.0.0.1:7891

为什么需要:
- graphrag 走 OpenAI 客户端,硬编码 POST /v1/chat/completions
- MiniMax 路径是 POST /v1/text/chatcompletion_v2
- 字段格式恰好兼容,只需"路径重写 + 头部透传"

上游 endpoint:
- chat: https://api.minimaxi.com/v1/text/chatcompletion_v2
- embedding: 暂无 OpenAI 兼容路径,本地 bge 仍用 llama.cpp / vllm

健康检查:
    curl http://127.0.0.1:7891/health