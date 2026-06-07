## 1. MCSConfig 字段拆分

- [x] 1.1 新增 `shared_plugins: list[str]`、`write_plugins: list[str]`、`read_plugins: list[str]` 字段
- [x] 1.2 新增 `write_llm: str`、`read_llm: str` 字段
- [x] 1.3 移除旧 `plugins: list[str]` 字段
- [x] 1.4 更新 `knowledge_graph()` 工厂方法，按 shared/write/read 分类返回默认插件，接受 `write_llm`/`read_llm` 参数
- [x] 1.5 更新 `memory_system()` 工厂方法（如有）

## 2. MCS 类双 Manager 重构

- [x] 2.1 创建 `mcs/core/mcs.py`，从 `mcs/__init__.py` 移入 MCS 类定义
- [x] 2.2 将 `plugin_manager` 替换为 `write_manager` + `read_manager`
- [x] 2.3 实现 `_register_shared_plugins()`：共享插件同一实例注册到两个 manager
- [x] 2.4 实现 `_register_write_plugins()`：写入插件只注册到 write_manager
- [x] 2.5 实现 `_register_read_plugins()`：读取插件只注册到 read_manager
- [x] 2.6 处理 LLM 分离：`write_llm` / `read_llm` 从对应 manager 查找；相同时共享实例
- [x] 2.7 `initialize()` 中 QueryEngine 使用 `read_manager` + `read_llm`
- [x] 2.8 `initialize()` 中 WritePipeline 使用 `write_manager` + `write_llm`，但 `query_engine` 传入读取侧
- [x] 2.9 `shutdown()` 处理双 manager 的生命周期（避免共享插件被 shutdown 两次）
- [x] 2.10 `_try_load_from_storage()` 适配双 manager（Index 重建用 read_manager）
- [x] 2.11 `persist_full()` 使用 write_manager 查找 Storage

## 3. MCSBuilder 抽象类

- [x] 3.1 创建 `mcs/core/builder.py`，定义 `MCSBuilder` ABC
- [x] 3.2 实现抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`
- [x] 3.3 实现具体方法 `build() -> MCS`，封装从配置到初始化的完整流程
- [x] 3.4 实现 `_collect_registry()`，从 `shared_plugins` + `write_plugins` + `read_plugins` + `write_llm` + `read_llm` 收集插件类

## 4. presets 脚手架模块

- [x] 4.1 创建 `mcs/presets/__init__.py`，导出 `create_mcs` 和 `Phase1Builder`
- [x] 4.2 创建 `mcs/presets/phase1.py`，实现 `get_phase1_plugin_registry()` 函数
- [x] 4.3 实现 `Phase1Builder` 类，继承 `MCSBuilder`
- [x] 4.4 实现 `create_mcs()` 快捷工厂函数，接受 `write_llm`/`read_llm`/`llm`（共用快捷参数）

## 5. mcs/__init__.py 重构

- [x] 5.1 将 `mcs/__init__.py` 改为从 `core` 和 `presets` 导入导出
- [x] 5.2 移除 `_default_plugin_registry()` 内联定义
- [x] 5.3 更新 `__all__` 列表，新增 `MCSBuilder`、`create_mcs`

## 6. WritePipeline 调整

- [x] 6.1 `WritePipeline.__init__()` 已接收 `query_engine` 参数，无需变更签名
- [x] 6.2 确认 WritePipeline 的 `plugin_manager` 是 `write_manager`，`llm` 是 `write_llm`
- [x] 6.3 确认 WritePipeline 的 `query_engine` 使用 `read_manager` 的 QueryEngine

## 7. Bench 代码适配

- [x] 7.1 更新 `mcs/bench/multihop_rag.py` 的 `_make_mcs()` 改用 `create_mcs()` 或 `Phase1Builder`
- [x] 7.2 验证 `mcs/bench/hotpot.py` 的 MCS 创建方式兼容

## 8. 测试全量更新

- [x] 8.1 更新 `tests/conftest.py` 中的配置创建，使用新字段
- [x] 8.2 更新 `tests/test_claude_llm.py` 的 `_default_plugin_registry` 导入
- [x] 8.3 更新 `tests/test_decision_apply.py` 的 WritePipeline/QueryEngine 创建
- [x] 8.4 更新其他测试文件中使用 `config.plugins` 的地方
- [x] 8.5 验证双 Manager 架构：共享插件同实例、专用插件单侧注册
- [x] 8.6 验证写入用 read QueryEngine 正常定位关联节点
- [x] 8.7 运行全量测试确保无回归

## 9. 示例代码更新

- [x] 9.1 更新 `examples/basic_usage.py` 使用新配置格式
- [x] 9.2 更新 `examples/wiki_example.py` 使用新配置格式

## 10. 文档更新

- [x] 10.1 更新 `mcs/core/__init__.py` docstring 说明新增模块
- [x] 10.2 更新 CLAUDE.md 中 MCSConfig 相关说明（sqlite_storage 不再作为插件）
