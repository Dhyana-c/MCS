## Why

测试代码和脚本存在多处重复逻辑和过期代码，影响维护效率：

1. **MCS 实例构建逻辑重复**：`conftest._MockLLMBuilder`、`test_pipeline_write._build_mcs_with_store`、`test_mcs_api._build_mcs` 手动组装 MCS，重复了 `MCSBuilder.build()` 的大部分逻辑，且容易与主代码不同步。
2. **插件初始化逻辑重复**：多个测试文件包含相同的 PluginManager + PluginContext 初始化代码。
3. **bench 脚本 .env 加载重复**：6 个评测脚本包含完全相同的 .env 加载代码块。
4. **过期脚本未清理**：`_run_eval_variants.py` 是早期实验性脚本，功能已被 bench 脚本覆盖。
5. **硬编码路径不可移植**：`bench/multihop_rag/data.py` 硬编码了本地数据路径。

## What Changes

### 测试基础设施优化

- **统一 MCS 实例构建**：让 `_MockLLMBuilder` 继承 `MCSBuilder`，只覆写 `get_plugin_class()` 返回 Mock LLM，删除其他测试文件中的重复构建函数。
- **提取插件初始化 helper**：在 `tests/conftest.py` 中添加 `init_plugin_manager()` helper，统一 PluginManager + PluginContext 初始化模式。
- **提取图构建 fixture**：将 `_fanout_with_root()` 等重复的图构建函数提取到 `tests/conftest.py`。

### bench 脚本优化

- **提取 .env 加载逻辑**：在 `bench/_env.py` 中提供 `load_dotenv()` 函数，各脚本复用。
- **修复硬编码路径**：将 `bench/multihop_rag/data.py` 中的硬编码路径改为环境变量或相对路径。

### 过期代码清理

- **删除 `_run_eval_variants.py`**：功能已被 `bench/multihop_rag/scripts/` 下脚本覆盖。

## Capabilities

### New Capabilities

- `test-helpers`: 测试辅助函数和 fixture 集中管理（MCS 构建工厂、插件初始化 helper、图构建 fixture）
- `bench-utils`: bench 脚本公共工具（.env 加载、路径配置）

### Modified Capabilities

- `mcs-builder`: 无 spec 级别变更，但测试代码将继承 MCSBuilder 而非手动组装
- `bench-directory-structure`: 补充 `bench/_env.py` 作为公共工具模块

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `tests/conftest.py` | 修改 | 添加 `MockLLMBuilder`（继承 MCSBuilder）、`init_plugin_manager()`、图构建 fixture |
| `tests/test_pipeline_write.py` | 修改 | 删除 `_build_mcs_with_store`，改用 conftest 的构建工厂 |
| `tests/test_pipeline_query.py` | 修改 | 删除 `_build_engine`，改用 conftest helper |
| `tests/test_mcs_api.py` | 修改 | 删除 `_build_mcs`，改用 conftest 的构建工厂 |
| `tests/test_hub_fallback.py` | 修改 | 删除 `_init`，改用 conftest helper |
| `tests/test_directed_navigation.py` | 修改 | 删除 `_init_plugin`，改用 conftest helper |
| `tests/test_directed_hierarchy.py` | 修改 | 删除 `_fanout_with_root`，改用 conftest fixture |
| `tests/test_seed_graph.py` | 修改 | 删除 `_fanout_with_root`，改用 conftest fixture |
| `bench/_env.py` | 新增 | 提供 `load_dotenv()` 函数 |
| `bench/multihop_rag/data.py` | 修改 | 硬编码路径改为环境变量 |
| `bench/multihop-rag/scripts/run_*.py` | 修改 | 使用 `bench._env.load_dotenv()` |
| `_run_eval_variants.py` | 删除 | 过期脚本 |

### 依赖关系

- 测试代码变更不影响主代码功能
- bench 脚本变更不影响评测逻辑，仅重构代码组织

### 风险

- **低风险**：测试重构不影响生产代码
- **需验证**：重构后所有测试仍通过
