## MODIFIED Requirements

### Requirement: purpose 枚举固定且与流程位置对应

`purpose` SHALL 为固定命名集合之一。Phase 1 MUST 至少支持：`extract_concepts`、`judge_relations`、`decide_directions`、`decide_hub`、`navigate_hub`、`arbitrate`、`synthesize`、`gen_aliases`、`gen_summary`、`select_facts`。**agent 层 `MemoryStore` 调用的语义判断 purpose（`generalize` / `adjudicate` / `split` / `merge`）同样经统一入口 `call(purpose, nodes_in, free_args)`、注册于 `DEFAULT_PROMPTS`**——其中 `split` / `merge` 为本 change 新增（概念拆分 / 合并），由 agent 工具内部加载节点 + 边后调用、产出结构化方案（`into[]/relation/edges[]` 或 `keep/absorb/merged_content`）；这些 purpose 不在 core 读写管线位置上，但服从同一统一签名、同一「system / template / parser 可覆盖」契约。

#### Scenario: purpose 含 select_facts

- **WHEN** 检查 LLMInterface 与文档
- **THEN** `select_facts` MUST 被定义为独立 purpose；其渲染 MUST 将候选节点与事实边统一编号平铺为事实条目

#### Scenario: 未注册 purpose 报错

- **WHEN** 传入未注册 `purpose`
- **THEN** 框架 MUST 抛明确错误，不静默回退

#### Scenario: agent 层 split / merge purpose 经统一入口

- **WHEN** `MemoryStore.split_concept` / `merge_concepts` 调用 LLM
- **THEN** MUST 经统一 `call(purpose="split" | "merge", nodes_in, free_args)` 入口
- **AND** `split` / `merge` MUST 注册于 `DEFAULT_PROMPTS`（system / template / parser 三元组，用户可覆盖）
- **AND** MUST NOT 直接调用厂商 SDK
