build/proxy/
├── openai_to_minimax.py   # OpenAI 客户端 → MiniMax 协议桥接
├── test_connectivity.py   # 最小连通性验证(1 条 prompt)
└── README.md

启动代理:
    export GRAPHRAG_API_KEY=$(grep GRAPHRAG_API_KEY build/graphrag/.env | cut -d= -f2)
    python build/proxy/openai_to_minimax.py

最小连通性验证(无需 graphrag):
    cp build/graphrag/.env.example build/graphrag/.env
    # 编辑 .env,把 PASTE_YOUR_KEY_HERE 换成真实 key(永远不要贴聊天)
    python build/proxy/test_connectivity.py
    # 输出: HTTP 200 + 1 条 MiniMax 回复 + token 用量

为什么需要:
- graphrag 走 OpenAI 客户端,硬编码 POST /v1/chat/completions
- MiniMax 路径是 POST /v1/text/chatcompletion_v2
- 字段格式恰好兼容,只需"路径重写 + 头部透传"

上游 endpoint:
- chat: https://api.minimaxi.com/v1/text/chatcompletion_v2
- embedding: 暂无 OpenAI 兼容路径,本地 bge 仍用 llama.cpp / vllm

健康检查:
    curl http://127.0.0.1:7891/health

# === 安全准则 ===
# 1. .env 已 gitignore,不会被 commit
# 2. API key 永不进聊天/截图/日志(test_connectivity.py 只打前缀)
# 3. 一旦 key 进过 LLM 上下文/被贴出,视为泄露,立即去 MiniMax 控制台撤销
# 4. graphrag dry-run 用 fake key 即可,只有真生产构建才用真 key