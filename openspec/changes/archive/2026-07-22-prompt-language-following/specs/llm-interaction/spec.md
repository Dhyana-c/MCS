## ADDED Requirements

### Requirement: 默认 prompt 语言跟随

每个 purpose 的默认 prompt（`system` + `template`）MUST 指示 LLM：其生成的自然语言文本（节点 `content` / 概括 / 摘要 / 别名 / 社区 `theme` / `summary` 等）MUST 使用**输入文本或被处理节点的原文语言**，MUST NOT 翻译——即使该实体在通用知识里有其他语言（如中文）的名称，也 MUST 保留原文语言表述。此要求覆盖所有产出自然语言文本的 purpose：`extract_concepts` / `extract_work_events` / `judge_relations` / `decide_hub` / `navigate_hub` / `synthesize` / `gen_aliases` / `gen_summary` / `gen_graph_summary` / `generalize` / `adjudicate` / `split` / `merge` / `merge_content`。

#### Scenario: 知名英文实体不翻译

- **WHEN** `extract_concepts` 处理一段含 `Apple` 的英文文本
- **THEN** 产出节点的 `name`/`content` MUST 为英文（如 `Apple` 及英文描述）
- **AND** MUST NOT 产出 `苹果公司` 或中文描述

#### Scenario: 生成类 prompt 跟随节点语言

- **WHEN** `decide_hub` 处理一个纯英文节点群（中心 + 一跳子节点均为英文）
- **THEN** 产出的社区 `theme` / `summary` MUST 为英文
- **AND** MUST NOT 产出中文 `theme`

#### Scenario: 混合语言逐实体保留原文

- **WHEN** 输入文本同时含中文实体与英文实体
- **THEN** 各实体节点 MUST 按其**原文语言**保留（中文实体中文、英文实体英文）
- **AND** MUST NOT 把英文实体翻译成中文、也不把中文实体翻译成英文

#### Scenario: gen_aliases 示例语言中立

- **WHEN** 审查 `gen_aliases` 的 `USER_TEMPLATE` 示例
- **THEN** 示例 MUST NOT 以中文译名作示范（如 `苹果公司`）
- **AND** MUST 使用不预设单一语言的示例形态

### Requirement: node_class 枚举英中映射

`extract_concepts` / `judge_relations` 的 prompt MUST 将 `node_class` 枚举值暴露为英文 `concept` / `fact`（而非中文 `概念` / `事实`）。对应的 parser MUST 把 `concept` 映射到 `CLASS_CONCEPT`、`fact` 映射到 `CLASS_FACT`，并 MUST **向后兼容**仍接受中文值 `概念` / `事实`（旧库 / 旧调用 / 旧测试不破）。**存储层 `node.node_class` 取值 MUST 不变**（仍为中文常量 `概念` / `事实`）——本次只改 prompt↔LLM 的协议字面值与 parser 翻译，非 BREAKING。

#### Scenario: prompt 暴露英文枚举

- **WHEN** 审查 `extract_concepts` / `judge_relations` 的 `SYSTEM_PROMPT` / `USER_TEMPLATE`
- **THEN** `node_class` 枚举字面值 MUST 为 `concept` / `fact`
- **AND** MUST NOT 为 `概念` / `事实`

#### Scenario: parser 英文值映射到中文常量

- **WHEN** parser 收到 LLM 输出的 `node_class="fact"`
- **THEN** MUST 映射为 `CLASS_FACT`（中文常量 `事实`）存入 `ConceptDraft` / `Decision`

#### Scenario: parser 向后兼容中文值

- **WHEN** parser 收到 LLM 输出的 `node_class="概念"`（中文，旧调用或 LLM 偶发）
- **THEN** MUST 仍接受并映射为 `CLASS_CONCEPT`
- **AND** MUST NOT 报错或回退为默认值而丢失语义

#### Scenario: 存储取值不变

- **WHEN** 节点经 ingest 落盘
- **THEN** `node.node_class` 的存储值 MUST 仍为中文常量（`概念` / `事实`）
- **AND** 既有读路径（载重过滤、`get_relations` 事件边过滤、universe 归属判定等基于 `node_class` 的逻辑）MUST 不受影响
