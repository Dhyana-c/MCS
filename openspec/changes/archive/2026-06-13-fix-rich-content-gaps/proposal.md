## Why

ef2384d（rich-concept-content）修复了两个机制性缺陷——杀掉 statements 死路径、用内容变厚自然收敛 root 扇出——但引入三个未覆盖的风险：merge 后 content 无界增长、别名通道被收窄、缺少检索指标验证。同时 pending 的 perf-optimization-overhaul 提案有两处 spec 级问题（rerank 缓存与 merge content 冲突、重试退避只覆盖 deepseek）。这些问题必须在全量重建之前修复，否则一次 7h 建图的验证成本会被浪费在已知缺陷上。

## What Changes

### A. rich-concept-content 缺口修复

- **A1 merge content 压缩**：`_dispatch_merge` 追加 content 后，若 content 超过阈值（默认 500 字），触发一次 LLM 重写压缩（复用 `gen_summary` prompt 机制），替代当前纯追加 + 子串去重。压缩后 content 长度 ≤ 阈值，避免高频 merge 概念（如人名）的 content 持续膨胀吃掉遍历批次预算和注入词法重排噪声。
- **A2 别名富集恢复**：`judge_relations` prompt 恢复 `aliases_to_add` 字段——merge 时 LLM 可贡献额外别名（同义词、缩写、变体写法）。`Decision.aliases_to_add` 字段取消 deprecated 标记。`_dispatch_merge` 已有将 `aliases_to_add` 并入别名槽的逻辑，无需改动。
- **A3 200 篇子集 A/B 验证**：在 200 篇子集上对比 ef2384d 前后的 hit@10、alias 索引规模、候选召回率，确认 content 变厚 + 别名恢复不降检索质量。

### B. perf-optimization-overhaul 修正

- **B1 rerank token 缓存失效**：perf 提案任务 7 的 `LexicalScorer._token_cache` 以 `node_id` 为 key，但 `_dispatch_merge` 原地改写 `node.content` 后无失效步骤。改为以 `(node_id, content_hash)` 为 key，merge 改写 content 后 hash 自然变化，下次查询自动 miss → 重新分词。perf 提案中路径 `plugins/index/rerank.py` 修正为实际路径 `plugins/postprocess/rerank.py`。
- **B2 共享重试基类**：perf 提案任务 5 仅在 deepseek 适配器加重试。将退避重试提升为 `LLMInterface` 基类的共享方法 `_call_with_retry`（指数退避 + jitter），三个适配器（deepseek / claude / ollama）的 `_raw_call` 统一走此方法。

## Capabilities

### New Capabilities

- `merge-content-compaction`：merge 后 content 超阈值时触发 LLM 压缩重写，防止单节点 content 无界增长

### Modified Capabilities

- `write-pipeline`：`_dispatch_merge` 新增 content 压缩步骤；`judge_relations` prompt 恢复 `aliases_to_add` 字段
- `query-rerank`：`LexicalScorer._token_cache` key 从 `node_id` 改为 `(node_id, content_hash)` 以适配 merge 原地改写
- `llm-interaction`：`LLMInterface` 新增共享 `_call_with_retry` 方法，三适配器统一覆盖重试 + 退避 + jitter

## Impact

### 受影响代码

| 文件 | 变更类型 |
|------|----------|
| `core/write_pipeline.py` | `_dispatch_merge` 新增压缩步骤（复用 `gen_summary` 或新 prompt） |
| `core/decisions.py` | `Decision.aliases_to_add` 取消 deprecated 标记 |
| `prompts/judge_relations.py` | `SYSTEM_PROMPT` / `USER_TEMPLATE` 恢复 `aliases_to_add` 字段说明 |
| `interfaces/llm.py` | 新增 `_call_with_retry` 共享重试方法 |
| `plugins/llm/deepseek_llm.py` | `_raw_call` 改走 `_call_with_retry` |
| `plugins/llm/claude_llm.py` | `_raw_call` 改走 `_call_with_retry` |
| `plugins/llm/ollama_llm.py` | `_raw_call` 改走 `_call_with_retry` |
| `plugins/postprocess/rerank.py` | `LexicalScorer._token_cache` key 含 content hash |

### 依赖关系

- **前置依赖**：perf-optimization-overhaul 的任务 5（LLM 重试）和任务 7（rerank 缓存）——本 change 的 B1/B2 是对这两个任务的修正，应在实现时合并到 perf change 中
- **执行顺序**：perf change 全部实现完毕 → 本 change（A1+A2）→ 一起全量重建 → A3 验证

### 风险

- **content 压缩引入额外 LLM 调用**：每次 merge 超阈值多一次 `gen_summary` 调用——但只在阈值触发时，且 500 字阈值下大多数 merge 不触发
- **别名恢复可能让 merge prompt 输出稍长**：`aliases_to_add` 字段回到输出 schema——字段级影响可忽略
- **content_hash 计算**：每次 `LexicalScorer.score` 需算 hash——对短文本（< 1KB）用 `hash()` 即可，开销可忽略
