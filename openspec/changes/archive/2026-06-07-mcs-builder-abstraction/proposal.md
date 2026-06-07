## Why

当前 `MCS` 类位于 `mcs/__init__.py`，存在以下问题：

1. **core 耦合实现细节**：`_default_plugin_registry()` 硬编码导入 15+ 个具体插件类，违反 `core` 层不应依赖实现的原则
2. **初始化逻辑散落**：`mcs/bench/multihop_rag.py` 中的 `_make_mcs()` 重复了配置组装逻辑，且环境变量读取散落各处
3. **缺乏统一构建入口**：用户需要手动创建 `MCSConfig`、注入插件配置、调用 `initialize()`，缺乏"一键创建"的便捷方式
4. **读写管线共享同一套插件**：写入和读取使用同一个 `PluginManager` 和同一个 LLM，无法支持写入用便宜模型（概念提取、关系判定）、读取用强模型（语义导航、重排）的场景；也无法让写入使用轻量 Entry 插件、读取使用重量 Entry 插件

引入 `MCSBuilder` 抽象层，将 MCS 类移入 `core`，在包外提供预设脚手架，实现关注点分离；同时将插件配置拆分为 shared/write/read 三组，支持读写管线使用不同插件。

## What Changes

### 新增

- **`mcs/core/mcs.py`**：MCS 类从 `__init__.py` 移入，双 PluginManager 架构（write_manager + read_manager），共享插件注册到两个 manager
- **`mcs/core/builder.py`**：`MCSBuilder` 抽象基类，只依赖 `MCSConfig`，定义构建契约，支持 shared/write/read 分离构建
- **`mcs/presets/__init__.py`**：脚手架模块，提供预配置的构建器和快捷工厂
- **`mcs/presets/phase1.py`**：Phase1 插件注册表 + `Phase1Builder` + `create_mcs()` 快捷工厂

### 修改

- **`mcs/core/config.py`**：`MCSConfig` 新增 `shared_plugins`、`write_plugins`、`read_plugins`、`write_llm`、`read_llm` 字段，移除旧 `plugins` 字段
- **`mcs/core/write_pipeline.py`**：`WritePipeline` 接收 read_manager 的 `QueryEngine`，自身使用 write_manager
- **`mcs/__init__.py`**：改为从 `core` 导出 `MCS`/`MCSConfig`，移除 `_default_plugin_registry` 内联定义
- **`mcs/core/__init__.py`**：导出 `MCS`、`MCSBuilder`
- **`mcs/bench/multihop_rag.py`**：`_make_mcs()` 改用 `mcs.presets.phase1.create_mcs()`
- **所有测试文件**：更新为新配置格式

### 删除

- `MCSConfig.plugins` 字段（由 `shared_plugins` + `write_plugins` + `read_plugins` 替代）
- `_default_plugin_registry()` 函数（由 `mcs.presets.phase1.get_phase1_plugin_registry()` 替代）

## Capabilities

### New Capabilities

- `mcs-builder`: MCS 构建器抽象，定义 `MCSBuilder` 契约，支持基于 `MCSConfig` 构建 MCS 实例，支持 shared/write/read 分离插件注册
- `mcs-presets`: 预设脚手架模块，提供 Phase1 默认插件注册表、快捷工厂函数，便于用户快速创建 MCS 实例

### Modified Capabilities

- `project-skeleton`: 目录结构变更，新增 `mcs/core/mcs.py`、`mcs/core/builder.py`、`mcs/presets/` 模块
- `plugin-protocol`: `MCSConfig` 结构变更，`plugins` 字段拆分为 `shared_plugins` + `write_plugins` + `read_plugins`

## Impact

### 代码变更

| 文件 | 变更类型 |
|------|----------|
| `mcs/core/mcs.py` | 新建（从 `__init__.py` 移入 + 双 Manager 重构） |
| `mcs/core/builder.py` | 新建 |
| `mcs/core/config.py` | 修改（MCSConfig 字段拆分） |
| `mcs/core/write_pipeline.py` | 修改（接收 read QueryEngine） |
| `mcs/core/__init__.py` | 修改（导出 MCS、MCSBuilder） |
| `mcs/presets/__init__.py` | 新建 |
| `mcs/presets/phase1.py` | 新建 |
| `mcs/__init__.py` | 修改（改为导出 + 移除内联注册表） |
| `mcs/bench/multihop_rag.py` | 修改（使用 presets） |
| `tests/*` | 修改（新配置格式） |

### 依赖关系

```
mcs/core/           # 不依赖 plugins/、presets/
    ├── mcs.py      # MCS 类（双 Manager）
    ├── builder.py  # MCSBuilder（抽象）
    └── config.py   # MCSConfig（shared/write/read 分离）

mcs/presets/        # 依赖 plugins/，提供脚手架
    └── phase1.py   # Phase1 插件注册 + 工厂

mcs/__init__.py     # 导出
```

### 使用方式变更

```python
# 之前
from mcs import MCS, MCSConfig
config = MCSConfig.knowledge_graph()
mcs = MCS(config)
mcs.initialize()

# 之后：读写同模型
from mcs.presets import create_mcs
mcs = create_mcs(llm="deepseek", db_path="mcs.db")

# 之后：读写不同模型
from mcs.presets import create_mcs
mcs = create_mcs(write_llm="ollama", read_llm="deepseek", db_path="mcs.db")

# 之后：完整自定义
from mcs import MCS, MCSConfig
config = MCSConfig(
    shared_plugins=["sqlite_storage", "source_tracking", "summary"],
    write_plugins=["idempotency_check", "fanout_reducer", "summary_regen"],
    read_plugins=["alias_index", "alias_entry", "hub_fallback", "priority_trim", "rerank"],
    write_llm="ollama_llm",
    read_llm="deepseek_llm",
)
mcs = MCS(config)
mcs.initialize()
```

### 插件分类矩阵

| PluginType | 分类 | 原因 |
|------------|------|------|
| STORAGE | shared | 数据一致性：写入后立即可读 |
| NODE_EXTENSION | shared | 节点结构一致性：summary/source_tracking 渲染 |
| STORAGE_SCHEMA_EXT | shared | 存储扩展：source_tracking 的 schema |
| ENTRY | read | 种子定位：只有读取需要 |
| TRIM | read | 裁剪：只有读取需要 |
| INDEX | read | 索引查询：alias_index 等 |
| ARBITRATION | read | 结果仲裁：只有读取需要 |
| COMPACTION | write | 压缩裂变：只有写入后触发 |
| POSTPROCESS | 按 position | write_preprocess → write；query_preprocess/query_postprocess → read |
| LLM | 分离 | write_llm + read_llm 分别指定 |
| MAINTENANCE | write | 维护操作：GC 等 |

### 测试影响

- 所有测试需更新为新配置格式（`shared_plugins`/`write_plugins`/`read_plugins` 替代 `plugins`）
- `tests/test_claude_llm.py` 中 `from mcs import _default_plugin_registry` 需更新为 `from mcs.presets.phase1 import get_phase1_plugin_registry`
