## Why

MCS 已在 multihop-rag（静态文档检索）和 golden_cage（null 诚实口径）上验证了核心能力，但这两个评测共享同一盲区：**无时间维度、无信息更新/覆盖、无用户-助手对话形态**。LoCoMo 补了对话形态和时间推理，但缺少两个关键能力：

1. **Knowledge Update**：用户信息被后续会话覆盖/失效——正面打 MCS 的互斥边 + arbitrate 裁决
2. **Abstention**：对历史中未提及的问题诚实弃答——与黄金笼 null 口径互补但场景不同（黄金笼是"语料中无答案"，这里是"用户历史中未提及"）

LongMemEval（ICLR 2025, arXiv:2410.10813）恰好覆盖这两个能力，且 6 类问题几乎为 MCS 的能力面定制：

| question_type | 数量 | MCS 对应能力 |
|--------------|------|-------------|
| temporal-reasoning | 133 | 事件层 + timeline 工具 |
| multi-session | 133 | BFS 语义游走 + agent 探索 |
| knowledge-update | 78 | 互斥边 + arbitrate 裁决 |
| single-session-user | 70 | 基础信息抽取 |
| single-session-assistant | 56 | 助手信息记忆 |
| single-session-preference | 30 | 偏好抽取（rubric 评分） |
| abstention (_abs 后缀) | 30 | null 诚实口径 |

**成本分析**：Oracle 版每题平均 ~6.6K token（仅证据会话），S 版每题 ~115K token（含填充会话）。Oracle 版 ingest 成本可控（500 题 × ~6.6K = ~3.3M token），可作为首期；S 版留 Phase 2。

## What Changes

- 新增 `bench/longmemeval/` 评测框架：LongMemEval 端到端对话记忆评测
- 新增数据拉取脚本：从 HuggingFace 下载 oracle / S / M 版数据
- 新增数据预处理：解析会话时间戳、拼接对话文本、按类型拆分问题
- 新增数据加载器：`LongMemEvalDataLoader`，加载 oracle / S 版
- 新增对话式 ingest 适配器：每会话 = 一次 `mcs.ingest()`，带时间戳
- 新增图隔离策略：每题一个独立 SQLite db（防跨题记忆泄漏）
- 新增评测双轨：
  - **检索轨**：`mcs.query()` / agent.search() → 检查 answer_session_ids 对应节点是否被召回 → Recall@k
  - **QA 轨**：agent.chat(question) → LLM 生成答案 → LLM judge 判对错
- 新增按问题类型的分项指标
- 新增与 Mem0/Zep 横向基线对比

## Capabilities

### New Capabilities
- `longmemeval-eval`: LongMemEval 对话记忆评测框架——数据拉取/预处理、对话式 ingest、图隔离、检索+QA 双轨评测、按类型分项指标

### Modified Capabilities
（无——不修改任何现有模块代码；建图走框架 ingest，不动 `bench/agent_build.py`，见 design D5）

## Impact

- 新增 `bench/longmemeval/` 目录（不影响现有核心代码）
- 数据下载到 `bench/longmemeval/data/`（oracle 已下载 15MB，S 版 277MB 待下载）
- **knowledge-update 类题**直接暴露互斥边 + arbitrate 的正确性——若互斥机制有 bug 会直接扣分
- **abstention 类题**测试"用户历史中未提及的信息能否诚实弃答"——与黄金笼"语料中无答案"互补
- **每题独立图**意味着 500 次 ingest + 500 次 query，成本高于 LoCoMo（10 次图 × 1986 题）
- LongMemEval 许可 MIT，无商业限制
