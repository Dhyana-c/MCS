# Proposal: 统一插件基类 — 以 core/plugin.py 为顶级抽象

> 本 change 取代并吸收早期的 `adapt-plugins-to-new-base` 提案（后者仅有 proposal、且描述的是未落地的 `PluginEnum(ABC)` 设计）。实际落地以本 change 的 `PluginType(str, Enum)` 设计为准，`adapt-plugins-to-new-base` 已删除。

## 动机

当前插件系统存在两个根本性的架构问题：

### 1. 双重基类冲突

项目中存在两个 Plugin 基类：

- `mcs/core/plugin.py` — 新定义的顶级插件接口（`Plugin` + `PluginEnum`）
- `mcs/plugins/base.py` — 旧插件基类（`Plugin`，含 `name/version/interfaces/initialize/shutdown`）

两者同名、职责重叠，所有插件继承的是 `plugins/base.py` 的版本，`core/plugin.py` 尚未被任何代码使用。

### 2. core ↔ interfaces 循环依赖

```
core/plugin_manager.py  →  interfaces/entry_plugin.py  （core 依赖 interfaces）
interfaces/entry_plugin.py  →  core/graph.py           （interfaces 依赖 core）
```

`core` 是最底层模块，却依赖 `interfaces`；`interfaces` 定义接口方法签名时又引用 `core.graph.Node`。两者互相依赖，只能靠 `TYPE_CHECKING` 和函数内延迟导入绕开。

### 目标

1. **`core/plugin.py` 成为唯一的插件顶级抽象**，所有接口和插件实现都适配它
2. **消除 core → interfaces 的依赖**，`interfaces` 改为依赖 `core`（单向）
3. **删除 `plugins/base.py`**，其职责由 `core/plugin.py` 接管
4. **`PluginManager` 只依赖 `core/plugin.py`**，不再硬编码任何特定接口的检查逻辑

## 设计

### 新的依赖方向

```
core/plugin.py          （最底层，零依赖）
    ↑
core/graph.py           （依赖 core/plugin.py 中的类型）
    ↑
interfaces/*            （依赖 core，不反向依赖）
    ↑
core/plugin_manager.py  （依赖 core/plugin.py，不依赖 interfaces）
core/write_pipeline.py  （依赖 core + interfaces）
core/query_engine.py    （依赖 core + interfaces）
    ↑
plugins/*               （依赖 core + interfaces）
```

