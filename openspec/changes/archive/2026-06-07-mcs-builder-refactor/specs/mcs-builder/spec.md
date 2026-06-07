## MODIFIED Requirements

### Requirement: MCSBuilder 抽象基类定义构建契约

`MCSBuilder` SHALL 作为抽象基类定义在 `mcs/core/builder.py`，只依赖 `MCSConfig` 和 `Plugin` 类型。它 SHALL 提供 `build() -> MCS` 方法，封装从配置到完成态 MCS 的完整构建流程（不再委托 `MCS.initialize()`）。

#### Scenario: Builder 只依赖 core 类型

- **WHEN** 检查 `mcs/core/builder.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST 只导入 `mcs/core/` 下的模块，MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`

#### Scenario: Builder 构建完成态 MCS 实例

- **WHEN** 调用 `builder.build()` 返回 MCS 实例
- **THEN** 返回的实例 MUST 已完成全部初始化，可直接调用 `ingest()` 和 `query()`
- **AND** MUST NOT 有 `initialize()` 方法可调用

#### Scenario: Builder 从 shared/write/read 收集注册表

- **WHEN** `MCSBuilder._collect_registry()` 被调用
- **THEN** MUST 合并 `config.shared_plugins`、`config.write_plugins`、`config.read_plugins` 以及 `write_llm`/`read_llm` 中的所有插件名称，返回完整的名称→类映射

---

## REMOVED Requirements

### Requirement: Builder 委托 MCS.initialize()

**Reason**: Builder 现在直接在 build() 中完成全部初始化，MCS 不再有 initialize() 方法。

**Migration**: 所有 `MCS(config).initialize()` 调用改为 `Builder(config).build()`。