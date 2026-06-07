## Why

前置/后置插件共用 `PluginType.POSTPROCESS`，仅靠 `position` 字符串属性区分挂载点，类型系统无法静态约束，运行时才能发现挂载错误。写入管线同样依赖此机制（`write_preprocess`），需一并解决。

## What Changes

### **BREAKING** 插件类型拆分
- 新增 `PluginType.PREPROCESS` 枚举值，用于查询和写入的前置处理
- 新增 `PreprocessPluginInterface`，定义 `preprocess(text: str, ctx) -> str`
- `PostprocessPluginInterface` 专用于后置处理（查询 ⑤ / 写入末尾），删除 `position` 属性
- 查询管线 `_run_preprocess` 改用 `PluginType.PREPROCESS`
- 写入管线 `_run_preprocess` 改用 `PluginType.PREPROCESS`
- 删除 `_read_chain_for_position` 方法

### 插件迁移
- `IdempotencyCheckPlugin`（`position="write_preprocess"`）迁移为 `PreprocessPluginInterface`
- `RerankPlugin`（`position="query_postprocess"`）保持为 `PostprocessPluginInterface`，删除 `position` 属性

## Capabilities

### New Capabilities
- `preprocess-plugin`: 查询和写入管线的前置插件接口，独立类型，处理文本预处理

### Modified Capabilities
- `plugin-protocol`: 新增 `PREPROCESS` 插件类型；`PostprocessPluginInterface` 移除 `position` 属性
- `query-pipeline`: 阶段 ① 使用 `PluginType.PREPROCESS` 查找前置插件
- `write-pipeline`: 阶段 ① 使用 `PluginType.PREPROCESS` 查找前置插件

## Impact

### 代码变更
- `mcs/core/plugin.py`: 新增 `PluginType.PREPROCESS`
- `mcs/interfaces/preprocess_plugin.py`: 新增 `PreprocessPluginInterface`
- `mcs/interfaces/postprocess_plugin.py`: 删除 `position` 属性
- `mcs/core/query_engine.py`: 修改 `_run_preprocess`，删除 `_read_chain_for_position`
- `mcs/core/write_pipeline.py`: 修改 `_run_preprocess`，删除 `_read_chain_for_position` 调用
- `mcs/plugins/phase1/source_tracking.py`: `IdempotencyCheckPlugin` 迁移为 `PreprocessPluginInterface`
- `mcs/plugins/phase1/rerank.py`: 删除 `position` 属性

### API 变更
- **Breaking**: `PostprocessPluginInterface.position` 属性删除
- **Breaking**: 使用 `position` 的插件需迁移类型或删除属性
