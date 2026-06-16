## ADDED Requirements

### Requirement: 存储库记录建库出处

持久化存储 SHALL 记录建库出处元信息：`relation_model`、`schema_version`、已挂扩展名集（点 + 边扩展 `get_name()` 排序后序列化）。该元信息 MUST 在建库时写入、随库持久化。内存 store 无持久化，本要求对其为 no-op（接口一致即可）。

#### Scenario: 建库写入出处

- **WHEN** 以 `relation_model="property_graph"` + 扩展集 `{source_tracking, summary}` 建库
- **THEN** 库中 MUST 持久化 `relation_model`、`schema_version`、扩展名集

#### Scenario: 内存 store no-op

- **WHEN** 使用 `InMemoryStore`
- **THEN** provenance 记录 MUST 为 no-op，且 MUST NOT 报错

---

### Requirement: 开库出处校验（relation_model 硬拒、扩展集告警）

打开已存在的库时，系统 SHALL 在任何读写之前校验出处：

- `relation_model` **不一致** → MUST **拒绝**打开（抛配置类错误），MUST NOT 静默打开——防混库静默损坏（宪法：混库为未定义行为）。这是唯一硬拒条件。
- 扩展名集**变化**（新增 / 移除）→ MUST 仅记 WARNING、放行。MUST NOT 因扩展集差异拒绝——opt-in 插件本就时挂时不挂，新增 / 移除扩展是合法迁移（新字段取默认、旧 orphan 字段被忽略）。
- 出处**缺失**（旧库无元信息）→ MUST 视为 legacy，按当前配置补写出处 + 记 WARNING、放行（MUST NOT 破坏既有库）。

#### Scenario: relation_model 不一致则拒绝

- **WHEN** 库出处记 `relation_model="attribute_node"`，当前配置为 `property_graph`
- **THEN** 系统 MUST 抛配置类错误拒绝打开；MUST NOT 静默以当前模式读写

#### Scenario: 扩展集变化仅告警

- **WHEN** 库出处记扩展集 `{source_tracking, summary}`，当前配置为 `{source_tracking, summary, my_edge_ext}`（新增一个）
- **THEN** 系统 MUST 记 WARNING 并放行；MUST NOT 拒绝

#### Scenario: 出处缺失则补写放行

- **WHEN** 打开一个无出处元信息的旧库
- **THEN** 系统 MUST 按当前配置补写出处、记 WARNING、放行；MUST NOT 拒绝或清空既有数据

#### Scenario: 校验先于读写

- **WHEN** 库被装配 / 初始化
- **THEN** 出处校验 MUST 发生在任何节点 / 边读写之前

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
