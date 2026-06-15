# MultiHop-RAG 检索评测报告（GLM-5.1 查询侧 · 全量 200 query）

**日期**：2026-06-15
**数据**：MultiHop-RAG（`yixuantt/MultiHop-RAG`），whole_doc 整篇摄入
**建图模型**：deepseek-chat（沿用 `chat_16k/graph.db`，**不重建图**）
**查询 + 文档重排模型**：GLM-5.1（经 Anthropic 兼容网关 `api.0ki.cn/api/anthropic`）
**token_budget T**：16000
**图库**：`bench/multihop_rag/outputs/chat_16k/graph.db`（复制到 `chat_16k_glm/` 隔离查询）

---

## 1. 实验目的

**换 read 侧 LLM**：建图仍用 deepseek-chat（图不变），仅查询 + 文档重排换成 GLM-5.1，观察查询阶段对模型的敏感度。

> 这是「换 read 模型」对比实验。与 deepseek 同图基线**模型不同**，指标仅作方向性对比（query 子集 n=200 相同，可比性较好）。

## 2. 执行与配额

| 项 | 值 |
|---|---|
| 目标 query | 200 |
| 实际完成 | **200 / 200**（分两批：首批 179 配额触发停，续跑补完 21） |
| 端点配额 | 1800 次/批 |
| 首批消耗 | 1708 / 1800（quota 软上限触发停） |
| 续跑消耗 | 206 次（配额重置后） |
| 总耗时 | 首批 3.08h + 续跑 31min |
| doc_rerank | llm（语义重排） |
| 续跑 | query 级 checkpoint（`results.jsonl`），跨 session 断点续跑 ✓ |

**停止/保护机制**：`llm.json` 的 `quota=1700` 软上限（**session 增量口径**：本次新增内部 LLM + 重排调用，不累积历史）+ 连续失败熔断（阈值 3）。首批由 quota 触发停；续跑跑满 200。

## 3. 检索质量（200 query · doc_rerank=llm · T=16000）

| 类型 | n | hit@2 | hit@4 | **hit@10** | recall@10 | map@10 | mrr@10 |
|---|---|---|---|---|---|---|---|
| **overall** | 200 | 0.580 | 0.635 | **0.765** | 0.487 | 0.309 | 0.528 |
| inference | 70 | 0.557 | 0.600 | 0.800 | 0.486 | 0.258 | 0.482 |
| comparison | 79 | 0.570 | 0.608 | 0.684 | 0.395 | 0.285 | 0.505 |
| temporal | 51 | 0.627 | 0.725 | **0.843** | 0.634 | 0.415 | 0.628 |

## 4. 与 deepseek-chat 同图基线对比（同 200 query 子集）

| 指标 | deepseek-chat | **GLM-5.1** | Δ |
|---|---|---|---|
| hit@10 | 0.770 | **0.765** | −0.005 |
| recall@10 | 0.484 | 0.487 | +0.003 |
| map@10 | 0.315 | 0.309 | −0.006 |
| mrr@10 | 0.551 | 0.528 | −0.023 |
| temporal hit@10 | 0.863 | 0.843 | −0.020 |
| inference hit@10 | 0.743 | **0.800** | **+0.057** |

> **结论**：GLM-5.1 在查询侧的检索质量**与 deepseek-chat 基本持平**（overall hit@10 0.765 vs 0.770，Δ−0.5pp，recall@10 甚至略高）。inference 类型 GLM 反超（+5.7pp）。换 read 模型对 MCS 检索质量影响很小——验证了「建图质量主导、查询侧模型可替换」的架构韧性。

## 5. 成本分析

| 项 | deepseek-chat | GLM-5.1 |
|---|---|---|
| 每 query 端点调用 | ~15（14 内部 + 1 重排） | **~9.6**（8.6 内部 + 1 重排） |
| 每 query 耗时 | ~22s | **~62s** |
| 200 query 总调用 | ~3000 | ~1914（首批 1708 + 续跑 206） |

GLM-5.1 每 query 的 LLM 调用数**少于** deepseek（9.6 vs 15，`select_facts` 更早收敛、遍历节点更少），但**单次延迟更高**（经中转网关 + `select_facts` 输入接近 T=16000 token），导致每 query 耗时反而更高（62s vs 22s）。

## 6. 复现

```bash
# 配置：bench/multihop_rag/config/llm.json（backend=claude, quota=1700；含凭据，已 gitignore）
python bench/multihop_rag/scripts/test.py \
  --output bench/multihop_rag/outputs/chat_16k_glm \
  --token-budget 16000 \
  --llm-config bench/multihop_rag/config/llm.json \
  --queries 200 --doc-rerank llm
# 配额耗尽自动停；换新配额后重跑同命令自动续跑剩余 query（session 增量配额计数）
```

## 7. 结论

- **GLM-5.1 作为查询侧 LLM 与 deepseek-chat 同档**（overall hit@10 0.765 vs 0.770），inference 类型反超。换 read 模型对 MCS 检索质量影响极小。
- 配额效率：GLM 每 query 调用更少（9.6 vs 15），但延迟更高，总耗时更长。
- 完整跑完 200 query（分两批，query 级 checkpoint 跨 session 续跑验证通过）。
- **新增工程能力**：LLM 端点配置文件化（claude/deepseek 可切，凭据不进版本库）、query 级断点续跑、配额软上限（session 增量口径）+ 连续失败熔断双保险。
