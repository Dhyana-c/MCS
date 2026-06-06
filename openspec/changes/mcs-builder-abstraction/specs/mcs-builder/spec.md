## ADDED Requirements

### Requirement: MCSBuilder 抽象基类定义构建契约

`MCSBuilder` SHALL 作为抽象基类定义在 `mcs/core/builder.py`，只依赖 `MCSConfig` 和 `Plugin` 类型。它 SHALL 提供 `build() -> MCS` 方法，封装从配置到初始化完成的整个构建流程。

#### Scenario: Builder 只依赖 core 类型

- **WHEN** 检查 `mcs/core/builder.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST 只导入 `mcs/core/` 下的模块，MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`

#### Scenario: Builder 构建完整 MCS 实例

- **WHEN** 调用 `builder.build()` 返回 MCS 实例
- **THEN** 返回的实例 MUST 已完成 `initialize()`，可直接调用 `ingest()` 和 `query()`

### Requirement: MCSBuilder 通过抽象方法查找插件类

`MCSBuilder` SHALL 定义抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`，由子类实现具体插件查找逻辑。`build()` SHALL 通过此方法为每个 `config.plugins` 名称查找对应插件类。

#### Scenario: 插件类查找委托给子类

- **WHEN** `MCSBuilder.build()` 处理 `config.plugins` 列表中的每个名称
- **THEN** MUST 调用 `self.get_plugin_class(name)` 查找插件类
- **AND** 返回 None 的名称 MUST 被跳过（与当前行为一致）

#### Scenario: 子类实现具体查找

- **WHEN** 实现 `Phase1Builder` 子类
- **THEN** `get_plugin_class(name)` MUST 返回 Phase1 插件注册表中对应的类

### Requirement: MCS 类接受插件注册表注入

`MCS.__init__()` SHALL 接受 `plugin_registry: dict[str, type[Plugin]] | None` 参数。当提供注册表时，`initialize()` SHALL 使用此注册表而非硬编码的默认注册表。

#### Scenario: 注入自定义注册表

- **WHEN** 创建 `MCS(config, plugin_registry=my_registry)`
- **THEN** `initialize()` MUST 使用 `my_registry` 查找插件类

#### Scenario: 默认注册表行为

- **WHEN** 创建 `MCS(config)` 不提供 `plugin_registry`
- **THEN** MUST 使用空注册表（依赖 `register_plugin()` 手动添加，或由 Builder 注入）

### Requirement: MCS 类位于 mcs/core/mcs.py

`MCS` 类 SHALL 定义在 `mcs/core/mcs.py`，而非 `mcs/__init__.py`。`mcs/__init__.py` SHALL 从 `mcs.core.mcs` 导入并导出 `MCS`。

#### Scenario: 导入路径变更

- **WHEN** 检查 `mcs/core/mcs.py`
- **THEN** MUST 包含 `class MCS` 定义，与原 `mcs/__init__.py` 中的定义一致（除注册表注入变更）

#### Scenario: 向后兼容导出

- **WHEN** 使用 `from mcs import MCS`
- **THEN** MUST 正常工作，返回 `mcs.core.mcs.MCS` 类