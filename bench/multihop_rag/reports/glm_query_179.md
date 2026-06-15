# MultiHop-RAG 检索评测报告（GLM-5.1 查询侧 · 179/200 query）

**日期**：2026-06-15
**数据**：MultiHop-RAG（`yixuantt/MultiHop-RAG`），whole_doc 整篇摄入
**建图模型**：deepseek-chat（沿用 `chat_16k/graph.db`，**不重建图**）
**查询 + 文档重排模型**：GLM-5.1（经 Anthropic 兼容网关 `api.0ki.cn/api/anthropic`）
**token_budget T**：16000
**图库**：`bench/multihop_rag/outputs/chat_16k/graph.db`（复制到 `chat_16k_glm/` 隔离查询）

---

## 1. 实验目的

**换 read 侧 LLM**：建图仍用 deepseek-chat（图不变），仅查询 + 文档重排换成 GLM-5.1，观察查询阶段对模型的敏感度。

> 这是「换 read 模型」对比实验。指标与 deepseek 同图基线**不可等同对比**（模型不同 + query 子集 n 不同），仅作方向性参考。

## 2. 执行与配额

| 项 | 值 |
|---|---|
| 目标 query | 200 |
| 实际完成 | **179**（quota 软上限触发停止） |
| 端点配额 | 1800 次 |
| 实际消耗 | **1708 / 1800**（余 92） |
| 耗时 | **3.08 小时**（11087s，纯查询循环） |
| doc_rerank | llm（语义重排） |
| 续跑 | query 级 checkpoint（`results.jsonl`），剩余 21 query 可续 |

**停止机制**：`llm.json` 的 `quota=1700` 软上限（端点总消耗 = 内部 LLM 调用 + 文档重排调用）+ 连续失败熔断（阈值 3）。本次由 quota 触发停止；因检查点间隔 10 query，实际停时端点调用 1708，略超 1700 但远低于 1800 上限。

## 3. 检索质量（179 query · doc_rerank=llm · T=16000）

| 类型 | n | hit@2 | hit@4 | **hit@10** | recall@10 | map@10 | mrr@10 |
|---|---|---|---|---|---|---|---|
| **overall** | 179 | 0.570 | 0.615 | **0.749** | 0.470 | 0.297 | 0.513 |
| inference | 65 | 0.554 | 0.585 | 0.785 | 0.481 | 0.256 | 0.467 |
| comparison | 71 | 0.563 | 0.606 | 0.676 | 0.390 | 0.282 | 0.503 |
| temporal | 43 | 0.605 | 0.674 | **0.814** | 0.585 | 0.382 | 0.601 |

## 4. 与 deepseek-chat 同图基线对比

| 指标 | deepseek-chat (n=200) | GLM-5.1 (n=179) | Δ |
|---|---|---|---|
| hit@10 | 0.770 | 0.749 | −0.021 |
| recall@10 | 0.484 | 0.470 | −0.014 |
| map@10 | 0.315 | 0.297 | −0.018 |
| mrr@10 | 0.551 | 0.513 | −0.038 |

> GLM-5.1 在查询侧的检索质量**略低于 deepseek-chat**（hit@10 −2.1pp），但量级相当、同档可用。temporal 类型两者都最强（GLM 0.814 vs deepseek 0.863）。

## 5. 成本分析

| 项 | deepseek-chat | GLM-5.1 |
|---|---|---|
| 每 query 端点调用 | ~15（14 内部 + 1 重排） | **~9.5**（8.5 内部 + 1 重排） |
| 每 query 耗时 | ~22s | **~62s** |
| 200 query 总调用（推算） | ~3000 | ~1900 |

GLM-5.1 每 query 的 LLM 调用数**少于** deepseek（9.5 vs 15，`select_facts` 更早收敛、遍历节点更少），但**单次延迟更高**（经中转网关 + `select_facts` 输入接近 T=16000 token），导致每 query 耗时反而更高（62s vs 22s）。

## 6. 复现

```bash
# 配置：bench/multihop_rag/config/llm.json（backend=claude, quota=1700；含凭据，已 gitignore）
python bench/multihop_rag/scripts/test.py \
  --output bench/multihop_rag/outputs/chat_16k_glm \
  --token-budget 16000 \
  --llm-config bench/multihop_rag/config/llm.json \
  --queries 200 --doc-rerank llm
# 续跑剩余 21 query：换新配额后重跑同命令（自动跳过已完成的 179）
```

## 7. 结论

- GLM-5.1 作为查询侧 LLM 可用，检索质量与 deepseek-chat 同档（hit@10 0.749 vs 0.770）。
- 配额效率：GLM 每 query 调用更少（9.5 vs 15），但延迟更高，总耗时反而更长。
- 本次 1800 配额跑了 179/200 query；剩余 21 可用新配额续跑（query 级 checkpoint 已持久化）。
- **新增工程能力**：LLM 端点配置文件化（claude/deepseek 可切，凭据不进版本库）、query 级断点续跑、配额软上限 + 连续失败熔断双保险。
