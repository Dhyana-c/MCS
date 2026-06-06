## Context

### 当前状态

MCS 类位于 `mcs/__init__.py`，包含：
1. `_default_plugin_registry()` 函数，硬编码导入 15+ 个具体插件类
2. `MCS.__init__()` 和 `initialize()` 方法，组装整个系统
3. 公共 API 方法 `ingest()`、`query()`、`persist_full()`

这导致：
- `mcs/__init__.py` 成为"包级模块"，但它依赖具体实现（`plugins/phase1/*`）
- 无法在 `core` 层测试 MCS 类而不引入 plugins
- bench 代码重复实现初始化逻辑（`_make_mcs`）

### 约束

1. **core 不依赖实现**：`mcs/core/` 不应导入 `mcs/plugins/`
2. **向后兼容**：`from mcs import MCS, MCSConfig` 保持有效
3. **接口稳定**：MCS 类的公共 API 不变

## Goals / Non-Goals

**Goals:**
1. MCS 类移入 `core`，成为纯数据持有者 + 公共 API
2. 引入 `MCSBuilder` 抽象，只依赖 `MCSConfig`
3. 新建 `presets/` 脚手架，提供 Phase1 默认构建器和快捷工厂
4. 保持向后兼容，现有代码导入路径不变

**Non-Goals:**
1. 不改变 MCS 类的公共 API（`ingest`、`query`、`persist_full`）
2. 不改变插件接口契约
3. 不改变 `MCSConfig` 的结构

## Decisions

### D1: MCS 类移入 `mcs/core/mcs.py`

**理由**：
- MCS 类是核心抽象，应位于 `core` 层
- 移动后 `core` 可独立测试，无需引入具体插件
- 符合"core 不依赖实现"原则

**替代方案**：
- 保留在 `mcs/__init__.py` → 无法解耦插件注册逻辑

### D2: `MCSBuilder` 作为抽象基类

**设计**：
```python
class MCSBuilder(ABC):
    """抽象构建器 - 只依赖 MCSConfig"""

    def __init__(self, config: MCSConfig):
        self.config = config

    @abstractmethod
    def get_plugin_class(self, name: str) -> type[Plugin] | None:
        """根据插件名称返回插件类"""
        ...

    def build(self) -> MCS:
        """构建并初始化 MCS 实例"""
        registry = self._collect_registry()
        mcs = MCS(self.config, plugin_registry=registry)
        mcs.initialize()
        return mcs

    def _collect_registry(self) -> dict[str, type[Plugin]]:
        """从 config.plugins 收集插件注册表"""
        return {
            name: cls
            for name in self.config.plugins
            if (cls := self.get_plugin_class(name)) is not None
        }
```

**理由**：
- 抽象方法 `get_plugin_class` 反转依赖，让子类决定如何查找插件类
- `build()` 封装完整的初始化流程

### D3: 新建 `mcs/presets/` 脚手架模块

**目录结构**：
```
mcs/presets/
├── __init__.py    # 导出 create_mcs, Phase1Builder
└── phase1.py      # Phase1 插件注册表 + 工厂函数
```

**phase1.py 设计**：
```python
def get_phase1_plugin_registry() -> dict[str, type[Plugin]]:
    """返回 Phase1 默认插件注册表"""
    from mcs.plugins.phase1.alias_index import AliasIndexPlugin, AliasEntryPlugin
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    # ... 其他插件
    return {
        "alias_index": AliasIndexPlugin,
        "alias_entry": AliasEntryPlugin,
        "deepseek_llm": DeepSeekLLMPlugin,
        # ...
    }

class Phase1Builder(MCSBuilder):
    """Phase1 预设构建器"""

    _registry: dict[str, type[Plugin]]

    def __init__(self, config: MCSConfig):
        super().__init__(config)
        self._registry = get_phase1_plugin_registry()

    def get_plugin_class(self, name: str) -> type[Plugin] | None:
        return self._registry.get(name)

def create_mcs(
    llm: str = "deepseek",
    db_path: str = "mcs.db",
    token_budget: int = 8000,
    **overrides
) -> MCS:
    """快捷工厂：创建 Phase1 MCS 实例"""
    config = MCSConfig.knowledge_graph(llm=llm)
    config.token_budget = token_budget
    config.plugin_configs["sqlite_storage"] = {"path": db_path}
    # 应用 overrides...
    builder = Phase1Builder(config)
    return builder.build()
```

**理由**：
- `presets/` 是"实现层"，可以依赖 `plugins/`
- 提供一键创建的便捷入口
- bench 代码可直接使用 `create_mcs()`

### D4: `mcs/__init__.py` 改为导出 + 兼容别名

```python
# mcs/__init__.py

from mcs.core.mcs import MCS
from mcs.core.config import MCSConfig
from mcs.core.builder import MCSBuilder
from mcs.presets.phase1 import create_mcs, get_phase1_plugin_registry

# 向后兼容别名
_default_plugin_registry = get_phase1_plugin_registry

__all__ = [
    "MCS",
    "MCSConfig",
    "MCSBuilder",
    "create_mcs",
    "_default_plugin_registry",
]
```

**理由**：
- 保持 `from mcs import MCS, MCSConfig` 不变
- `_default_plugin_registry` 作为别名，旧代码无需修改

## Risks / Trade-offs

### Risk 1: 导入循环

**风险**：`presets/phase1.py` 导入 `plugins/`，而 `plugins/` 可能反向导入 `mcs/__init__.py`

**缓解**：
- `plugins/` 只依赖 `core/` 和 `interfaces/`，不依赖 `mcs/__init__.py`
- 已验证 `plugins/` 的导入无循环

### Risk 2: 测试兼容性

**风险**：`tests/test_claude_llm.py` 使用 `from mcs import _default_plugin_registry`

**缓解**：
- 提供兼容别名，测试无需修改
- 或更新测试导入路径

### Trade-off: 新增模块

**代价**：新增 `core/mcs.py`、`core/builder.py`、`presets/` 模块

**收益**：
- 清晰的架构分层
- core 可独立测试
- 用户可自定义 Builder 实现

## Migration Plan

### Phase 1: 移动 MCS 类

1. 创建 `mcs/core/mcs.py`，复制 MCS 类定义
2. 移除 `_default_plugin_registry` 内联定义，改为参数注入
3. 更新 `mcs/core/__init__.py` 导出
4. 更新 `mcs/__init__.py` 从 core 导入

### Phase 2: 创建 Builder 抽象

1. 创建 `mcs/core/builder.py`
2. 定义 `MCSBuilder` ABC

### Phase 3: 创建 Presets 脚手架

1. 创建 `mcs/presets/__init__.py`
2. 创建 `mcs/presets/phase1.py`
3. 实现 `Phase1Builder` 和 `create_mcs()`

### Phase 4: 更新 Bench 代码

1. `mcs/bench/multihop_rag.py` 的 `_make_mcs()` 改用 `create_mcs()`
2. 移除重复的初始化逻辑

### Phase 5: 验证兼容性

1. 运行全量测试
2. 验证 `from mcs import MCS, MCSConfig` 仍有效
3. 验证 `_default_plugin_registry` 别名

## Open Questions

1. **是否需要支持自定义 Builder 注册？**
   - 当前设计：用户可继承 `MCSBuilder` 自定义实现
   - 未定：是否需要 `register_builder(name, cls)` 机制

2. **`create_mcs()` 的参数设计**
   - 当前设计：`create_mcs(llm, db_path, token_budget, **overrides)`
   - 未定：是否需要支持更多常用参数（如 `max_rounds`、`max_picked`）