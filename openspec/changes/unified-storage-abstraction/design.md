## Context

当前架构：
- `GraphStoreInterface` (core/graph_store.py) — 图操作接口（CRUD + 查询），`InMemoryGraphStore` 实现之
- `StorageInterface` (interfaces/storage.py) — 持久化接口（save/load），`SQLiteStoragePlugin` 实现之
- `InMemoryGraphStore` 放在 `core/` 中，违反"core 只含接口"原则
- 两个接口职责重叠：`StorageInterface.save(graph)` 把 `GraphStoreInterface` 的内容写入持久层

**消费者分析**：
- `QueryEngine`、`WritePipeline`、插件 — 需要 `GraphStoreInterface`（图操作）
- `MCS` — 持有 `GraphStoreInterface` 实例，通过 `StorageInterface` 持久化

## Goals / Non-Goals

**Goals:**
- 合并两个接口为统一的 `StoreInterface`
- `InMemoryStore` 移出 core → `mcs/stores/`
- `SQLiteStore` 直接实现 `StoreInterface`（可在 SQLite 上做计算）
- `core/store.py` 只保留接口定义

**Non-Goals:**
- 本次不实现 SQLite 直接计算优化（只是留出扩展点）
- 不改变 `Node`、`Edge`、`Subgraph` 数据类
- 不改变插件系统的其他类型

## Decisions

### D1: 统一接口设计

**决策**：`StoreInterface` 合并全部方法
```python
class StoreInterface(ABC):
    # 图操作（继承自 GraphStoreInterface）
    @abstractmethod
    def add_node(self, node: Node) -> str: ...
    @abstractmethod
    def get_node(self, node_id: str) -> Node | None: ...
    @abstractmethod
    def get_neighbors(self, node_id: str) -> list[Node]: ...
    # ... 其他 CRUD + 查询方法

    # 持久化钩子（继承自 StorageInterface）
    @abstractmethod
    def save(self) -> None: ...      # 持久化当前状态
    @abstractmethod
    def load(self) -> None: ...      # 从持久层加载
    @abstractmethod
    def commit(self) -> None: ...    # 提交挂起写入
    @abstractmethod
    def save_full(self) -> None: ... # 全量重建持久化
```

**理由**：
- 一个存储后端只需实现一个接口
- `InMemoryStore` 可以实现持久化钩子为空操作（或可选支持）
- `SQLiteStore` 可以直接在 SQLite 上做计算，不需要"load 到内存再操作"

**替代方案**：保持两个接口分离
- 否决原因：概念割裂，`StorageInterface` 只是把 `GraphStoreInterface` 内容写入持久层，没有独立价值

### D2: 文件组织

**决策**：
```
mcs/
  core/
    store.py              → StoreInterface ABC（接口定义）
    graph.py              → Node/Edge/Subgraph 数据类（保留）
  stores/
    in_memory.py          → InMemoryStore 实现
    sqlite_store.py       → SQLiteStore 实现（从 plugins/phase1/sqlite_storage.py 迁出）
```

**理由**：
- `core/` 只含接口和数据类
- `stores/` 是存储实现目录，与 `plugins/` 正交

### D3: SQLiteStore 与插件系统

**决策**：`SQLiteStore` 不再是 Plugin 子类
- MCS 初始化时直接创建 `StoreInterface` 实例（`InMemoryStore` 或 `SQLiteStore`）
- `PluginContext` 持有 `StoreInterface` 实例而非通过 `PluginManager` 查找

**理由**：
- 存储是核心依赖，不是可选插件
- 简化初始化流程

### D4: 向后兼容

**决策**：不提供向后兼容别名（breaking change）
- `GraphStoreInterface` → 删除
- `StorageInterface` → 删除
- `InMemoryGraphStore` → 删除，用 `InMemoryStore`
- `SQLiteStoragePlugin` → 删除，用 `SQLiteStore`

**理由**：
- 项目处于早期阶段，breaking change 可接受
- 避免别名累积增加概念复杂度

## Risks / Trade-offs

### R1: Breaking change 范围大
- **风险**：所有使用 `GraphStoreInterface`、`StorageInterface` 的代码需更新
- **缓解**：一次性重构，运行全量测试验证

### R2: PluginType.STORAGE 移除
- **风险**：插件系统少了一个类型
- **缓解**：存储不是"可选插件"，是核心组件，移除合理

## Migration Plan

1. **创建新结构**
   - 创建 `mcs/core/store.py`（`StoreInterface` ABC）
   - 创建 `mcs/stores/in_memory.py`（`InMemoryStore`）
   - 创建 `mcs/stores/sqlite_store.py`（`SQLiteStore`）

2. **删除旧文件**
   - 删除 `mcs/core/graph_store.py`
   - 删除 `mcs/interfaces/storage.py`
   - 删除 `mcs/plugins/phase1/sqlite_storage.py`

3. **更新导入路径**
   - 所有消费方改为 `from mcs.core.store import StoreInterface`
   - MCS 实例化改为 `InMemoryStore()`

4. **运行测试验证**
   - 全量测试验证重构正确性

**回滚策略**：Git revert