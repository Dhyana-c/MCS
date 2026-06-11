## Why

全量 609 篇文档建图 + 1000 query 评测（`v4flash_full_v2`，tag `v0.1.0-multihop-609`）显示 hit@10=0.649、recall@10=0.438，34.9% 的 query 种子定位失败（`navigate_hub` 返回空）。根因是 `extract_concepts` 生成的概念 `content` 过于简略（平均 79 字，42% < 50 字），导致：① root 扇出 762（信息稀薄→每节点 token 少→裂变迟迟不触发），`navigate_hub` 从 762 个子节点选方向时信息严重不足；② `relation_hints` 被转为 `statements` 存入 `extensions`，但 `ContextRenderer` 完全不渲染 `statements`，查询时 LLM 看不到任何关系信息；③ `LexicalScorer` 是 `statements` 唯一消费者，rerank 只是后处理，无法解决种子定位问题。需要从根源上丰富概念描述、移除无效的 statements 机制。

## What Changes

- **丰富 `extract_concepts` prompt**：让 LLM 为每个概念生成 2-4 句自包含描述（含关键事实、关系、上下文），不再只写一句话定义。
- **简化 `judge_relations` prompt**：移除 `initial_statements` / `statement` / `attach_statement`，只保留 `merge` / `create` / `no_op` 三种动作。
- **简化 `write_pipeline` 决策分发**：移除 `_dispatch_attach`（`attach_statement` 变 no-op）；`_dispatch_merge` 不再追加 `initial_statements` 到 extensions，改为将 concept content 追加到目标节点 content；`_dispatch_create` 不再写入 statements。
- **简化 `LexicalScorer`**：移除 `extensions["statements"]["items"]` 读取，只从 `node.content` 提取词法 token。
- **标记 deprecated**：`decisions.py` 中 `attach_statement` 动作类型、`initial_statements` / `statement` 字段标记为 deprecated（字段保留，向后兼容）。

## Capabilities

### New Capabilities
（无）

### Modified Capabilities
- `write-pipeline`：阶段 ④ DecisionList 从 4 种动作（merge/create/attach_statement/no_op）简化为 3 种（merge/create/no_op）；`attach_statement` 变为 no-op 兼容动作；merge 时 concept content 追加到目标节点 content（替代写入 statements extensions）；create 时不再写入 `initial_statements`。
- `query-rerank`：`LexicalScorer` 从 `node.content + extensions.statements.items` 双源词法匹配，改为仅 `node.content` 单源（content 已包含全部关系信息）。

## Impact

- **代码**：
  - `mcs/prompts/extract_concepts.py`：重写 SYSTEM_PROMPT
  - `mcs/prompts/judge_relations.py`：移除 statement 相关字段
  - `mcs/core/write_pipeline.py`：移除 statements 写入逻辑，merge 追加 content
  - `mcs/plugins/postprocess/rerank.py`：LexicalScorer 移除 statements 读取
  - `mcs/core/decisions.py`：标记 deprecated
  - `tests/test_pipeline_write.py`：更新 merge / attach_statement 测试
- **数据**：已有图（`bench/multihop_rag/outputs/v4flash_full_v2/`）不动；新图需重建，root 扇出预期从 762 降至 <100。
- **文档**：`openspec/specs/write-pipeline/spec.md` 中 `attach_statement` 相关场景需标记为 deprecated 或移除。
