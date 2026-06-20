# store-provenance Specification

## Purpose
TBD - created by archiving change edge-extension-model. Update Purpose after archive.
## Requirements
### Requirement: 存储库记录建库出处

持久化存储 SHALL 记录建库出处元信息：`schema_version`、已挂扩展名集（点 + 边扩展 `get_name()` 排序后序列化），MUST NOT 再记录 `relation_model`（已删除）。该元信息 MUST 在建库时写入、随库持久化。内存 store 无持久化，本要求对其为 no-op（接口一致即可）。

#### Scenario: 建库写入出处（无 relation_model）

- **WHEN** 以扩展集 `{source_tracking, summary}` 建库
- **THEN** 库中 MUST 持久化 `schema_version`、扩展名集；MUST NOT 含 `relation_model` 出处

#### Scenario: 内存 store no-op

- **WHEN** 使用 `InMemoryStore`
- **THEN** provenance 记录 MUST 为 no-op，且 MUST NOT 报错

---

### Requirement: 开库补齐附加列（保证放行后可写）

`CREATE TABLE IF NOT EXISTS` 对既存表是 no-op、不会为旧库追加新列。为使"放行旧库"后仍可写，系统打开持久化库时 SHALL 检测必需的附加列是否存在，缺失则以 `ALTER TABLE ... ADD COLUMN` 补齐。本变更引入的附加列为 `edges.extensions_json`。补列 MUST 在任何读写之前完成。

#### Scenario: 旧库缺 extensions_json 列则补齐

- **WHEN** 打开一个 `edges` 表无 `extensions_json` 列的旧库
- **THEN** 系统 MUST 检测到缺列并 `ALTER TABLE edges ADD COLUMN extensions_json TEXT`

#### Scenario: 补列后可正常写入

- **WHEN** 旧库补列 + 补出处后执行写入（含 `extensions_json` 的 INSERT）
- **THEN** 写入 MUST 成功；MUST NOT 抛 `OperationalError: table edges has no column named extensions_json`

#### Scenario: 新建库不重复补列

- **WHEN** 新建库（`CREATE TABLE` 已含 `extensions_json`）
- **THEN** 补列检测 MUST 识别列已存在、不重复 ALTER、不报错

