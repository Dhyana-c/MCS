## 1. 测试基础设施重构

### 1.1 MockLLMBuilder 继承 MCSBuilder

- [ ] 1.1.1 重构 `tests/conftest.py:_MockLLMBuilder`，让动态子类 `_MockBuilder` 的 `build()` 调用 `super().build()`
- [ ] 1.1.2 在 `_MockBuilder` 中覆写 `_instantiate_plugin()`，使 `"mock_llm"` 返回注入的实例而非新建
- [ ] 1.1.3 在 `_MockBuilder` 中覆写 `_init_store()`，支持外部传入的 Store
- [ ] 1.1.4 添加 `store` 参数到 `MockLLMBuilder.__init__()`，支持自定义 Store

### 1.2 插件初始化 helper

- [ ] 1.2.1 在 `tests/conftest.py` 添加 `init_plugin_manager()` 函数
- [ ] 1.2.2 添加 `fanout_reducer` fixture（封装 FanoutReducerPlugin 初始化）

### 1.3 更新测试文件删除重复代码

- [ ] 1.3.1 `test_pipeline_write.py`：删除 `_build_mcs_with_store`，改用 `MockLLMBuilder`
- [ ] 1.3.2 `test_pipeline_query.py`：删除 `_build_engine`，改用 `MockLLMBuilder` 或 helper
- [ ] 1.3.3 `test_mcs_api.py`：删除 `_build_mcs`，改用 `MockLLMBuilder`
- [ ] 1.3.4 `test_hub_fallback.py`：删除 `_init`，改用 `init_plugin_manager()`
- [ ] 1.3.5 `test_directed_navigation.py`：删除 `_init_plugin`，改用 `init_plugin_manager()`
- [ ] 1.3.6 `test_directed_hierarchy.py`：删除 `_fanout_with_root`，改用 `fanout_reducer` fixture
- [ ] 1.3.7 `test_seed_graph.py`：删除 `_fanout_with_root`，改用 `fanout_reducer` fixture

### 1.4 验证测试重构

- [ ] 1.4.1 运行 `pytest tests/ -q` 验证所有测试通过

---

## 2. bench 脚本优化

### 2.1 公共 .env 加载

- [ ] 2.1.1 创建 `bench/_env.py` 文件
- [ ] 2.1.2 实现 `load_dotenv()` 函数

### 2.2 更新 bench 脚本

- [ ] 2.2.1 `run_baseline.py`：删除手动 .env 加载，改用 `from bench._env import load_dotenv`
- [ ] 2.2.2 `run_node_rerank.py`：删除手动 .env 加载，改用 `load_dotenv()`
- [ ] 2.2.3 `run_doc_rerank.py`：删除手动 .env 加载，改用 `load_dotenv()`
- [ ] 2.2.4 `run_whole_doc.py`：删除手动 .env 加载，改用 `load_dotenv()`
- [ ] 2.2.5 `run_whole_doc_20.py`：删除手动 .env 加载，改用 `load_dotenv()`
- [ ] 2.2.6 `run_whole_doc_200.py`：删除手动 .env 加载，改用 `load_dotenv()`

### 2.3 修复硬编码路径

- [ ] 2.3.1 `bench/multihop_rag/data.py`：将 `DEFAULT_CORPUS` 改为环境变量 + 相对路径
- [ ] 2.3.2 `bench/multihop_rag/data.py`：将 `DEFAULT_QA` 改为环境变量 + 相对路径

---

## 3. 过期代码清理

- [ ] 3.1 删除 `_run_eval_variants.py` 文件

---

## 4. 验证

- [ ] 4.1 运行 `pytest tests/ -q` 确认所有测试通过
- [ ] 4.2 运行一个 bench 脚本确认 .env 加载正常工作