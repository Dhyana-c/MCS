# Tasks: 统一插件基类实现任务

## Phase 1: 基础设施

- [x] 1.1 扩展 `core/plugin.py`
  - 添加 `PluginType(str, Enum)` 枚举
  - 添加 `Plugin.get_priority()` 默认实现（返回 0）
  - 添加 `Plugin.get_types()` 默认实现（返回 `{get_type()}`，多接口插件覆写）
  - 添加 `Plugin.initialize()` 默认实现（空操作）
  - 添加 `Plugin.shutdown()` 默认实现（空操作）
  - 保留 `get_name()`, `get_type()`, `execute()` 为抽象方法

- [x] 1.2 重写 `core/plugin_manager.py`
  - 移除 `interfaces: dict[type, list[Plugin]]` 字典
  - 添加 `_by_type: dict[PluginType, list[Plugin]]` 字典
  - 修改 `register()` 按 `plugin.get_types()` 索引到每个类型（多接口插件可被任意类型查到）
  - 修改 `get()` 接受 `PluginType` 参数
  - 修改 `get_all()` 接受 `PluginType` 参数，按 priority 排序
  - 添加 `get_by_name()` 方法
  - 移除 `ArbitrationPluginInterface` 单例检查
  - 移除 `collect_schema_extensions()` 和 `collect_node_extensions()` 特殊方法
  - 移除对 `interfaces/` 的所有非 TYPE_CHECKING 导入

## Phase 2: 接口层

- [x] 2.1 适配 `interfaces/entry_plugin.py`
  - 继承 `Plugin`（从 `mcs.core.plugin` 导入）
  - 实现 `get_type()` 返回 `PluginType.ENTRY`
  - 实现 `execute()` 委托给 `locate()`
  - 将 `priority: ClassVar[int]` 改为 `get_priority()` 方法
  - 将 `exclusive: ClassVar[bool]` 改为 `exclusive` 属性

- [x] 2.2 适配 `interfaces/trim_plugin.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.TRIM`
  - 实现 `execute()` 委托给 `trim()`

- [x] 2.3 适配 `interfaces/arbitration_plugin.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.ARBITRATION`
  - 实现 `execute()` 委托给 `arbitrate()`

- [x] 2.4 适配 `interfaces/postprocess_plugin.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.POSTPROCESS`
  - 实现 `execute()` 委托给 `process()`
  - 添加 `position` 属性（默认 `"query_postprocess"`）

- [x] 2.5 适配 `interfaces/compaction_plugin.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.COMPACTION`
  - 实现 `execute()` 委托给 `run()`

- [x] 2.6 适配 `interfaces/storage.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.STORAGE`
  - `execute()` 抛 `NotImplementedError`（无统一语义）
  - 移除 `initialize()` 抽象（由 Plugin 提供默认实现）

- [x] 2.7 适配 `interfaces/index.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.INDEX`
  - `execute()` 抛 `NotImplementedError`

- [x] 2.8 适配 `interfaces/llm.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.LLM`
  - 实现 `execute()` 委托给 `call()`
  - 保留 `PromptBundle` 和其他方法不变

- [x] 2.9 适配 `interfaces/node_extension.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.NODE_EXTENSION`
  - `execute()` 抛 `NotImplementedError`

- [x] 2.10 适配 `interfaces/storage_schema_ext.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.STORAGE_SCHEMA_EXT`
  - `execute()` 抛 `NotImplementedError`

- [x] 2.11 适配 `interfaces/maintenance.py`
  - 继承 `Plugin`
  - 实现 `get_type()` 返回 `PluginType.MAINTENANCE`
  - 实现 `execute()` 委托给 `run()`

## Phase 3: 管线层

- [x] 3.1 适配 `core/query_engine.py`
  - 将 `plugin_manager.get_all(EntryPluginInterface)` 改为 `plugin_manager.get_all(PluginType.ENTRY)`
  - 将 `plugin_manager.get(TrimPluginInterface)` 改为 `plugin_manager.get(PluginType.TRIM)`
  - 将 `plugin_manager.get(ArbitrationPluginInterface)` 改为 `plugin_manager.get(PluginType.ARBITRATION)`
  - 将 `plugin_manager.get_all(PostprocessPluginInterface)` 改为 `plugin_manager.get_all(PluginType.POSTPROCESS)`
  - 更新 `TYPE_CHECKING` 导入

- [x] 3.2 适配 `core/write_pipeline.py`
  - 将 `plugin_manager.get_all(PostprocessPluginInterface)` 改为 `plugin_manager.get_all(PluginType.POSTPROCESS)`
  - 将 `plugin_manager.get_all(IndexInterface)` 改为 `plugin_manager.get_all(PluginType.INDEX)`
  - 将 `plugin_manager.get_all(CompactionPluginInterface)` 改为 `plugin_manager.get_all(PluginType.COMPACTION)`
  - 将 `plugin_manager.get(StorageInterface)` 改为 `plugin_manager.get(PluginType.STORAGE)`
  - 更新 `TYPE_CHECKING` 导入

