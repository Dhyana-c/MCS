## Context

当前架构：
- `GraphStore` 是内存图存储，用 `dict` 实现（`_nodes`, `_edges`, `_adjacency`）
- `StorageInterface` 是持久化抽象，`SQLiteStoragePlugin` 实现之
- 两者正交：`StorageInterface` 负责快照，`GraphStore` 负责图操作

**消费者分析**：
| 消费者 | 调用方法 |
|--------|----------|
| `QueryEngine` | `get_node`, `get_neighbors`, `get_out_neighbors`, `get_subgraph` |
| `WritePipeline` | `get_node`, `get_neighbors`, `get_edge`, `add_node`, `add_edge` |
| `FanoutReducerPlugin` | 全部方法（含 delete/update） |
| `CommunityMergerPlugin` | `get_*`, `add_*`, `update_node` |
| `AliasIndexPlugin` | `get_all_nodes` |
| `graph_quality` | `get_all_nodes`, `get_all_edges`, `get_neighbors` |

## Goals / Non-Goals

**Goals:**
- 定义 `GraphStoreInterface` 抽象基类，统一读写接口
- 当前 `GraphStore` 改名为 `InMemoryGraphStore`，实现该接口
- 保持 `StorageInterface` 不变（持久化与图操作正交）
- 所有消费者统一依赖 `GraphStoreInterface`

**Non-Goals:**
- 本次不实现 SQLite 直接计算（只是留出扩展点）
- 不拆分只读/读写接口（过度设计）
- 不改变 `Node`、`Edge`、`Subgraph` 数据类

## Decisions

### D1: 单一接口策略

**决策**：两层架构
```
GraphStoreInterface (ABC, 读写一体化)
    └── InMemoryGraphStore (dict 实现)
    └── SQLiteGraphStore   (未来扩展)
```

**理由**：
- 只读消费者直接用 `GraphStoreInterface`，类型系统不限制，实际不调用写方法
- 不需要 Protocol 鸭子类型——所有实现显式继承 ABC
- 减少概念复杂度

**替代方案**：拆分 `GraphView`（只读）+ `GraphStoreInterface`（读写）
- 否决原因：过度设计，增加不必要的层次

### D2: `GraphStoreInterface` 方法集

**决策**：全部现有方法
```python
class GraphStoreInterface(ABC):
    # 节点 CRUD
    @abstractmethod
    def add_node(self, node: Node) -> str: ...
    @abstractmethod
    def get_node(self, node_id: str) -> Node | None: ...
    @abstractmethod
    def update_node(self, node_id: str, updates: dict) -> None: ...
    @abstractmethod
    def delete_node(self, node_id: str) -> None: ...

    # 边 CRUD
    @abstractmethod
    def add_edge(self, source_id: str, target_id: str, direction: str = "bidirectional") -> None: ...
    @abstractmethod
    def get_edge(self, source_id: str, target_id: str) -> Edge | None: ...
    @abstractmethod
    def delete_edge(self, source_id: str, target_id: str) -> None: ...

    # 查询
    @abstractmethod
    def get_neighbors(self, node_id: str) -> list[Node]: ...
    @abstractmethod
    def get_out_neighbors(self, node_id: str) -> list[Node]: ...
    @abstractmethod
    def get_subgraph(self, node_id: str, token_budget: TokenBudget | None) -> Subgraph: ...
    @abstractmethod
    def get_all_nodes(self) -> list[Node]: ...
    @abstractmethod
    def get_all_edges(self) -> list[Edge]: ...
```

**理由**：与现有 `GraphStore` 方法签名一致，最小改动

### D3: 文件组织

**决策**：
```
mcs/
  core/
    graph.py          → Node, Edge, Subgraph（数据类）
    graph_store.py    → GraphStoreInterface (ABC) + InMemoryGraphStore (实现)
```

**理由**：
- 数据类与存储接口分离，职责清晰
- 避免循环导入

### D4: `StorageInterface` 关系

**决策**：保持不变，与 `GraphStoreInterface` 正交

```
GraphStoreInterface (图操作)    StorageInterface (持久化)
        ↓                              ↓
InMemoryGraphStore            SQLiteStoragePlugin
        ↓         save/load           ↓
        └──────────────────────────────┘
```

## Risks / Trade-offs

### R1: 类型标注更新
- **风险**：大量文件更新导入路径
- **缓解**：保留 `GraphStore = InMemoryGraphStore` 别名，渐进迁移

### R2: 无只读语义强制
- **风险**：只读消费者技术上可调用写方法
- **缓解**：接受此风险——实际不会调用，依赖代码规范而非类型系统

## Migration Plan

1. **创建 `graph_store.py`**：定义 `GraphStoreInterface` ABC + `InMemoryGraphStore` 实现 + `GraphStore` 别名
2. **重构 `graph.py`**：只保留 Node/Edge/Subgraph 数据类，re-export 接口
3. **更新类型标注**：消费者统一依赖 `GraphStoreInterface`
4. **运行测试验证**

**回滚策略**：删除新文件，恢复原 `GraphStore` 类