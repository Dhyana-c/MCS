## ADDED Requirements

### Requirement: 抽取产物语言跟随输入

ingest 阶段 ③（概念提取）与 ④（关系判定）的 LLM 产出——`ConceptDraft.name` / `ConceptDraft.content`、`Decision` 的概念字段——MUST 跟随 ingest 输入文本的**原文语言**；对输入中出现的实体（含在通用知识里有其他语言名称的知名实体，如 `Apple` / `Tesla` / `Google`）MUST NOT 翻译。此要求由 `extract_concepts` / `judge_relations` 的 prompt 语言跟随指令与 `node_class` 枚举英化共同实现。

#### Scenario: 英文语料产出英文节点

- **WHEN** ingest 一段含 `Apple` / `Tesla` / `Google` 等知名英文实体的英文文本
- **THEN** 落图中对应概念节点的 `name` / `content` MUST 为英文
- **AND** MUST NOT 出现 `苹果公司` / `特斯拉` / `谷歌` 等中文译名节点

#### Scenario: 中文语料行为不变

- **WHEN** ingest 中文文本（如 `golden_cage` 风格语料）
- **THEN** 落图节点的 `name` / `content` MUST 为中文
- **AND** 抽取 / 连边行为 MUST 与本次修复前逐字等价（回归）

#### Scenario: 无中文锚实体保持原文

- **WHEN** 英文文本含 LLM 训练知识里无中文译名的实体（如人名 `Sergey Brin`、缩写 `FTX`）
- **THEN** 对应节点 MUST 保持原文语言

#### Scenario: 关系判定不引入翻译

- **WHEN** `judge_relations` 对英文 `ConceptDraft` 判定关系并产出命题节点
- **THEN** 命题节点的 `content` MUST 为英文
- **AND** `Decision.reason` 等自由文本字段 SHOULD 跟随输入语言
