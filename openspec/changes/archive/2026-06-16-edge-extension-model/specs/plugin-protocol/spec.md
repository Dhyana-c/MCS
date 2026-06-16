## ADDED Requirements

### Requirement: 提供 EdgeExtensionInterface 用于边数据扩展

The system SHALL define `EdgeExtensionInterface` inheriting `Plugin`, mirroring `NodeExtensionInterface`: `get_type()` returns `PluginType.EDGE_EXTENSION`; abstract `schema() -> dict`、`default() -> Any`、`serialize(data) -> dict`、`deserialize(data) -> Any`；optional `render(edge, purpose) -> str | None`（default `None`）；`execute()` SHALL raise `NotImplementedError`. 插件 `get_name()` SHALL serve as the key in `edge.extensions`。

#### Scenario: 接口最小契约

- **WHEN** 实现一个 EdgeExtensionPlugin
- **THEN** 子类 MUST 提供 `schema / default / serialize / deserialize`；`get_type()` MUST 返回 `PluginType.EDGE_EXTENSION`；未覆写 `render` 时 MUST 返回 `None`

#### Scenario: render 带 purpose 参

- **WHEN** 框架渲染一条边并调用某边扩展的 `render`
- **THEN** MUST 以 `render(edge, purpose)` 形式调用（purpose 来自当前渲染场景），使扩展能按 purpose 决定是否贡献

#### Scenario: 按类型查找

- **WHEN** 调用 `plugin_manager.get_all(PluginType.EDGE_EXTENSION)`
- **THEN** 返回值 MUST 是所有已注册的 `EDGE_EXTENSION` 类型插件

---

### Requirement: PluginType 增 EDGE_EXTENSION 取值

`PluginType` 枚举 SHALL 增取值 `EDGE_EXTENSION = "edge_extension"`，与既有 `NODE_EXTENSION` 并列。

#### Scenario: 枚举取值存在

- **WHEN** 检查 `PluginType`
- **THEN** MUST 含 `EDGE_EXTENSION`，其值为 `"edge_extension"`

---

### Requirement: 字段级可见性判定规则（点 / 边一致）

`NodeExtensionInterface.render(node, purpose)` 与 `EdgeExtensionInterface.render(edge, purpose)` SHALL 共用同一**可见性判定规则**：返回片段=该字段在此 purpose 下渲染；返回 `None`=隐藏、MUST NOT 进入渲染文本。

此"一致"仅指**渲染时的可见性判定规则**一致，**不**意味着点 / 边在 token 估算中都计入可见扩展：守门估算（`estimate_node`）当前刻意 `extensions=None`、不计节点扩展贡献，且守门不渲染 / 不估算关系边；本变更 MUST NOT 改变此现状。可见扩展与估算的一致性仅在被 token 预算的**查询侧**视图中要求（见 `edge-extension-model` "边渲染 / 估算的查询侧一致性"）。

#### Scenario: render 返回 None 即隐藏

- **WHEN** 某扩展的 `render(..., purpose)` 返回 `None`
- **THEN** ContextRenderer MUST NOT 渲染该字段

#### Scenario: 一致仅指判定规则、非估算口径

- **WHEN** 比较节点扩展与边扩展的可见性语义
- **THEN** 两者 MUST 采同一规则（片段=可见、`None`=隐藏）；框架 MUST NOT 据此推断"守门估算须计入扩展贡献"——守门 `estimate_node` 不计节点扩展、且不估算关系边，本变更不改此现状
