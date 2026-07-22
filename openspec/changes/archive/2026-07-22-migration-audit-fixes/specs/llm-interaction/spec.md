# llm-interaction Delta

> migration-audit-fixes：C2 删 purpose 枚举里的 `arbitrate`（已随 retire-framework-query-pipeline 退役——
> `LLMArbitrationPlugin` + `arbitrate` bundle 删除，仲裁功能由 agent 层 `adjudicate` purpose 表达）。
> 同步删除 `context_renderer._ALL_SUMMARY_PURPOSES = {"arbitrate"}` 死分支（result-rendering 隐含）。

## MODIFIED Requirements

### Requirement: purpose 枚举固定且与流程位置对应

`purpose` SHALL 为固定命名集合之一。Phase 1 MUST 至少支持：`extract_concepts`、`judge_relations`、`decide_directions`、`decide_hub`、`navigate_hub`、`synthesize`、`gen_aliases`、`gen_summary`、`select_facts_write`。**`arbitrate` purpose 已删除**（原 `LLMArbitrationPlugin` + `arbitrate` prompt bundle 随读查询编排退役——读查询改由记忆 agent 驱动；仲裁功能在 agent 层经 `adjudicate` purpose 表达，见 arbitrate 原语 delta）。**读侧 `select_facts` bundle 已删除**（仅留写侧 `select_facts_write`）。**agent 层 `MemoryStore` 调用的语义判断 purpose（`generalize` / `adjudicate` / `split` / `merge`）同样经统一入口 `call(purpose, nodes_in, free_args)`、注册于 `DEFAULT_PROMPTS`**——其中 `split` / `merge` 为概念拆分 / 合并 purpose，由 agent 工具内部加载节点 + 边后调用、产出结构化方案（`into[]/relation/edges[]` 或 `keep/absorb/merged_content`）；这些 purpose 不在 core 读写管线位置上，但服从同一统一签名、同一「system / template / parser 可覆盖」契约。

> ContextRenderer 的「全节点摘要」purpose 集合（`_ALL_SUMMARY_PURPOSES`）MUST NOT 再含 `arbitrate`（死分支随该 purpose 退役删除）；`_SUMMARY_PURPOSES`（`decide_directions` / `decide_hub` / `navigate_hub` / `extract_concepts`）保留——仍有活跃消费者。

#### Scenario: purpose 不含 arbitrate

- **WHEN** 检查 `DEFAULT_PROMPTS` 注册集合与 LLMInterface purpose 枚举
- **THEN** MUST NOT 含 `arbitrate` purpose（随 retire-framework-query-pipeline 退役删除）
- **AND** 仲裁功能 MUST 经 agent 层 `adjudicate` purpose 表达（`mcs_agent/memory.py` `_do_arbitrate` 调 `purpose="adjudicate"`）

#### Scenario: purpose 含 select_facts_write

- **WHEN** 检查 LLMInterface 与文档
- **THEN** `select_facts_write` MUST 被定义为独立 purpose（写路径窄召回）；其渲染 MUST 将候选节点与事实边统一编号平铺为事实条目
- **AND** 读侧 `select_facts` bundle MUST NOT 存在（仅留 `select_facts_write`）

#### Scenario: 未注册 purpose 报错

- **WHEN** 传入未注册 `purpose`
- **THEN** 框架 MUST 抛明确错误，不静默回退

#### Scenario: agent 层 split / merge purpose 经统一入口

- **WHEN** `MemoryStore.split_concept` / `merge_concepts` 调用 LLM
- **THEN** MUST 经统一 `call(purpose="split" | "merge", nodes_in, free_args)` 入口
- **AND** `split` / `merge` MUST 注册于 `DEFAULT_PROMPTS`（system / template / parser 三元组，用户可覆盖）
- **AND** MUST NOT 直接调用厂商 SDK