- [x] 3.3 适配 `core/context_renderer.py`
  - 将 `plugin_manager.get_all(NodeExtensionInterface)` 改为 `plugin_manager.get_all(PluginType.NODE_EXTENSION)`
  - 更新 `TYPE_CHECKING` 导入

## Phase 4: 插件层 (Phase 1)

- [x] 4.1 适配 `plugins/phase1/alias_index.py`
  - 移除 `Plugin` 多重继承，多继承 `EntryPluginInterface` + `IndexInterface` + `NodeExtensionInterface`
  - 实现 `get_name()` 返回 `"alias_index"` 或 `"alias_entry"`
  - 实现 `get_type()` 返回对应类型
  - 移除 `name`, `version`, `interfaces` ClassVar
  - 实现 `get_priority()` 替代 `priority` ClassVar
  - `AliasIndexPlugin` 覆写 `get_types()` 返回 `{INDEX, NODE_EXTENSION}`（多接口登记）

- [x] 4.2 适配 `plugins/phase1/hub_fallback.py`
  - 单继承 `EntryPluginInterface`
  - 实现 `get_name()`, `get_type()`, `get_priority()`
  - `exclusive` 改为属性

- [x] 4.3 适配 `plugins/phase1/priority_trim.py`
  - 单继承 `TrimPluginInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.4 适配 `plugins/phase1/rerank.py`
  - 单继承 `PostprocessPluginInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.5 适配 `plugins/phase1/source_tracking.py`
  - 多继承 `PostprocessPluginInterface` + `NodeExtensionInterface` + `StorageSchemaExtensionInterface`
  - 实现 `get_name()`, `get_type()`
  - `SourceTrackingPlugin` 覆写 `get_types()` 返回 `{NODE_EXTENSION, STORAGE_SCHEMA_EXT}`（多接口登记，保证 schema 扩展不丢）

- [x] 4.6 适配 `plugins/phase1/fanout_reducer.py`
  - 单继承 `CompactionPluginInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.7 适配 `plugins/phase1/community_merger.py`
  - 单继承 `CompactionPluginInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.8 适配 `plugins/phase1/summary_regen.py`
  - 单继承 `CompactionPluginInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.9 适配 `plugins/phase1/summary.py`
  - 单继承 `NodeExtensionInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.10 适配 `plugins/phase1/sqlite_storage.py`
  - 单继承 `StorageInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.11 适配 `plugins/phase1/deepseek_llm.py`
  - 单继承 `LLMInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.12 适配 `plugins/phase1/claude_llm.py`
  - 单继承 `LLMInterface`
  - 实现 `get_name()`, `get_type()`

- [x] 4.13 适配 `plugins/phase1/ollama_llm.py`
  - 单继承 `LLMInterface`
  - 实现 `get_name()`, `get_type()`

## Phase 5: 插件层 (Phase 2)

- [x] 5.1 适配 `plugins/phase2/arbitration.py`
  - Stub 文件，无需改动（Phase 2 未实现）

- [x] 5.2 适配 `plugins/phase2/confidence.py`
  - Stub 文件，无需改动

- [x] 5.3 适配 `plugins/phase2/event_layer.py`
  - Stub 文件，无需改动

- [x] 5.4 适配 `plugins/phase2/gc.py`
  - Stub 文件，无需改动

- [x] 5.5 适配 `plugins/phase2/timeseries_entry.py`
  - Stub 文件，无需改动

- [x] 5.6 适配 `plugins/phase2/versioning.py`
  - Stub 文件，无需改动

## Phase 6: 清理与集成

- [x] 6.1 删除 `plugins/base.py`

- [x] 6.2 适配 `mcs/__init__.py`
  - 更新 `_default_plugin_registry()`
  - 更新 `MCS.initialize()` 中的插件实例化逻辑
  - 移除对 `Plugin` 基类的旧导入

- [x] 6.3 更新测试文件
  - `tests/test_skeleton.py`：适配新基类，移除 ArbitrationPlugin 单例测试
  - `tests/test_plugin_chains.py`：适配新基类
  - `tests/test_persistence.py`：适配新基类
  - 其他测试文件按需适配

- [x] 6.4 运行完整测试套件
  - 执行 `.venv/Scripts/python.exe -m pytest tests/ -q`：354 passed

- [x] 6.5 更新 `openspec/specs/plugin-protocol/spec.md`
  - 通过本 change 的 `specs/plugin-protocol/spec.md` delta 落地（归档时应用）
  - 移除 ClassVar 约定（priority 改 `get_priority()`、exclusive 改属性）
  - 新增 Plugin 基类 / PluginType 枚举 / get_types 多接口登记 / core 不依赖 interfaces 等要求

- [x] 6.6 更新 `CLAUDE.md`
  - 在「开关 / 工程」节增补一行指向插件协议（`core/plugin.py` + `PluginType` + `PluginManager` 按类型索引）