# plugin-protocol Specification Delta

## ADDED Requirements

### Requirement: PluginType 枚举包含 PREPROCESS

The system SHALL include `PREPROCESS = "preprocess"` in the `PluginType` enum defined in `mcs/core/plugin.py`.

#### Scenario: 按类型查找前置插件

- **WHEN** 调用 `plugin_manager.get_all(PluginType.PREPROCESS)`
- **THEN** 返回值 MUST 是所有注册的 PREPROCESS 类型插件

---

### Requirement: 提供 PreprocessPluginInterface 用于前置处理

The system SHALL define `PreprocessPluginInterface` with abstract method `preprocess(text: str, ctx) -> str`. This interface MUST be used for both query and write pipeline stage ① (text preprocessing), separate from `PostprocessPluginInterface`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 PreprocessPlugin
- **THEN** 子类 MUST 提供 `preprocess` 方法；`preprocess` MUST 返回 `str`；`get_type()` MUST 返回 `PluginType.PREPROCESS`

#### Scenario: 链式调用语义

- **WHEN** 配置多个 PreprocessPlugin [P1, P2]
- **THEN** 框架 MUST 调用 P1(text) → P2(P1输出)；返回 P2 的输出

---

## REMOVED Requirements

### Requirement: PostprocessPluginInterface.position 属性

**Reason**: 前置处理和后置处理职责不同，应使用独立插件类型而非字符串属性区分。类型系统可静态约束挂载点，避免运行时错误。

**Migration**: 现有使用 `position="query_preprocess"` 或 `position="write_preprocess"` 的 PostprocessPlugin 需迁移为 `PreprocessPluginInterface`。方法签名从 `process(input: Any, ctx)` 改为 `preprocess(text: str, ctx)`。

#### Scenario: PostprocessPlugin 不再有 position 属性

- **WHEN** 检查 `PostprocessPluginInterface` 定义
- **THEN** MUST NOT 存在 `position` 属性或 `@property def position(self) -> str` 方法

#### Scenario: 管线不依赖 position 筛选

- **WHEN** 检查 `QueryEngine` 和 `WritePipeline` 的 `_run_preprocess` 方法
- **THEN** 代码 MUST NOT 包含 `getattr(p, "position", ...)` 相关逻辑
