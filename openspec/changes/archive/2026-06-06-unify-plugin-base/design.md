# Design: 统一插件基类实现设计

## 1. 核心类设计

### 1.1 PluginType 枚举

```python
# mcs/core/plugin.py

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class PluginType(str, Enum):
    """MCS 插件类型枚举。

    继承 str 和 Enum，使得：
    - 可作为 dict key（str 可哈希）
    - 支持字符串比较：PluginType.ENTRY == "entry"
    - 支持枚举语法：PluginType.ENTRY
    """
    ENTRY = "entry"
    TRIM = "trim"
    ARBITRATION = "arbitration"
    POSTPROCESS = "postprocess"
    COMPACTION = "compaction"
    STORAGE = "storage"
    INDEX = "index"
    LLM = "llm"
    NODE_EXTENSION = "node_extension"
    STORAGE_SCHEMA_EXT = "storage_schema_ext"
    MAINTENANCE = "maintenance"
```

### 1.2 Plugin 基类

```python
# mcs/core/plugin.py（续）

class Plugin(ABC):
    """所有 MCS 插件的顶级基类。

    设计原则：
    - 使用实例方法而非 ClassVar，支持运行时动态配置
    - execute() 作为统一入口，便于管线统一调用
    - initialize/shutdown 管理生命周期
    """

    @abstractmethod
    def get_name(self) -> str:
        """返回插件标识符。

        用于日志、配置索引、node.extensions 键名（NodeExtension 插件）。
        """
        pass

    @abstractmethod
    def get_type(self) -> PluginType:
        """返回插件类型。

        用于 PluginManager 按类型索引和查找。
        """
        pass

    def get_priority(self) -> int:
        """返回执行优先级（数值越大越优先）。

        默认返回 0。子类可覆写。
        用于 EntryPlugin 等需要排序的场景。
        """
        return 0

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """统一执行入口。

        管线可通过此方法统一调用任意插件。
        具体语义由各接口定义。
        """
        pass

    def initialize(self, context: Any) -> None:
        """初始化插件。

        默认空操作。子类可覆写以访问 graph/config 等。
        """
        pass

    def shutdown(self) -> None:
        """清理插件资源。

        默认空操作。子类可覆写。
        """
        pass
```

**设计决策**：

| 决策 | 理由 |
|------|------|
| `PluginType(str, Enum)` | str 继承使其可哈希、可比较，无需额外 dataclass |
| 不使用 PluginEnum 基类 | 没有扩展场景，直接定义 PluginType 枚举即可 |
| `get_name()` 抽象 | 必须由插件实现，是核心标识 |
| `get_type()` 抽象 | 必须由插件实现，决定其角色 |
| `get_priority()` 非抽象，默认 0 | 大多数插件不需要优先级，减少样板代码 |
| `initialize()` / `shutdown()` 非抽象 | 很多插件不需要初始化/清理，减少样板代码 |
| `execute()` 抽象 | 强制插件提供统一入口，便于未来扩展 |

---

## 2. 接口适配设计

### 2.1 EntryPluginInterface

```python
# mcs/interfaces/entry_plugin.py

from __future__ import annotations
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import Node


class EntryPluginInterface(Plugin):
    """入口插件接口 — 查询阶段②种子定位。

    继承 Plugin，实现 get_type() 返回 ENTRY，
    并定义 locate() 作为核心方法。
    """

    @abstractmethod
    def get_type(self) -> PluginType:
        return PluginType.ENTRY

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """统一入口，委托给 locate()。"""
        return self.locate(
            query=kwargs["query"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        """返回 query 的候选种子节点。"""
        pass

    # === 可选：exclusive 语义 ===

    @property
    def exclusive(self) -> bool:
        """是否独占。默认 False。"""
        return False
```

### 2.2 其他接口（统一模式）

所有接口遵循相同模式：

| 接口 | get_type() | execute() 委托 | 核心方法 |
|------|------------|----------------|----------|
| TrimPluginInterface | TRIM | `trim(nodes, budget)` | `trim()` |
| ArbitrationPluginInterface | ARBITRATION | `arbitrate(accumulated, query, ctx)` | `arbitrate()` |
| PostprocessPluginInterface | POSTPROCESS | `process(input, ctx)` | `process()` |
| CompactionPluginInterface | COMPACTION | `run(changed_nodes, graph, llm_caller)` | `run()` |
| StorageInterface | STORAGE | （无统一语义，抛 NotImplementedError） | `save()`/`load()` |
| IndexInterface | INDEX | （无统一语义） | `lookup()` |
| LLMInterface | LLM | `call(purpose, nodes_in, free_args)` | `call()` |
| NodeExtensionInterface | NODE_EXTENSION | （无统一语义） | `render()` |
| StorageSchemaExtensionInterface | STORAGE_SCHEMA_EXT | （无统一语义） | `node_columns()` |
| MaintenanceInterface | MAINTENANCE | `run(graph)` | `run()` |

---

## 3. PluginManager 设计

