# preprocess-plugin Specification

## Purpose
定义前置插件接口，用于查询和写入管线的文本预处理。与后置插件分离，提供类型安全的挂载点。

## Requirements

### Requirement: PreprocessPluginInterface 继承 Plugin 并返回 PREPROCESS 类型

The system SHALL define `PreprocessPluginInterface` inheriting `Plugin`, with `get_type()` returning `PluginType.PREPROCESS`, and an abstract `preprocess(text: str, ctx) -> str` method. `execute()` SHALL delegate to `preprocess()`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 PreprocessPlugin
- **THEN** 子类 MUST 提供 `preprocess` 方法；`preprocess` MUST 返回 `str`；`get_type()` MUST 返回 `PluginType.PREPROCESS`

#### Scenario: 链式调用语义

- **WHEN** 配置多个 PreprocessPlugin [P1, P2, P3]
- **THEN** 框架 MUST 调用 P1(text) → P2(P1输出) → P3(P2输出)；返回 P3 的输出

#### Scenario: 空链返回原文

- **WHEN** 未配置任何 PreprocessPlugin
- **THEN** 框架 MUST 返回原始输入文本

---

### Requirement: PluginType 枚举包含 PREPROCESS

The system SHALL include `PREPROCESS = "preprocess"` in the `PluginType` enum defined in `mcs/core/plugin.py`.

#### Scenario: 按类型查找前置插件

- **WHEN** 调用 `plugin_manager.get_all(PluginType.PREPROCESS)`
- **THEN** 返回值 MUST 是所有注册的 PREPROCESS 类型插件

---

### Requirement: 查询管线阶段 ① 使用 PreprocessPlugin 类型

The system SHALL modify `QueryEngine._run_preprocess` to use `plugin_manager.get_all(PluginType.PREPROCESS)` for locating preprocess plugins, instead of filtering `PostprocessPlugin` by `position` attribute.

#### Scenario: 不再依赖 position 属性

- **WHEN** 检查 `_run_preprocess` 实现
- **THEN** 代码 MUST NOT 包含 `getattr(p, "position", ...) == "query_preprocess"` 逻辑

#### Scenario: 前置插件与后置插件类型分离

- **WHEN** 同时配置前置插件和后置插件
- **THEN** 框架 MUST 分别通过 `PluginType.PREPROCESS` 和 `PluginType.POSTPROCESS` 查找，两者互不干扰

---

### Requirement: 写入管线阶段 ① 使用 PreprocessPlugin 类型

The system SHALL modify `WritePipeline._run_preprocess` to use `plugin_manager.get_all(PluginType.PREPROCESS)` for locating preprocess plugins, instead of filtering `PostprocessPlugin` by `position` attribute.

#### Scenario: 不再依赖 position 属性

- **WHEN** 检查写入管线 `_run_preprocess` 实现
- **THEN** 代码 MUST NOT 包含 `getattr(p, "position", ...) == "write_preprocess"` 逻辑

#### Scenario: 写入前置插件接收文本

- **WHEN** 写入管线执行阶段 ①
- **THEN** 每个 PreprocessPlugin 的输入和输出 MUST 是 `str` 类型
