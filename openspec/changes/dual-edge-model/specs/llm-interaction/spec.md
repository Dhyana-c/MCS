## MODIFIED Requirements

### Requirement: purpose 枚举固定且与流程位置对应

The `purpose` parameter SHALL be one of a fixed set of named purposes. Phase 1 MUST support at least: `extract_concepts`, `judge_relations`, `decide_directions`, `decide_hub`, `navigate_hub`, `arbitrate`, `synthesize`, `gen_aliases`, `gen_summary`, `select_facts`, `select_nodes`.

#### Scenario: purpose 列表包含 select_facts

- **WHEN** 检查 LLMInterface 与文档
- **THEN** `select_facts` MUST 被明确定义为独立 purpose；其渲染 MUST 将候选节点和浮现的关系边统一编号平铺为事实条目

#### Scenario: 未注册的 purpose 报错

- **WHEN** 调用方传入未注册的 `purpose` 字符串
- **THEN** 框架 MUST 抛出明确错误（未知 purpose），不静默回退

#### Scenario: purpose 决定 prompt 与渲染

- **WHEN** 同样的 `nodes_in` 被以不同 purpose 调用
- **THEN** ContextRenderer 渲染出的内容 MUST 可能不同；prompt 模板 MUST 不同

---

## ADDED Requirements

### Requirement: select_facts 渲染为统一编号的事实条目

`ContextRenderer` SHALL 提供 `render_facts(nodes: list[Node], edges: list[Edge]) -> str` 方法，将候选节点和浮现的关系边统一编号平铺。节点渲染为 `① name (id=xxx)\n  content...`，关系边渲染为 `② source_name —label→ target_name`。`select_facts` prompt 模板 MUST 指导 LLM 返回编号列表。

#### Scenario: 节点事实条目格式

- **WHEN** 渲染候选节点 FTX审判
- **THEN** 输出 MUST 为 `① FTX审判 (id=xxx)\n  FTX审判是针对SBF的欺诈案件...` 格式（带编号）

#### Scenario: 关系边事实条目格式

- **WHEN** 渲染关系边 `(FTX事件, relationship, "涉及", FTX审判)`
- **THEN** 输出 MUST 为 `③ FTX事件 —涉及→ FTX审判` 格式（带编号，紧跟节点条目之后）

#### Scenario: 无关系边时只有节点条目

- **WHEN** 已选节点和候选节点之间无关系边
- **THEN** 事实列表 MUST 只含节点条目，无边条目

#### Scenario: select_facts prompt 指导返回编号

- **WHEN** LLM 调用 `purpose="select_facts"`
- **THEN** user prompt MUST 要求 LLM "返回相关事实的编号列表，如 [1, 3, 4]"

#### Scenario: select_facts parser 返回编号列表

- **WHEN** LLM 返回 `[1, 3, 4]`
- **THEN** parser MUST 返回 `list[int]`（编号列表），框架根据编号映射回对应的节点或边

---

### Requirement: judge_relations 输出边 label

`judge_relations` prompt MUST 指导 LLM 为每个方向的语义边输出粗粒度 label。Decision 的 `edges_to` 字段 MUST 从 `list[str]`（目标 ID 列表）变为 `list[dict]`，每项含 `target_id` 和 `label`。

#### Scenario: edges_to 含 label

- **WHEN** `judge_relations` LLM 返回 create 决策
- **THEN** `edges_to` MUST 为 `[{"target_id": "...", "label": "涉及"}, ...]` 格式

#### Scenario: 双向边 label 独立

- **WHEN** 概念 A 和 B 之间有双向关系
- **THEN** A→B 的 label 和 B→A 的 label MUST 独立确定，MAY 不同

#### Scenario: label 为短词组

- **WHEN** LLM 输出 edge label
- **THEN** label MUST 为 1-4 字的短词组，MUST NOT 为完整句子
