---
type: adr
number: 0002
status: deferred
created: 2026-08-31
client: siliao
tags: [adr, ocr, hardware, deferred]
---

# ADR-002 · Unlimited-OCR 横评试点延期

## 上下文

siliao RAG 灌库前端的 OCR 链路存在两条并行入口:
- `build/ocr/pic2md.py` — `paddleocr.PaddleOCR`(中文 v4,开 cls 方向分类),适用手机翻拍图,产出 `data/markdown/<doc_id>/raw_ocr/<stem>.json` 缓存 + `pages/*.md`
- `build/ocr/run_mineru.py` — 调用 `magic-pdf`,适用扫描 PDF,保留表格/公式/印章

历史债(commit `42ad05c` 已修但仍未消):`article_splitter` 章节归属 bug,根因是 OCR 输出顺序错。
若换成更强 OCR 端,这类后处理 bug 预期减少。

候选方案:**baidu/Unlimited-OCR**(3B 参数, MIT, HF 月下载 295 万次, paper arXiv 2606.23050)。
卖点:**one-shot long-horizon parsing** — 单次推理同时给版面、阅读顺序、表格、公式;
副作用是需要 `torch==2.10.0+cu129`、`transformers==4.57.1`、`Python 3.12.3`、 ≥16GB 显存。

## 决策

**不做试点**。将 Unlimited-OCR 横评任务整体延后到具备目标硬件的机器到位再启。

## 触发场景

任一满足即重新评估(2 条以上同时满足强烈建议重启):
1. 拿到 ≥16GB 显存的 Linux 主机(本机 RTX 4090/A5000 起步,或云上 A10/H100)
2. 扫描版法规 / 手写体翻拍 超出 PaddleOCR 当前能力,业务侧提出替代需求
3. Unlimited-OCR 出现 Windows 兼容 wheel 或 mini 模型(2B/1B)
4. PaddleOCR-VL / DeepSeek-OCR 出现更低显存门槛分支并通过初评

## 取舍

| 方案 | 代价 | 收益 |
|---|---|---|
| **当前(PaddleOCR + MinerU 双轨)** | 两套入口、章节归属 bug 历史债、缺 OCR 前端评测 | 0 部署成本,8GB 显存够用 |
| **换 Unlimited-OCR transformers** | 需 ≥16GB GPU + Linux + Python 3.12 重建环境 | one-shot 结构化输出,可减 article_splitter 类的后处理 bug |
| **换 Unlimited-OCR vLLM/SGLang** | 同上 + 部署复杂度翻倍(起 sidecar 服务) | 推理吞吐高、社区活跃、HF 月下载量百万级 |
| 推迟(选) | 短期不变;债项继续累积 | 待 GPU 资源到位再评估,避免在本机 8GB 上消耗工程时间 |

## 关键技术细节

1. **Lock-version 验证**: uv pip install --dry-run 确认 `torch==2.10.0+cu129` 在 PyPI 索引中
   only 有 `manylinux_2_28_x86_64 / manylinux_2_28_aarch64` 两个 wheel,Windows `win_amd64` 缺失
2. **显存估算**: 3B BF16 权重 ≈ 6GB,Kv cache + activation ≈ 4-5GB,
   再加 CUDA context overhead,实际峰值 ≥10GB。RTX 2060 SUPER 8GB 装不下,即使量化到 int8
   也会在 `max_length=32768` decoding 时 OOM
3. **仓库 `infer.py` 是 SGLang 客户端**: 也意味着官方不提供 transformers offline 路径,
   transformers 用法完全靠 `trust_remote_code` 跑 `modeling_*.py`,升级 transformers 风险高
4. **30 天后再回顾**: 在这之前,如果有任何硬件/版本变化(Windows 出 cu129 wheel / 出 mini 模型)
   重做 dry-run;否则不进 evaluation

## 还债触发器

- 上述 4 条 restart 信号任 2 条成立 → 重启 `t_94fb7501` 的延期版本
- 章节归属 bug 在生产数据上重新出现 ≥ 1 次/月 → 把"换 OCR 端"提级到 P0
- 业务明确需要扫描版法规进库但 PaddleOCR/MinerU 召回 < 80% → 触发同样的 P0 重启

## 参考

- 源仓库: <https://github.com/baidu/Unlimited-OCR>
- HF 模型: <https://huggingface.co/baidu/Unlimited-OCR>(3B BF16, MIT, 月下载 295 万)
- 锁版验证: uv pip dry-run 输出
- 取消任务卡: `t_94fb7501`
