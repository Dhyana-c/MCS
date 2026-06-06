## Why

当前 `MCS` 类位于 `mcs/__init__.py`，存在以下问题：

1. **core 耦合实现细节**：`_default_plugin_registry()` 硬编码导入 15+ 个具体插件类，违反 `core` 层不应依赖实现的原则
2. **初始化逻辑散落**：`mcs/bench/multihop_rag.py` 中的 `_make_mcs()` 重复了配置组装逻辑，且环境变量读取散落各处
3. **缺乏统一构建入口**：用户需要手动创建 `MCSConfig`、注入插件配置、调用 `initialize()`，缺乏"一键创建"的便捷方式

引入 `MCSBuilder` 抽象层，将 MCS 类移入 `core`，在包外提供预设脚手架，实现关注点分离。

## What Changes

### 新增

- **`mcs/core/mcs.py`**：MCS 类从 `__init__.py` 移入，作为纯数据持有者 + 公共 API
- **`mcs/core/builder.py`**：`MCSBuilder` 抽象基类，只依赖 `MCSConfig`，定义构建契约
- **`mcs/presets/__init__.py`**：脚手架模块，提供预配置的构建器和快捷工厂
- **`mcs/presets/phase1.py`**：Phase1 插件注册表 + `Phase1Builder` + `create_mcs()` 快捷工厂

### 修改

- **`mcs/__init__.py`**：改为从 `core` 导出 `MCS`/`MCSConfig`，保持向后兼容；移除 `_default_plugin_registry` 内联定义
- **`mcs/core/__init__.py`**：导出 `MCS`、`MCSBuilder`
- **`mcs/bench/multihop_rag.py`**：`_make_mcs()` 改用 `mcs.presets.phase1.create_mcs()`

### 向后兼容

- `from mcs import MCS, MCSConfig` 保持不变
- `from mcs import _default_plugin_registry` 改为从 `mcs.presets.phase1` 导入的别名

## Capabilities

### New Capabilities

- `mcs-builder`: MCS 构建器抽象，定义 `MCSBuilder` 契约，支持基于 `MCSConfig` 构建 MCS 实例，支持插件注册表注入
- `mcs-presets`: 预设脚手架模块，提供 Phase1 默认插件注册表、快捷工厂函数，便于用户快速创建 MCS 实例

### Modified Capabilities

- `project-skeleton`: 目录结构变更，新增 `mcs/core/mcs.py`、`mcs/core/builder.py`、`mcs/presets/` 模块

## Impact

### 代码变更

| 文件 | 变更类型 |
|------|----------|
| `mcs/core/mcs.py` | 新建（从 `__init__.py` 移入） |
| `mcs/core/builder.py` | 新建 |
| `mcs/core/__init__.py` | 修改（导出 MCS、MCSBuilder） |
| `mcs/presets/__init__.py` | 新建 |
| `mcs/presets/phase1.py` | 新建 |
| `mcs/__init__.py` | 修改（改为导出 + 兼容别名） |
| `mcs/bench/multihop_rag.py` | 修改（使用 presets） |

### 依赖关系

```
mcs/core/           # 不依赖 plugins/、presets/
    ├── mcs.py      # MCS 类
    └── builder.py  # MCSBuilder（抽象）

mcs/presets/        # 依赖 plugins/，提供脚手架
    └── phase1.py   # Phase1 插件注册 + 工厂

mcs/__init__.py     # 导出 + 向后兼容
```

### 使用方式变更

```python
# 之前（仍然支持）
from mcs import MCS, MCSConfig
config = MCSConfig.knowledge_graph()
mcs = MCS(config)
mcs.initialize()

# 之后（推荐）
from mcs.presets import create_mcs
mcs = create_mcs(llm="deepseek", db_path="mcs.db")
```

### 测试影响

- `tests/test_claude_llm.py` 中 `from mcs import _default_plugin_registry` 需更新导入路径（或使用兼容别名）
- 其他测试无需修改（导入路径不变）
