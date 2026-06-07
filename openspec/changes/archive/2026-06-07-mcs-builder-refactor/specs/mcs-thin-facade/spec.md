## ADDED Requirements

### Requirement: MCS 类只暴露双管线和定向插件管理

`MCS` 类 SHALL 只暴露以下公共方法：
- `ingest(text: str, **metadata) -> WriteContext`：执行写入管线
- `query(text: str, existing_context: list | None = None) -> Any`：执行查询管线
- `show() -> str`：以 Markdown 流程图展示双管线插件注册与处理流程
- `register_plugin(plugin: Plugin, target: Literal["writer", "reader"]) -> None`：向指定管线注册插件
- `register_shared_plugin(plugin: Plugin) -> None`：将同一插件实例注册到双管线
- `unregister_plugin(name: str, target: Literal["writer", "reader"]) -> None`：从指定管线注销插件
- `shutdown() -> None`：关闭所有插件和存储资源

MCS MUST NOT 持有 `MCSConfig` 实例，MUST NOT 有 `initialize()` 方法。

#### Scenario: MCS 构造不接受 Config

- **WHEN** 检查 `MCS.__init__` 的参数签名
- **THEN** MUST NOT 包含 `config: MCSConfig` 参数
- **AND** MUST 接受 `write_pipeline`, `query_engine`, `store`, `write_manager`, `read_manager` 参数

#### Scenario: ingest 调用写入管线

- **WHEN** 调用 `mcs.ingest("some text")`
- **THEN** MUST 委托给内部的 `write_pipeline.ingest()`
- **AND** 返回 `WriteContext`

#### Scenario: query 调用查询管线

- **WHEN** 调用 `mcs.query("some query")`
- **THEN** MUST 委托给内部的 `query_engine.query()`
- **AND** 返回 `List[Node]` 或后处理链的输出类型

---

### Requirement: 插件注册必须指定目标管线

`register_plugin()` 和 `unregister_plugin()` 方法 SHALL 接受 `target` 参数，值为 `"writer"` 或 `"reader"`。

#### Scenario: 向 writer 注册插件

- **WHEN** 调用 `mcs.register_plugin(plugin, target="writer")`
- **THEN** 插件 MUST 只注册到 `write_manager`
- **AND** `read_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: 向 reader 注册插件

- **WHEN** 调用 `mcs.register_plugin(plugin, target="reader")`
- **THEN** 插件 MUST 只注册到 `read_manager`
- **AND** `write_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: 注销插件需指定管线

- **WHEN** 调用 `mcs.unregister_plugin("alias_entry", target="reader")`
- **THEN** 只从 `read_manager` 移除插件
- **AND** 若同名插件存在于 `write_manager`，MUST NOT 受影响

---

### Requirement: 共享插件便捷注册

`register_shared_plugin()` 方法 SHALL 将同一插件实例注册到 `write_manager` 和 `read_manager` 两侧。

#### Scenario: 共享插件注册到两侧

- **WHEN** 调用 `mcs.register_shared_plugin(plugin)`
- **THEN** 插件 MUST 注册到 `write_manager`
- **AND** 插件 MUST 注册到 `read_manager`
- **AND** `write_manager.get_by_name(plugin.get_name()) is read_manager.get_by_name(plugin.get_name())` MUST 为 True

#### Scenario: 共享插件不触发跨 manager 重复检查

- **WHEN** 同一插件实例通过 `register_shared_plugin()` 注册
- **THEN** MUST NOT 抛出 ValueError（跨 manager 的同名注册是允许的）
- **AND** 若同一 manager 内已有同名插件，MUST 抛出 ValueError（单 manager 内去重）

---

### Requirement: shutdown 去重关闭共享插件

`shutdown()` 方法 SHALL 确保共享插件实例只被关闭一次，避免同一实例被两个 manager 各关闭一次。

#### Scenario: 共享插件只 shutdown 一次

- **WHEN** 插件 P 同时注册在 `write_manager` 和 `read_manager`（同一实例）
- **AND** 调用 `mcs.shutdown()`
- **THEN** P 的 `shutdown()` 方法 MUST 只被调用一次

#### Scenario: 非共享插件各关闭一次

- **WHEN** 插件 A 只在 `write_manager`，插件 B 只在 `read_manager`
- **AND** 调用 `mcs.shutdown()`
- **THEN** A 和 B 的 `shutdown()` 方法 MUST 各被调用一次

---

### Requirement: show 方法以 Markdown 流程图展示双管线

`show()` 方法 SHALL 返回 Markdown 格式字符串，包含 writer 和 reader 两条管线的处理阶段和已注册插件。

#### Scenario: show 返回 Mermaid 流程图

- **WHEN** 调用 `mcs.show()`
- **THEN** 返回的字符串 MUST 包含 Mermaid `flowchart TD` 代码块
- **AND** 包含 writer 管线的 7 个阶段
- **AND** 包含 reader 管线的 5 个阶段

#### Scenario: show 列出各管线已注册插件

- **WHEN** 调用 `mcs.show()`
- **THEN** 返回的字符串 MUST 列出 write_manager 中注册的所有插件名称和类型
- **AND** MUST 列出 read_manager 中注册的所有插件名称和类型

---

### Requirement: 移除 persist_full 和 load-on-startup

MCS 类 MUST NOT 有 `persist_full()` 方法或 `_try_load_from_storage()` 方法。

#### Scenario: 用户直接操作 Store

- **WHEN** 用户需要全量持久化
- **THEN** MUST 调用 `mcs.store.save_full()` 而非 `mcs.persist_full()`

#### Scenario: load-on-startup 由 Builder 执行

- **WHEN** Builder 完成 build()
- **THEN** 若 Store 为空且 SQLiteStore 可用，MUST 已从存储加载数据
- **AND** 用户无需调用任何加载方法
