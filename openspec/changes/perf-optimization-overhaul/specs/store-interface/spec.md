## ADDED Requirements

### Requirement: SQLiteStore 维护反向邻接表

`SQLiteStore` SHALL 维护 `_reverse_adjacency: dict[str, set[str]]`，在 `add_edge` 和 `delete_edge` 时同步更新。`delete_node` 查找入边时 MUST 使用 `_reverse_adjacency` 而非遍历全图。

#### Scenario: add_edge 同步更新反向索引

- **WHEN** `add_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].add(B)` 和 `_reverse_adjacency[B].add(A)`

#### Scenario: delete_edge 同步更新反向索引

- **WHEN** `delete_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].discard(B)` 和 `_reverse_adjacency[B].discard(A)`

#### Scenario: delete_node 使用反向索引查找入边

- **WHEN** `delete_node(X)` 查找指向 X 的入边
- **THEN** MUST 仅遍历 `_reverse_adjacency.get(X, set())` 中的节点；MUST NOT 遍历 `self._adjacency` 的全部键

#### Scenario: load 时重建反向索引

- **WHEN** `SQLiteStore.load()` 从持久层加载图数据
- **THEN** MUST 在加载完成后重建 `_reverse_adjacency`，使其与 `_adjacency` 保持一致

---

### Requirement: StoreInterface 提供 add_bidirectional 辅助方法

`StoreInterface` SHALL 提供 `add_bidirectional(source_id: str, target_id: str) -> None` 方法，一次性添加两条单向边 `source→target` 和 `target→source`。

#### Scenario: 语义边一次性添加

- **WHEN** `add_bidirectional(A, B)` 被调用
- **THEN** MUST 等价于调用 `add_edge(A, B)` + `add_edge(B, A)`

#### Scenario: 接口定义为非抽象

- **WHEN** 检查 `StoreInterface.add_bidirectional`
- **THEN** MUST 为带默认实现的方法（默认调用两次 `add_edge`）；子类 MAY 覆写以优化（如减少存在性检查）
