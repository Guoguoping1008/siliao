graphrag/
├── settings.yaml          # 模型配置(DeepSeek + bge-large-zh)
├── prompts/                # 中文 prompt 模板(覆盖默认英文)
│   ├── entity_extraction.txt
│   ├── summarize_descriptions.txt
│   ├── extract_graph.txt
│   ├── community_report.txt
│   ├── local_search.txt
│   └── global_search.txt
├── input/                  # 章节 md,自动从 data/markdown/<doc_id>/articles/ 复制
├── run.sh                  # 总入口
└── .env.example            # API Key 模板(不提交)

调用:
  cp .env.example .env  &&  vim .env
  cp ../../data/markdown/feed-law-2026/articles/*.md input/
  ./run.sh