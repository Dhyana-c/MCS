## Why

当前 GraphStore 是纯内存实现，写入管线每次 `ingest()` 完成后图变更只停留在内存中，不会自动持久化到 SQLite。长时间运行场景（如批量摄入 HotpotQA 7405 条数据）中途崩溃会丢失所有已摄入数据，必须从头重来。需要一个自动落盘机制，确保每次写入后变更可靠地持久化。

## What Changes

- WritePipeline 在阶段 ⑤ 图更新完成后，自动将变更的节点和边持久化到 StorageInterface
- 新增 `AutoPersistPlugin`（PostprocessPlugin，position=write_postprocess），在 ingest 末尾自动调用 storage.save_node / save_edge
- MCS 顶层 `ingest()` 返回前触发落盘（作为后置处理链的一部分）
- 支持配置开关 `auto_persist: true/false`，默认开启
- 查询启动时若图为空，自动从 StorageInterface 加载已有数据（load-on-startup）
- 现有 SQLiteStoragePlugin 的 `save()` / `load()` 接口不变，仅新增增量落盘路径

## Capabilities

### New Capabilities
- `auto-persistence`: 每次写入后自动将变更增量持久化到存储后端，以及查询时按需加载已有数据

### Modified Capabilities
- `write-pipeline`: 阶段 ⑥ 压缩判定插件链执行后，增加自动落盘步骤
- `plugin-protocol`: PostprocessPlugin 的 position 新增 `write_postprocess` 挂载点（当前已有 `write_preprocess`，需补 `write_postprocess`）

## Impact

- `mcs/core/write_pipeline.py`: ingest 末尾增加落盘调用
- `mcs/plugins/phase1/`: 新增 AutoPersistPlugin
- `mcs/core/config.py`: MCSConfig 增加 auto_persist 配置项
- `mcs/__init__.py`: MCS.initialize() 中增加 load-on-startup 逻辑
- `mcs/plugins/phase1/sqlite_storage.py`: 无改动，复用现有 save_node / save_edge
- `mcs/interfaces/storage.py`: 无改动，接口已满足需求