```python
# mcs/core/plugin_manager.py

from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import GraphStore
    from mcs.core.token_budget import TokenBudget


@dataclass
class PluginContext:
    """注入到 Plugin.initialize() 中的运行时上下文。"""
    graph: GraphStore
    config: MCSConfig
    token_budget: TokenBudget
    context_renderer: ContextRenderer
    plugin_manager: PluginManager


class PluginManager:
    """插件管理器 — 按 PluginType 类型索引和查找。"""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._by_type: dict[PluginType, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        """注册插件。"""
        name = plugin.get_name()
        if name in self._plugins:
            raise ValueError(f"Plugin {name!r} already registered")

        self._plugins[name] = plugin
        plugin_type = plugin.get_type()
        self._by_type.setdefault(plugin_type, []).append(plugin)

    def get(self, plugin_type: PluginType) -> Plugin | None:
        """返回指定类型的第一个插件（按 priority 降序）。"""
        plugins = self.get_all(plugin_type)
        return plugins[0] if plugins else None

    def get_all(self, plugin_type: PluginType) -> list[Plugin]:
        """返回指定类型的所有插件，按 priority 降序排列。"""
        plugins = list(self._by_type.get(plugin_type, []))
        plugins.sort(key=lambda p: -p.get_priority())
        return plugins

    def get_by_name(self, name: str) -> Plugin | None:
        """按名称查找插件。"""
        return self._plugins.get(name)

    def initialize_all(self, context: PluginContext) -> None:
        """初始化所有插件。"""
        for plugin in self._plugins.values():
            plugin.initialize(context)

    def shutdown_all(self) -> None:
        """关闭所有插件。"""
        for plugin in self._plugins.values():
            plugin.shutdown()
```

**简化点**：
- 移除 `ArbitrationPluginInterface` 单例检查（过度设计）
- 移除 `EntryPluginInterface` 特殊排序逻辑（统一按 priority）
- 移除 `interfaces` 字典（改为 `_by_type`）

---

## 4. 管线适配设计

### 4.1 QueryEngine

```python
# mcs/core/query_engine.py 改动点

# 之前
from mcs.interfaces.entry_plugin import EntryPluginInterface
entry_plugins = self.plugin_manager.get_all(EntryPluginInterface)

# 之后
from mcs.core.plugin import PluginType
entry_plugins = self.plugin_manager.get_all(PluginType.ENTRY)
```

### 4.2 WritePipeline

```python
# mcs/core/write_pipeline.py 改动点

# 之前
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
plugins = self.plugin_manager.get_all(PostprocessPluginInterface)

# 之后
from mcs.core.plugin import PluginType
plugins = self.plugin_manager.get_all(PluginType.POSTPROCESS)
```

---

## 5. 插件实现适配设计

以 `HubFallbackEntryPlugin` 为例：

```python
# 之前
class HubFallbackEntryPlugin(Plugin, EntryPluginInterface):
    name: ClassVar[str] = "hub_fallback"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    def initialize(self, context: PluginContext) -> None: ...
    def shutdown(self) -> None: ...
    def locate(self, query: str, ctx: QueryContext) -> list[Node]: ...

# 之后
class HubFallbackEntryPlugin(EntryPluginInterface):
    """Hub Fallback 入口插件。"""

    def get_name(self) -> str:
        return "hub_fallback"

    def get_priority(self) -> int:
        return 0

    @property
    def exclusive(self) -> bool:
        return False

    def initialize(self, context: PluginContext) -> None: ...
    def shutdown(self) -> None: ...
    def locate(self, query: str, ctx: QueryContext) -> list[Node]: ...
```

**变化**：
- 移除 `ClassVar` 声明（`name`, `version`, `interfaces`, `priority`）
- `get_name()` / `get_priority()` 替代类属性
- `exclusive` 改为实例属性
- 单继承（只继承 `EntryPluginInterface`）

---

## 6. 迁移策略

### 6.1 迁移顺序

```
Phase 1: 基础设施
  ├── 1.1 扩展 core/plugin.py（添加 PluginType、完善 Plugin）
  └── 1.2 重写 core/plugin_manager.py

Phase 2: 接口层
  ├── 2.1-2.11 适配 interfaces/*.py（11个文件）

Phase 3: 管线层
  ├── 3.1 适配 core/query_engine.py
  ├── 3.2 适配 core/write_pipeline.py
  └── 3.3 适配 core/context_renderer.py

Phase 4: 插件层
  ├── 4.1-4.13 适配 plugins/phase1/*.py（13个文件）
  └── 4.14-4.19 适配 plugins/phase2/*.py（6个文件）

Phase 5: 清理
  ├── 5.1 删除 plugins/base.py
  ├── 5.2 适配 mcs/__init__.py
  └── 5.3 更新测试文件
```

### 6.2 不保留兼容层

直接迁移，不保留旧基类兼容层，减少技术债。

---

## 7. 文件变更清单

### 7.1 扩展

| 文件 | 变更 |
|------|------|
| `core/plugin.py` | 添加 `PluginType`、完善 `Plugin` 方法 |

### 7.2 重写

| 文件 | 变更 |
|------|------|
| `core/plugin_manager.py` | 按 PluginType 索引 |
| `interfaces/entry_plugin.py` | 继承 Plugin |
| `interfaces/trim_plugin.py` | 继承 Plugin |
| `interfaces/arbitration_plugin.py` | 继承 Plugin |
| `interfaces/postprocess_plugin.py` | 继承 Plugin |
| `interfaces/compaction_plugin.py` | 继承 Plugin |
| `interfaces/storage.py` | 继承 Plugin |
| `interfaces/index.py` | 继承 Plugin |
| `interfaces/llm.py` | 继承 Plugin |
| `interfaces/node_extension.py` | 继承 Plugin |
| `interfaces/storage_schema_ext.py` | 继承 Plugin |
| `interfaces/maintenance.py` | 继承 Plugin |

### 7.3 适配

| 文件 | 变更 |
|------|------|
| `core/query_engine.py` | 使用 PluginType |
| `core/write_pipeline.py` | 使用 PluginType |
| `core/context_renderer.py` | 使用 PluginType |
| `mcs/__init__.py` | 适配新注册流程 |
| `plugins/phase1/*.py` (13个) | 适配新基类 |
| `plugins/phase2/*.py` (6个) | 适配新基类 |
| `tests/*.py` | 适配新基类 |

### 7.4 删除

| 文件 | 原因 |
|------|------|
| `plugins/base.py` | 职责由 `core/plugin.py` 接管 |
