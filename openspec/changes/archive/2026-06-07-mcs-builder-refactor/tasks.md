## 1. MCS 类重构

- [x] 1.1 重构 MCS 构造器——接受 `write_pipeline`, `query_engine`, `store`, `write_manager`, `read_manager`，移除 `config` 和 `plugin_registry` 参数
- [x] 1.2 移除 MCS 的 `initialize()` 方法——初始化逻辑全部移到 Builder
- [x] 1.3 移除 MCS 的 `_register_plugins_from_config()` / `_instantiate_plugin()` / `_register_llm_plugins()` 方法
- [x] 1.4 重构 `register_plugin(plugin, target)` ——添加 `target: Literal["writer", "reader"]` 参数，单侧注册
- [x] 1.5 新增 `register_shared_plugin(plugin)` 方法——将同一插件实例注册到 write_manager 和 read_manager 两侧
- [x] 1.6 新增 `unregister_plugin(name, target)` 方法——从指定 manager 注销插件
- [x] 1.7 实现 `show()` 方法——返回 Markdown 格式的双管线流程图（含 Mermaid 和插件列表）
- [x] 1.8 移除 `persist_full()` 方法——用户改为调用 `mcs.store.save_full()`
- [x] 1.9 移除 `_try_load_from_storage()` 方法——逻辑移到 Builder
- [x] 1.10 实现 `shutdown()` 方法——去重关闭共享插件实例（从当前 mcs.py:288-309 保留逻辑）

## 2. MCSBuilder 扩展

- [x] 2.1 扩展 `MCSBuilder.build()` ——接管完整初始化流程（14 步，含 ContextRenderer 构建）
- [x] 2.2 实现 `_init_store()` 私有方法——根据 config 实例化并初始化 Store
- [x] 2.3 实现 `_register_plugins()` 私有方法——按 shared/write/read 分类注册插件到双 manager
- [x] 2.4 实现 `_init_plugin_context()` 私有方法——创建 ContextRenderer，构建 PluginContext 并初始化所有插件
- [x] 2.5 实现 `_build_pipelines()` 私有方法——构建 QueryEngine 和 WritePipeline
- [x] 2.6 实现 `_load_on_startup()` 私有方法——若 Store 为空且 SQLite 可用，加载已有数据并重建 Index

## 3. Phase1Builder 适配

- [x] 3.1 更新 `Phase1Builder` ——继承自 MCSBuilder，利用基类的 build() 逻辑，移除重复的 `_collect_registry()` 和 `build()` 实现
- [x] 3.2 更新 `create_mcs()` 工厂函数——使用更新后的 Phase1Builder，接口签名保持不变

## 4. PluginManager 扩展

- [x] 4.1 新增 `PluginManager.unregister(name: str) -> bool` 方法——按名称移除已注册插件，同时清理 `_by_type` 索引

## 5. 测试迁移

- [x] 5.1 更新 `tests/conftest.py` ——`mcs_with_mock_llm` fixture 改用 Builder 构建，`register_plugin(mock_llm)` 改为 `register_shared_plugin(mock_llm)`
- [x] 5.2 更新 `tests/test_pipeline_write.py` ——所有 `MCS(config).register_plugin().initialize()` 改为 Builder 构建
- [x] 5.3 更新 `tests/test_query_engine.py` ——适配新的 MCS 构造方式
- [x] 5.4 新增 `test_register_shared_plugin()` 测试——验证共享注册行为（同实例双侧注册）
- [x] 5.5 新增 `test_register_plugin_target()` 测试——验证定向注册行为
- [x] 5.6 新增 `test_unregister_plugin()` 测试——验证注销行为
- [x] 5.7 新增 `test_show()` 测试——验证 show() 方法输出格式（Mermaid 代码块 + 插件列表）
- [x] 5.8 新增 `test_shutdown_dedup()` 测试——验证共享插件只 shutdown 一次

## 6. 示例与文档更新

- [x] 6.1 更新 `examples/basic_usage.py` ——`build_mock_mcs()` 改用 Builder 构建，`register_plugin()` 改为 `register_shared_plugin()`
- [x] 6.2 更新 `examples/wiki_example.py` ——同上
- [x] 6.3 更新 `mcs/__init__.py` docstring——反映新的使用方式（Builder 优先），移除 `MCS(config)` 示例
- [x] 6.4 更新 `README.md` ——更新快速开始示例，展示 `create_mcs()` 用法，移除手动 initialize 流程
- [x] 6.5 更新 `mcs/bench/multihop_rag.py` ——`persist_full()` 改为 `mcs.store.save_full()`

## 7. 规范更新与归档

- [x] 7.1 更新 `openspec/specs/mcs-builder/spec.md` ——归档新契约（Builder 全量组装、MCS 瘦门面）
- [x] 7.2 更新 `openspec/specs/plugin-protocol/spec.md` ——归档插件注册变更（target 参数、unregister、register_shared_plugin）
- [x] 7.3 更新 `openspec/specs/auto-persistence/spec.md` ——load-on-startup 改为 Builder 执行，移除 MCS.initialize() 引用
- [x] 7.4 更新 `openspec/specs/architecture.md` ——反映 MCS 的新定位（瘦门面）
- [x] 7.5 将变更 specs 合并到对应规范文件，归档 change
