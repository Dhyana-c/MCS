## 1. 新增插件类型枚举

- [x] 1.1 在 `mcs/core/plugin.py` 的 `PluginType` 枚举中添加 `SEED_SELECTOR = "seed_selector"`

## 2. 新增插件接口

- [x] 2.1 创建 `mcs/interfaces/seed_selector_plugin.py`，定义 `SeedSelectorPluginInterface`
  - 继承 `Plugin`
  - `get_type()` 返回 `PluginType.SEED_SELECTOR`
  - 抽象方法 `select(seeds: list[Node], query: str, budget: int, ctx) -> list[Node]`
  - `execute()` 委托给 `select()`
- [x] 2.2 更新 `mcs/interfaces/__init__.py`，导出 `SeedSelectorPluginInterface`

## 3. 更新 PluginManager

- [x] 3.1 验证 `mcs/core/plugin_manager.py` 支持新插件类型 `SEED_SELECTOR`

## 4. 重构 QueryEngine._traverse

- [x] 4.1 删除 `QueryEngine.__init__` 的 `max_picked` 参数
- [x] 4.2 新增 `QueryEngine.__init__` 的 `max_accumulated_nodes` 参数（默认 1000）
- [x] 4.3 重构 `_traverse`：
  - `accumulated` 初始化为空列表
  - `visited` 初始化为空集合
  - 删除 `max_picked` 相关逻辑
  - 实现 token 预算检查（每轮后检查 `accumulated` token 是否 > budget）
  - 实现 LLM 筛选：`llm.call(purpose="select_nodes", ...)`
  - 仅将选中节点加入 `accumulated` 和 `visited`
  - 未选中节点不加 `visited`
  - 实现安全阀：`max_rounds` 和 `max_accumulated_nodes`
- [x] 4.4 实现单轮候选超预算时的分批 LLM 调用逻辑

## 5. 重构 QueryEngine._locate_seeds

- [x] 5.1 在 TrimPlugin 之后增加 SeedSelectorPlugin 链调用
- [x] 5.2 支持多个 SeedSelectorPlugin 串联
- [x] 5.3 SeedSelectorPlugin 链为空时跳过

## 6. 实现默认 LLMSeedSelectorPlugin

- [x] 6.1 创建 `mcs/plugins/phase1/llm_seed_selector.py`
  - 实现 `LLMSeedSelectorPlugin`，继承 `SeedSelectorPluginInterface`
  - `priority=0`（默认兜底）
  - 使用 `llm.call(purpose="select_nodes", ...)` 筛选相关种子
  - 返回预算内的种子子集
- [x] 6.2 在默认配置中注册 `LLMSeedSelectorPlugin`

## 7. 测试与验证

- [x] 7.1 更新 `tests/core/test_query_engine.py`：
  - 删除 `max_picked` 相关测试
  - 新增 token 预算驱动遍历的测试
  - 新增 `visited` 语义测试（仅选中者加入）
  - 新增分批 LLM 调用测试
  - 新增 SeedSelectorPlugin 链的测试
  - 新增安全阀测试
- [x] 7.2 更新 `tests/interfaces/` 下的接口测试
- [x] 7.3 运行完整测试套件：`.venv/Scripts/python.exe -m pytest -q`

## 8. 文档更新

- [x] 8.1 更新 `openspec/specs/plugin-protocol/spec.md`（归档时自动合并 delta）
- [x] 8.2 更新 `openspec/specs/query-pipeline/spec.md`（归档时自动合并 delta）

## 9. 依赖检查

- [x] 9.1 确认 `preprocess-plugin-type` 变更已完成并归档
