## 1. 定义接口与实现

- [x] 1.1 创建 `mcs/core/graph_store.py`，定义 `GraphStoreInterface` ABC（全部 12 个抽象方法）
- [x] 1.2 在 `graph_store.py` 中实现 `InMemoryGraphStore`（从现有 GraphStore 迁移 dict 实现）
- [x] 1.3 在 `graph_store.py` 中添加 `GraphStore = InMemoryGraphStore` 别名

## 2. 重构 graph.py

- [x] 2.1 保留 `mcs/core/graph.py` 中的 Node、Edge、Subgraph 数据类
- [x] 2.2 删除 `graph.py` 中的 `GraphStore` 类（已迁移到 `graph_store.py`）
- [x] 2.3 在 `graph.py` 中 re-export `GraphStoreInterface`、`GraphStore`、`InMemoryGraphStore`

## 3. 更新类型标注

- [x] 3.1 更新 `mcs/core/query_engine.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 3.2 更新 `mcs/core/write_pipeline.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 3.3 更新 `mcs/core/plugin_manager.py`：`PluginContext.graph` 类型改为 `GraphStoreInterface`
- [x] 3.4 更新 `mcs/interfaces/storage.py`：`save`、`save_full` 参数类型改为 `GraphStoreInterface`
- [x] 3.5 更新 `mcs/interfaces/compaction_plugin.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 3.6 更新 `mcs/interfaces/maintenance.py`：`graph` 参数类型改为 `GraphStoreInterface`

## 4. 更新插件实现

- [x] 4.1 更新 `mcs/plugins/phase1/sqlite_storage.py`：`load()` 返回类型保持 `GraphStore` 别名
- [x] 4.2 更新 `mcs/plugins/phase1/community_merger.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.3 更新 `mcs/plugins/phase1/fanout_reducer.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.4 更新 `mcs/plugins/phase1/alias_index.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.5 更新 `mcs/plugins/phase1/hub_fallback.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.6 更新 `mcs/plugins/phase1/source_tracking.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.7 更新 `mcs/plugins/phase1/summary_regen.py`：`graph` 参数类型改为 `GraphStoreInterface`
- [x] 4.8 更新 `mcs/diagnostics/graph_quality.py`：`graph` 参数类型改为 `GraphStoreInterface`

## 5. 更新主入口

- [x] 5.1 更新 `mcs/__init__.py`：`MCS.graph` 类型改为 `GraphStoreInterface`，实例化使用 `InMemoryGraphStore`

## 6. 测试验证

- [x] 6.1 运行全量测试验证重构正确性：`.venv/Scripts/python.exe -m pytest -q`

## 7. 文档与导出

- [x] 7.1 更新 `mcs/__init__.py` 导出：添加 `GraphStoreInterface`、`InMemoryGraphStore`
- [x] 7.2 更新 `openspec/specs/architecture.md`：添加 `graph-store-interface` capability 索引