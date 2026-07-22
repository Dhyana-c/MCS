## ADDED Requirements

### Requirement: 回答侧语言跟随（主动对齐）

`MemoryAgent` 的 system prompt MUST 包含语言跟随规则，要求 LLM：① 用**用户消息的语言**回答（英文问全程英文答、中文问中文答）；② 当记忆图节点内容与用户语言不一致时，引用其信息 MUST **转成用户语言转述**、不原文照搬；③ 不确定用户语言时 MUST **先据用户消息判断再作答**（主动对齐，而非被动转述）。该规则 MUST 追加在**任意** `system_prompt`（含调用方自定义的 `system_prompt`）之后，使 bench 覆盖 prompt 等自定义场景同样吃到。此要求由 `mcs_agent/loop.py` 的 `LANGUAGE_FOLLOW_PROMPT`（在 `_build_system` 中无条件追加）实现。

#### Scenario: 英文问英文答

- **WHEN** 用户以英文消息提问
- **THEN** agent 最终回复 MUST 为英文

#### Scenario: 中文问中文答

- **WHEN** 用户以中文消息提问
- **THEN** agent 最终回复 MUST 为中文

#### Scenario: 节点语言与用户语言不一致时转述

- **WHEN** 记忆图节点内容为中文，但用户以英文提问
- **THEN** 回复在引用该节点信息时 MUST 转成英文转述
- **AND** MUST NOT 原文照搬中文节点内容

#### Scenario: 语言跟随规则追加在自定义 prompt 之后

- **WHEN** 调用方传入自定义 `system_prompt` 构造 `MemoryAgent`
- **THEN** 语言跟随规则 MUST 仍被追加在该自定义 prompt 之后
- **AND** 自定义角色文本 MUST 出现在语言跟随规则之前