### core/plugin.py 最终形态

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class PluginType(str, Enum):
    """MCS 插件类型枚举。

    用于 PluginManager 按类型索引和查找插件。
    继承 str 和 Enum，使得可直接用字符串比较。
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


class Plugin(ABC):
    """所有 MCS 插件的顶级基类。

    任何插件必须：
    - 声明 name（标识符）
    - 声明 type（PluginType，标识插件类型/角色）
    - 声明 priority（执行优先级，数值越大越优先）
    - 实现 execute()（统一执行入口）
    - 实现 initialize() / shutdown()（生命周期）
    """

    @abstractmethod
    def get_name(self) -> str:
        """插件标识符。"""
        pass

    @abstractmethod
    def get_type(self) -> PluginType:
        """插件类型/角色。"""
        pass

    @abstractmethod
    def get_priority(self) -> int:
        """执行优先级，数值越大越优先。"""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """统一执行入口。"""
        pass

    @abstractmethod
    def initialize(self, context: Any) -> None:
        """初始化插件。"""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """清理插件资源。"""
        pass
```

### interfaces/* 适配方式

每个接口（如 `EntryPluginInterface`）继承 `core/plugin.py` 的 `Plugin`，不再作为独立 ABC：

```python
# 之前
class EntryPluginInterface(ABC):
    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        pass

# 之后
class EntryPluginInterface(Plugin):
    """入口插件接口 — 查询阶段②种子定位。"""

    @abstractmethod
    def get_type(self) -> PluginType:
        return PluginType.ENTRY

    @abstractmethod
    def get_priority(self) -> int:
        return 0

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """统一入口，委托给 locate()。"""
        return self.locate(
            query=kwargs["query"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        pass
```

### PluginManager 简化

```python
class PluginManager:
    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.by_type: dict[PluginType, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        self.plugins[plugin.get_name()] = plugin
        self.by_type.setdefault(plugin.get_type(), []).append(plugin)

    def get(self, plugin_type: PluginType) -> Plugin | None:
        plugins = self.get_all(plugin_type)
        return plugins[0] if plugins else None

    def get_all(self, plugin_type: PluginType) -> list[Plugin]:
        """按类型查找，按 priority 降序排列。"""
        plugins = list(self.by_type.get(plugin_type, []))
        plugins.sort(key=lambda p: -p.get_priority())
        return plugins
```

**关键变化**：
- 不再按 `interface` 类对象索引，改为按 `PluginType` 枚举索引
- 不再硬编码 `ArbitrationPlugin` 单例检查（如需单例，在 `register` 中按 type 检查即可）
- 不再硬编码 `EntryPluginInterface` 排序（统一按 priority 排序）
- **零依赖 interfaces**，只依赖 `core/plugin.py`

### 具体插件适配示例

```python
# 之前
class HubFallbackEntryPlugin(Plugin, EntryPluginInterface):
    name: ClassVar[str] = "hub_fallback"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    def initialize(self, context): ...
    def shutdown(self): ...
    def locate(self, query, ctx): ...

# 之后
class HubFallbackEntryPlugin(EntryPluginInterface):
    """HubFallback 入口插件。"""

    def get_name(self) -> str:
        return "hub_fallback"

    def get_type(self) -> PluginType:
        return PluginType.ENTRY

    def get_priority(self) -> int:
        return 0

    def execute(self, **kwargs):
        return self.locate(kwargs["query"], kwargs.get("ctx"))

    def initialize(self, context): ...
    def shutdown(self): ...
    def locate(self, query, ctx): ...
```

不再需要多重继承 `Plugin + XxxInterface`，因为接口本身就继承自 `Plugin`。

## 影响范围

### 需要修改的文件

| 文件 | 变更 |
|------|------|
| `core/plugin.py` | 扩展：增加 `initialize`/`shutdown` 抽象方法 |
| `plugins/base.py` | **删除** |
| `core/plugin_manager.py` | 重写：按 PluginEnum 索引，移除 interfaces 依赖 |
| `interfaces/entry_plugin.py` | 继承 Plugin，实现 get_type/execute |
| `interfaces/trim_plugin.py` | 同上 |
| `interfaces/arbitration_plugin.py` | 同上 |
| `interfaces/postprocess_plugin.py` | 同上 |
| `interfaces/compaction_plugin.py` | 同上 |
| `interfaces/storage.py` | 同上 |
| `interfaces/index.py` | 同上 |
| `interfaces/llm.py` | 同上 |
| `interfaces/node_extension.py` | 同上 |
| `interfaces/storage_schema_ext.py` | 同上 |
| `interfaces/maintenance.py` | 同上 |
| `plugins/phase1/*.py` (12个) | 移除 `Plugin` 多重继承，适配新基类 |
| `core/write_pipeline.py` | 改用 `PluginType` 查找插件 |
| `core/query_engine.py` | 改用 `PluginType` 查找插件 |
| `core/context_renderer.py` | 改用 `PluginType` 查找插件 |
| `__init__.py` | 适配新注册流程 |
| `tests/*.py` | 适配新基类 |

### 需要删除的文件

| 文件 | 原因 |
|------|------|
| `plugins/base.py` | 职责由 `core/plugin.py` 接管 |

### 需要更新的文档

| 文件 | 变更 |
|------|------|
| `openspec/specs/plugin-protocol/spec.md` | 更新接口定义，移除 ClassVar 约定 |
| `CLAUDE.md` | 更新插件相关描述 |

## 风险

1. **所有插件都要改** — 12 个 phase1 插件 + 6 个 phase2 插件，改动面大但机械
2. **exclusive 语义** — 当前 `EntryPlugin.exclusive` 是 ClassVar，改为实例方法或属性即可
3. **LLMInterface 特殊性** — 它有大量自有方法（call/register_prompt/attach_renderer 等），继承 Plugin 后需确保不冲突
4. **测试覆盖** — 需要确保所有现有测试通过

## 不变

- 插件的功能逻辑不变（locate/trim/arbitrate/process/run 等方法签名不变）
- 管线流程不变（7 阶段写入 / 5 阶段查询）
- 配置格式不变（`MCSConfig.plugins` 名称列表）
