## Why

测试代码存在多处重复逻辑，且有一个过期脚本待清理，影响维护效率：

1. **MCS 实例构建逻辑重复**：`conftest._MockLLMBuilder`、`test_pipeline_write._build_mcs_with_store` 手动组装 MCS，重复了 `MCSBuilder.build()` 的大部分逻辑，且容易与主代码不同步。（`test_mcs_api._build_mcs` 刻意最小化、仅注册 mock_llm，供门面 API 测试隔离，非重复，保留。）
2. **插件初始化逻辑重复**：多个测试文件包含相同的 PluginManager + PluginContext 初始化代码（含 `test_pipeline_query._build_engine`、`test_dual_edge._build_engine`、`test_directed_hierarchy._fanout_with_root`、`test_seed_graph._fanout_with_root`、`test_anti_regression._fanout_with_root`）。
3. **过期脚本未清理**：`_run_eval_variants.py` 是早期一次性 A/B 实验脚本（硬编码本机路径），底层能力仍由 `bench/multihop_rag` 保留（**已于 `236bd58` 删除**，本 change 登记契约）。
4. **bench .env 加载重复**：`scripts/_common.setup_env` 与 `runner._maybe_load_dotenv` 的 .env 解析逻辑逐字相同，且 `runner._maybe_load_dotenv` 硬编码了本机路径 `D:/code/mcs/.env`（开发者机器绑定）。提取公共 `bench/_env.load_dotenv()` 统一两处，并改由 `__file__` 推导项目根。

## What Changes

### 测试基础设施优化

- **统一 MCS 实例构建**：让 `_MockLLMBuilder` 继承 `MCSBuilder`，只覆写 `get_plugin_class()` 返回 Mock LLM，删除其他测试文件中的重复构建函数。
- **提取插件初始化 helper**：在 `tests/conftest.py` 中添加 `init_plugin_manager()` helper，统一 PluginManager + PluginContext 初始化模式。
- **提取图构建 fixture**：将 `_fanout_with_root()` 等重复的图构建函数提取为 `tests/conftest.py` 的 factory fixture（支持 `token_budget` 参数化）；`test_anti_regression` 的 `_fanout_with_root` 是未被调用的死定义，直接删除。

### 过期代码清理

- **删除 `_run_eval_variants.py`**：早期一次性 A/B 实验脚本，硬编码本机路径；底层 `MultiHopEvalRunner` 仍保留于 `bench/multihop_rag`。（**已于 `236bd58` 删除**，本 change 仅登记契约。）

### bench .env 加载去重

- **提取 `bench/_env.py`**：提供 `load_dotenv(env_file=None)`，封装 .env 解析（`setdefault` 不覆盖、忽略注释/空行、`split("=",1)` 保留 value 中的 `=`），默认从项目根（`__file__` 推导）加载。
- **`scripts/_common.setup_env` 复用**：删内联解析，改调 `load_dotenv(PROJECT_ROOT/".env")`，行为逐字等价。
- **`runner._maybe_load_dotenv` 复用**：删硬编码 `D:/code/mcs/.env`，改 `load_dotenv()`（默认项目根）+ 找不到兜底 `./.env`，行为等价。

## Capabilities

### New Capabilities

- `test-helpers`: 测试辅助函数和 fixture 集中管理（MCS 构建工厂、插件初始化 helper、图构建 fixture）
- `bench-utils`: bench 公共 .env 加载（`bench/_env.load_dotenv`）统一 `scripts/_common` 与 `runner` 两处重复解析，并消除 `runner` 硬编码本机路径

### Modified Capabilities

- 无（本变更仅重构测试代码，不改动任何 capability 的 spec 契约）

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `tests/conftest.py` | 修改 | 添加 `MockLLMBuilder`（继承 MCSBuilder）、`init_plugin_manager()`、图构建 fixture |
| `tests/test_pipeline_write.py` | 修改 | 删除 `_build_mcs_with_store`，改用 conftest 的构建工厂 |
| `tests/test_pipeline_query.py` | 修改 | 删除 `_build_engine`，改用 conftest helper |
| `tests/test_dual_edge.py` | 修改 | 删除 `_build_engine`，改用 conftest helper |
| `tests/test_hub_fallback.py` | 修改 | 删除 `_init`，改用 conftest helper |
| `tests/test_directed_navigation.py` | 修改 | 删除 `_init_plugin`，改用 conftest helper |
| `tests/test_directed_hierarchy.py` | 修改 | 删除 `_fanout_with_root`，改用 conftest fixture |
| `tests/test_seed_graph.py` | 修改 | 删除 `_fanout_with_root`，改用 conftest fixture |
| `tests/test_anti_regression.py` | 修改 | 删除未被调用的重复死定义 `_fanout_with_root` |
| `_run_eval_variants.py` | 删除（已于 `236bd58`） | 过期脚本；本 change 登记契约 |
| `bench/_env.py` | 新增 | 公共 `load_dotenv()` |
| `bench/multihop_rag/scripts/_common.py` | 修改 | `setup_env` 复用 `load_dotenv` |
| `bench/multihop_rag/runner.py` | 修改 | `_maybe_load_dotenv` 复用 `load_dotenv`，删硬编码本机路径 |

### 依赖关系

- 测试代码变更不影响主代码功能

### 风险

- **低风险**：测试重构不影响生产代码
- **低风险**：bench .env 去重为行为等价重构（解析逻辑逐字不变），仅影响 bench 入口环境装配
- **需验证**：重构后所有测试仍通过
