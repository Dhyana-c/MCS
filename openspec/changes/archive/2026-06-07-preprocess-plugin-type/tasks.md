## 1. 新增插件类型枚举

- [x] 1.1 在 `mcs/core/plugin.py` 的 `PluginType` 枚举中添加 `PREPROCESS = "preprocess"`

## 2. 新增插件接口

- [x] 2.1 创建 `mcs/interfaces/preprocess_plugin.py`，定义 `PreprocessPluginInterface`
  - 继承 `Plugin`
  - `get_type()` 返回 `PluginType.PREPROCESS`
  - 抽象方法 `preprocess(text: str, ctx) -> str`
  - `execute()` 委托给 `preprocess()`
- [x] 2.2 更新 `mcs/interfaces/__init__.py`，导出 `PreprocessPluginInterface`

## 3. 修改 PostprocessPluginInterface

- [x] 3.1 删除 `mcs/interfaces/postprocess_plugin.py` 中的 `position` 属性
- [x] 3.2 更新文档注释，明确该接口专用于后置处理

## 4. 更新 PluginManager

- [x] 4.1 验证 `mcs/core/plugin_manager.py` 支持新插件类型 `PREPROCESS`

## 5. 重构 QueryEngine

- [x] 5.1 修改 `_run_preprocess`：
  - 使用 `plugin_manager.get_all(PluginType.PREPROCESS)` 获取前置插件链
  - 删除 `_read_chain_for_position("query_preprocess")` 调用
- [x] 5.2 修改 `_run_postprocess`：
  - 使用 `plugin_manager.get_all(PluginType.POSTPROCESS)` 获取后置插件链
  - 删除 `_read_chain_for_position("query_postprocess")` 调用
- [x] 5.3 删除 `_read_chain_for_position` 方法

## 6. 重构 WritePipeline

- [x] 6.1 修改 `_run_preprocess`：
  - 使用 `plugin_manager.get_all(PluginType.PREPROCESS)` 获取前置插件链
  - 删除 `getattr(p, "position", ...) == "write_preprocess"` 筛选逻辑

## 7. 迁移 IdempotencyCheckPlugin

- [x] 7.1 修改 `mcs/plugins/phase1/source_tracking.py` 中的 `IdempotencyCheckPlugin`：
  - 从继承 `PostprocessPluginInterface` 改为 `PreprocessPluginInterface`
  - `process(input, ctx)` 改为 `preprocess(text, ctx)`
  - 删除 `position` 属性

## 8. 清理 RerankPlugin

- [x] 8.1 修改 `mcs/plugins/phase1/rerank.py` 中的 `RerankPlugin`：
  - 删除 `position` 属性

## 9. 测试与验证

- [x] 9.1 更新 `tests/core/test_query_engine.py`：
  - 新增 PreprocessPlugin 链的测试
  - 验证 `_read_chain_for_position` 已删除
- [x] 9.2 更新 `tests/core/test_write_pipeline.py`：
  - 验证写入前置插件使用新类型
- [x] 9.3 更新 `tests/interfaces/` 下的接口测试
- [x] 9.4 运行完整测试套件：`.venv/Scripts/python.exe -m pytest -q`

## 10. 文档更新

- [x] 10.1 更新 `openspec/specs/plugin-protocol/spec.md`（归档时自动合并 delta）
- [x] 10.2 更新 `openspec/specs/query-pipeline/spec.md`（归档时自动合并 delta）
- [x] 10.3 更新 `openspec/specs/write-pipeline/spec.md`（归档时自动合并 delta）
