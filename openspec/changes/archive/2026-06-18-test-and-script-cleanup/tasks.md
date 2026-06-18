## 1. 测试基础设施重构

### 1.1 MockLLMBuilder 继承 MCSBuilder

- [x] 1.1.1 重构 `tests/conftest.py` 的 `_MockLLMBuilder`：重命名为公开的 `MockLLMBuilder`，让其动态子类 `_MockBuilder` 的 `build()` 调用 `super().build()`
- [x] 1.1.2 在 `_MockBuilder` 中覆写 `_instantiate_plugin()`，使 `"mock_llm"` 返回注入的实例而非新建
- [x] 1.1.3 在 `_MockBuilder` 中覆写 `_init_store()`，支持外部传入的 Store
- [x] 1.1.4 添加 `store` 参数到 `MockLLMBuilder.__init__()`，支持自定义 Store
- [x] 1.1.5 更新 `mcs_with_mock_llm` fixture 引用 `MockLLMBuilder`；将 `MockLLMBuilder` 类加入 `__all__` 供测试文件 `from conftest import MockLLMBuilder`（fixture 本身由 pytest 自动发现，不入 `__all__`）

### 1.2 插件初始化 helper

- [x] 1.2.1 在 `tests/conftest.py` 添加 `init_plugin_manager()` 函数
- [x] 1.2.2 添加 `fanout_reducer` factory fixture（封装 FanoutReducerPlugin 初始化，支持 `token_budget` 参数化）
- [x] 1.2.3 在 `tests/conftest.py` 添加 `make_query_engine()` 函数（封装 QueryEngine 构建）

### 1.3 更新测试文件删除重复代码

- [x] 1.3.1 `test_pipeline_write.py`：删除 `_build_mcs_with_store`，改用 `MockLLMBuilder`
- [x] 1.3.2 `test_pipeline_query.py`：删除 `_build_engine`，改用 `make_query_engine()`
- [x] 1.3.3 `test_hub_fallback.py`：删除 `_init`，改用 `init_plugin_manager()`
- [x] 1.3.4 `test_directed_navigation.py`：删除 `_init_plugin`，改用 `init_plugin_manager()`
- [x] 1.3.5 `test_directed_hierarchy.py`：删除 `_fanout_with_root`，改用 `fanout_reducer` fixture
- [x] 1.3.6 `test_seed_graph.py`：删除 `_fanout_with_root`，改用 `fanout_reducer` fixture
- [x] 1.3.7 `test_dual_edge.py`：删除 `_build_engine`，改用 `make_query_engine()`
- [x] 1.3.8 `test_anti_regression.py`：删除未被调用的重复死定义 `_fanout_with_root`

> 注：`test_mcs_api._build_mcs` 刻意最小化（仅注册 mock_llm，供门面 API 测试隔离），非重复，保留不动。

### 1.4 验证测试重构

- [x] 1.4.1 运行 `pytest tests/ -q` 验证所有测试通过

---

## 2. 过期代码清理

- [x] 2.1 删除 `_run_eval_variants.py` 文件（已于 `236bd58` 删除，本 change 确认）

---

## 3. bench .env 加载去重

- [x] 3.1 新建 `bench/_env.py`（`load_dotenv(env_file=None) -> bool`）
- [x] 3.2 `scripts/_common.setup_env` 复用 `load_dotenv`
- [x] 3.3 `runner._maybe_load_dotenv` 复用 `load_dotenv`，删硬编码 `D:/code/mcs/.env`
- [x] 3.4 新增 `tests/test_bench_env.py` 覆盖边界（默认/自定义路径、setdefault 不覆盖、缺失静默、注释/空行、value 含 `=`、空 value）

---

## 4. 验证

- [x] 4.1 运行 `pytest tests/ -q` 确认所有测试通过