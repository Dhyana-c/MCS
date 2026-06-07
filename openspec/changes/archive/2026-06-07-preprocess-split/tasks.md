# Tasks: preprocess-split — 前置处理插件拆分

## 任务清单

### 1. PluginType 枚举扩展

**文件**: `mcs/core/plugin.py`

- [x] 新增 `WRITE_PREPROCESS = "write_preprocess"`
- [x] 新增 `QUERY_PREPROCESS = "query_preprocess"`
- [x] 设置 `PREPROCESS = "write_preprocess"` 作为废弃别名
- [x] 更新枚举文档注释

### 2. 新接口文件创建

**文件**: `mcs/interfaces/write_preprocess_plugin.py`（新建）

- [x] 创建 `WritePreprocessPluginInterface` 类
- [x] `get_type()` 返回 `PluginType.WRITE_PREPROCESS`
- [x] `preprocess(text: str, ctx: WriteContext) -> str` 方法签名
- [x] 添加短路语义文档

**文件**: `mcs/interfaces/query_preprocess_plugin.py`（新建）

- [x] 创建 `QueryPreprocessPluginInterface` 类
- [x] `get_type()` 返回 `PluginType.QUERY_PREPROCESS`
- [x] `preprocess(text: str, ctx: QueryContext) -> str` 方法签名

### 3. 废弃兼容层

**文件**: `mcs/interfaces/preprocess_plugin.py`（修改）

- [x] 保留文件作为废弃兼容层
- [x] `PreprocessPluginInterface = WritePreprocessPluginInterface` 别名
- [x] 导入时发出 `DeprecationWarning`

### 4. 接口导出更新

**文件**: `mcs/interfaces/__init__.py`

- [x] 导出 `WritePreprocessPluginInterface`
- [x] 导出 `QueryPreprocessPluginInterface`
- [x] 保留 `PreprocessPluginInterface` 导出（废弃）

### 5. 管线调用变更

**文件**: `mcs/core/write_pipeline.py`

- [x] `_run_preprocess` 改用 `PluginType.WRITE_PREPROCESS`
- [x] `_mark_ingested_if_success` 改用 `PluginType.WRITE_PREPROCESS`
- [x] 类型标注使用 `WriteContext`

**文件**: `mcs/core/query_engine.py`

- [x] `_run_preprocess` 改用 `PluginType.QUERY_PREPROCESS`
- [x] 类型标注使用 `QueryContext`

### 6. 现有插件迁移

**文件**: `mcs/plugins/phase1/source_tracking.py`

- [x] `IdempotencyCheckPlugin` 继承 `WritePreprocessPluginInterface`
- [x] `preprocess` 方法签名改为 `ctx: WriteContext`
- [x] 移除 `getattr(ctx, "metadata", {})` hack，直接访问 `ctx.metadata`

### 7. 测试更新

**文件**: `tests/test_plugin_chains.py`

- [x] 新增 `WRITE_PREPROCESS` 类型注册测试
- [x] 新增 `QUERY_PREPROCESS` 类型注册测试
- [x] 新增两个类型互不干扰测试
- [x] 新增废弃别名测试（发出警告）
- [x] 更新现有 `PREPROCESS` 测试使用新类型

**文件**: `tests/test_pipeline_write.py`

- [x] 更新导入 `WritePreprocessPluginInterface`
- [x] 测试插件继承新接口
- [x] 验证管线使用 `WRITE_PREPROCESS`

**文件**: `tests/test_pipeline_query.py`

- [x] 更新导入 `QueryPreprocessPluginInterface`
- [x] 测试插件继承新接口
- [x] 验证管线使用 `QUERY_PREPROCESS`

### 8. 文档更新

**文件**: `openspec/specs/plugin-protocol/spec.md`（如存在）

- [x] 更新 PluginType 枚举说明
- [x] 新增两个接口文档
- [x] 标记废弃内容

**文件**: `CLAUDE.md`

- [x] 更新插件类型列表

## 依赖顺序

```
[1] ──▶ [2] ──▶ [3] ──▶ [4]
         │
         ▼
[5] ──▶ [6] ──▶ [7] ──▶ [8]
```

- 任务 1-4 可并行
- 任务 5-6 依赖 1-4 完成
- 任务 7 依赖 5-6 完成
- 任务 8 可在任意阶段进行