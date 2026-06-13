## MODIFIED Requirements

### Requirement: purpose 枚举固定且与流程位置对应

The `purpose` parameter SHALL be one of a fixed set of named purposes. Phase 1 MUST support at least: `extract_concepts`, `judge_relations`, `decide_directions`, `decide_hub`, `navigate_hub`, `arbitrate`, `synthesize`, `gen_aliases`, `gen_summary`, `select_nodes`, `select_nodes_batch`. The `select_nodes_batch` purpose SHALL use the `BATCH_USER_TEMPLATE` prompt template, separate from `select_nodes`.

#### Scenario: purpose 取值完整

- **WHEN** 检查 LLMInterface 与文档
- **THEN** 上述 11 个 purpose MUST 被明确定义；每个 MUST 对应到读/写流程中的一个具体调用位置

#### Scenario: 未注册的 purpose 报错

- **WHEN** 调用方传入未注册的 `purpose` 字符串
- **THEN** 框架 MUST 抛出明确错误（未知 purpose），不静默回退

#### Scenario: purpose 决定 prompt 与渲染

- **WHEN** 同样的 `nodes_in` 被以不同 purpose 调用
- **THEN** ContextRenderer 渲染出的内容 MUST 可能不同；prompt 模板 MUST 不同

#### Scenario: select_nodes_batch 有独立模板

- **WHEN** `_traverse` 批量扩展阶段调用 LLM
- **THEN** MUST 使用 `purpose="select_nodes_batch"` 和对应的 `BATCH_USER_TEMPLATE`；MUST NOT 通过 try/finally 动态替换 `select_nodes` 的模板

#### Scenario: select_nodes_batch 在初始化时注册

- **WHEN** LLM 适配器初始化
- **THEN** `select_nodes_batch` purpose 及其模板 MUST 在初始化时一次性注册；MUST NOT 在运行时动态换装
