# estimate-memoization Specification

## Purpose

为查询期 token 估算提供缓存机制，避免对同一节点重复计算 render token 开销。同时将 _traverse 的 used_tokens 维护从全量重算改为增量累加，提升遍历性能。缓存仅用于查询路径，写路径因节点内容变更不得使用。

## Requirements

### Requirement: estimate_node 支持可选缓存

`TokenBudget.estimate_node` SHALL 接受可选 `cache: dict[str, int] | None` 参数。当 cache 非空时，MUST 先以 `node.id` 查缓存；命中则直接返回缓存值；未命中则调用 `render_node_full` 计算后写入缓存并返回。当 cache 为 None 时，行为与原来完全一致（每次完整计算）。

#### Scenario: 缓存命中直接返回

- **WHEN** `estimate_node(node, cache={"n1": 42})` 且 `node.id == "n1"`
- **THEN** MUST 返回 42，MUST NOT 调用 `render_node_full`

#### Scenario: 缓存未命中时计算并缓存

- **WHEN** `estimate_node(node, cache={})` 且 `node.id == "n2"`
- **THEN** MUST 调用 `render_node_full` 计算值 V，写入 `cache["n2"] = V`，返回 V

#### Scenario: 无缓存时行为不变

- **WHEN** `estimate_node(node)` 或 `estimate_node(node, cache=None)`
- **THEN** MUST 每次调用 `render_node_full`，与原来行为完全一致

---

### Requirement: _traverse 使用增量 used_tokens 累加

`QueryEngine._traverse` SHALL 维护 `used_tokens: int` 变量，在节点被加入 `accumulated` 时增量累加 `estimate_node(node, cache)` 的返回值。MUST NOT 在每轮循环中重算 `sum(estimate_node(n) for n in accumulated)`。

#### Scenario: used_tokens 随节点加入递增

- **WHEN** 节点 N（估算 token=100）被加入 `accumulated`
- **THEN** `used_tokens` MUST 增加 100

#### Scenario: 不做全量重算

- **WHEN** 检查 `_traverse` 的 while 循环体
- **THEN** 代码 MUST NOT 包含 `sum(estimate_node(n) for n in accumulated)` 或等价全量重算逻辑

#### Scenario: 缓存在 _traverse 入口初始化

- **WHEN** `_traverse` 开始执行
- **THEN** MUST 初始化 `estimate_cache: dict[str, int] = {}` 并传递给后续所有 `estimate_node` 调用

---

### Requirement: estimate_node 缓存仅用于查询期

estimate_node 缓存 SHALL 仅在 `_traverse` 内部使用。写路径（`_guard_invariant`、`FanoutReducerPlugin` 等）MUST NOT 使用此缓存，因为写路径上节点内容会变更。

#### Scenario: 写路径不使用缓存

- **WHEN** `_guard_invariant` 调用 `estimate_node`
- **THEN** MUST NOT 传入 query 期的 cache dict

#### Scenario: 查询路径使用缓存

- **WHEN** `_traverse` 内部调用 `estimate_node`
- **THEN** MUST 传入 `_traverse` 初始化的 `estimate_cache`
