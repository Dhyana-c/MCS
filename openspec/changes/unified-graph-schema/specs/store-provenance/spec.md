# store-provenance（delta）

> `relation_model` 删除后，出处不再记录 / 校验它（单一模型无"混库"之分）。`schema_version` + 扩展名集出处保留。"开库出处校验（relation_model 硬拒）"移除；如需 schema 版本硬拒，另立（留实现）。

## MODIFIED Requirements

### Requirement: 存储库记录建库出处

持久化存储 SHALL 记录建库出处元信息：`schema_version`、已挂扩展名集（点 + 边扩展 `get_name()` 排序后序列化），MUST NOT 再记录 `relation_model`（已删除）。该元信息 MUST 在建库时写入、随库持久化。内存 store 无持久化，本要求对其为 no-op（接口一致即可）。

#### Scenario: 建库写入出处（无 relation_model）

- **WHEN** 以扩展集 `{source_tracking, summary}` 建库
- **THEN** 库中 MUST 持久化 `schema_version`、扩展名集；MUST NOT 含 `relation_model` 出处

## REMOVED Requirements

### Requirement: 开库出处校验（relation_model 硬拒、扩展集告警）

**原因**：`relation_model` 删除，单一模型不存在跨模式混库，该硬拒条件失效。`schema_version` 不兼容的硬拒（如需要）应另立独立要求，不再绑定 relation_model。
