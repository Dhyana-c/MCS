## ADDED Requirements

### Requirement: merge 后 content 超阈值时自动 LLM 压缩

`_dispatch_merge` 在将 `concept.content` 追加到目标节点后，MUST 检查目标节点 `content` 长度是否超过配置阈值（默认 500 字）。超过时 MUST 调用 `gen_summary` purpose 对 content 进行 LLM 压缩重写，防止高频 merge 概念的 content 无界增长。

#### Scenario: merge 后 content 未超阈值

- **WHEN** `_dispatch_merge` 追加 content 后 `len(node.content) <= threshold`
- **THEN** write_pipeline MUST NOT 发起额外的 LLM 压缩调用
- **AND** `node.content` 保持追加后的原始值

#### Scenario: merge 后 content 超阈值触发压缩

- **WHEN** `_dispatch_merge` 追加 content 后 `len(node.content) > threshold`
- **THEN** write_pipeline MUST 调用 `gen_summary` purpose 对节点 content 进行压缩
- **AND** 压缩后的 `node.content` 长度 MUST <= threshold

#### Scenario: 压缩调用失败时不阻塞 merge

- **WHEN** content 压缩 LLM 调用抛出异常
- **THEN** write_pipeline MUST 记录 warning 日志并保留追加后的原始 content
- **AND** merge 流程 MUST 正常完成（不抛出异常）

#### Scenario: 压缩阈值可配置

- **WHEN** 配置中指定 `merge_content_threshold` 值
- **THEN** write_pipeline MUST 使用该值作为压缩触发阈值
- **AND** 默认值 MUST 为 500

#### Scenario: 压缩发生在索引更新之前

- **WHEN** content 压缩被触发
- **THEN** 压缩 MUST 在 `_notify_indexes` 调用之前完成
- **AND** 索引系统拿到的是压缩后的 content
