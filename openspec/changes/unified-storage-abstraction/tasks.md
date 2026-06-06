## 1. 定义统一接口

- [ ] 1.1 创建 `mcs/core/store.py`，定义 `StoreInterface` ABC（合并 GraphStoreInterface + StorageInterface 全部方法）
- [ ] 1.2 创建 `mcs/stores/` 目录

## 2. 迁移实现

- [ ] 2.1 创建 `mcs/stores/in_memory.py`，实现 `InMemoryStore`（从 `core/graph_store.py` 迁出）
- [ ] 2.2 创建 `mcs/stores/sqlite_store.py`，实现 `SQLiteStore`（从 `plugins/phase1/sqlite_storage.py` 迁出并重构）

## 3. 更新核心文件

- [ ] 3.1 删除 `mcs/core/graph_store.py`
- [ ] 3.2 删除 `mcs/interfaces/storage.py`
- [ ] 3.3 删除 `mcs/plugins/phase1/sqlite_storage.py`
- [ ] 3.4 更新 `mcs/core/graph.py`：re-export `StoreInterface`、`InMemoryStore`、`SQLiteStore`

## 4. 更新类型标注

- [ ] 4.1 更新 `mcs/core/query_engine.py`：`graph` 参数改为 `store: StoreInterface`
- [ ] 4.2 更新 `mcs/core/write_pipeline.py`：`graph` 参数改为 `store: StoreInterface`
- [ ] 4.3 更新 `mcs/core/plugin_manager.py`：`PluginContext.store` 类型为 `StoreInterface`（移除 `graph` 属性）
- [ ] 4.4 更新 `mcs/interfaces/compaction_plugin.py`：`graph` 参数改为 `store: StoreInterface`
- [ ] 4.5 更新 `mcs/interfaces/maintenance.py`：`graph` 参数改为 `store: StoreInterface`

## 5. 更新插件实现

- [ ] 5.1 更新 `mcs/plugins/phase1/community_merger.py`：`graph` 改为 `store`
- [ ] 5.2 更新 `mcs/plugins/phase1/fanout_reducer.py`：`graph` 改为 `store`
- [ ] 5.3 更新 `mcs/plugins/phase1/alias_index.py`：`graph` 改为 `store`
- [ ] 5.4 更新 `mcs/plugins/phase1/hub_fallback.py`：`graph` 改为 `store`
- [ ] 5.5 更新 `mcs/plugins/phase1/source_tracking.py`：`graph` 改为 `store`
- [ ] 5.6 更新 `mcs/plugins/phase1/summary_regen.py`：`graph` 改为 `store`
- [ ] 5.7 更新 `mcs/diagnostics/graph_quality.py`：`graph` 改为 `store`

## 6. 更新主入口

- [ ] 6.1 更新 `mcs/__init__.py`：`MCS.store` 类型为 `StoreInterface`，实例化使用 `InMemoryStore`
- [ ] 6.2 从 `PluginType` 中移除 `STORAGE`
- [ ] 6.3 更新插件注册表：移除 `sqlite_storage`

## 7. 测试验证

- [ ] 7.1 运行全量测试验证重构正确性：`.venv/Scripts/python.exe -m pytest -q`

## 8. 文档与导出

- [ ] 8.1 更新 `mcs/__init__.py` 导出：添加 `StoreInterface`、`InMemoryStore`、`SQLiteStore`
- [ ] 8.2 更新 `openspec/specs/architecture.md`：移除 `graph-store-interface`，添加 `store-interface`
