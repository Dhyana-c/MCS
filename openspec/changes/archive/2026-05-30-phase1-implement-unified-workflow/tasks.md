## 1. 接口层改造

- [x] 1.1 删除 `mcs/interfaces/pipeline_hook.py`
- [x] 1.2 删除 `mcs/interfaces/query_hook.py`
- [x] 1.3 重写 `mcs/interfaces/llm.py`：删除旧 7 个语义方法；新增 `LLMInterface.call(purpose, nodes_in, free_args) -> ParsedResult`；新增 `register_prompt(purpose, system, template, parser)` / `get_prompt(purpose)` 注册点；新增 `set_caller(callable)` 让插件可注入 llm_caller 给 CompactionPlugin
- [x] 1.4 扩展 `mcs/interfaces/node_extension.py`：新增可选方法 `render(node, purpose: str) -> str | None`（默认返回 None）
- [x] 1.5 新增 `mcs/interfaces/entry_plugin.py`：`EntryPluginInterface`（类属性 `priority: int`、`exclusive: bool=False`；抽象方法 `locate(query, ctx) -> List[Node]`）
- [x] 1.6 新增 `mcs/interfaces/trim_plugin.py`：`TrimPluginInterface`（抽象方法 `trim(nodes, budget) -> List[Node]`）
- [x] 1.7 新增 `mcs/interfaces/arbitration_plugin.py`：`ArbitrationPluginInterface`（抽象方法 `arbitrate(accumulated, query, ctx) -> List[Node]`）
- [x] 1.8 新增 `mcs/interfaces/postprocess_plugin.py`：`PostprocessPluginInterface`（抽象方法 `process(input, ctx) -> Any`）
- [x] 1.9 新增 `mcs/interfaces/compaction_plugin.py`：`CompactionPluginInterface`（抽象方法 `should_run(changed_nodes, graph) -> bool` 与 `run(changed_nodes, graph, llm_caller) -> None`）

## 2. 核心引擎改造

- [x] 2.1 删除 `mcs/core/serializer.py`
- [x] 2.2 新增 `mcs/core/context_renderer.py`：`ContextRenderer.render(nodes_in, purpose) -> str` 主方法 + `get_summary(node)` 静态 helper；按 §4 设计图分 purpose 渲染策略；遍历 NodeExtension 调用 `render(node, purpose)` 聚合
- [x] 2.3 重写 `mcs/core/write_pipeline.py`：
  - 定义 `WriteContext` dataclass（7 字段）
  - 定义 `ConceptDraft` 与 `Decision` / `DecisionList` 数据结构（拆到 `mcs/core/decisions.py`）
  - 实现 `WritePipeline.ingest(text, **metadata)` 按 6 段管线执行
  - 实现 `_apply_decisions(decisions, graph)` 派发器（merge / create / attach_statement / no_op）
- [x] 2.4 重写 `mcs/core/query_engine.py`：
  - 定义 `QueryContext` dataclass（4 字段）
  - 实现 `QueryEngine.query(text, existing_context=None) -> Any` 按 5 段管线执行；默认返回 `result_set: List[Node]`
  - 实现 ③ BFS Loop（visited + max_rounds + max_picked + 每节点一次 decide_directions LLM 调用）
- [x] 2.5 升级 `mcs/core/plugin_manager.py`：
  - `register` 时按接口类型分桶
  - `get_all(EntryPluginInterface)` 按 priority 降序排列
  - 注册第 2 个 `ArbitrationPluginInterface` 抛配置错误
  - 提供 `collect_node_extensions()` 给 ContextRenderer 用
- [x] 2.6 更新 `mcs/core/config.py`：
  - `MCSConfig.knowledge_graph()` 工厂方法返回新默认插件清单（11 个，含 `max_rounds=5` / `max_picked=50`）
  - 增加 `prompt_overrides: dict[str, dict] = field(default_factory=dict)` 字段供用户覆盖 prompt

## 3. Phase 1 插件实现

- [x] 3.1 拆分 `mcs/plugins/phase1/alias_index.py`：
  - 保留 `AliasIndexPlugin` 作 NodeExtension（管理 `extensions["alias_entry"]["aliases"]`）
  - 新增 `AliasEntryPlugin`（实现 `EntryPluginInterface`，priority=100，使用内部别名词典做 locate）
  - 实现写流程 ⑤ 后的 aliases 索引同步逻辑（不通过旧 hook，改为节点变更通知或 PostprocessPlugin 形式）
- [x] 3.2 新增 `mcs/plugins/phase1/hub_fallback.py`：`HubFallbackEntryPlugin`（priority=0，返回 hub-role 节点作为兜底种子；LLM 顶点导航留为未来增强）
- [x] 3.3 新增 `mcs/plugins/phase1/priority_trim.py`：`PriorityTrimPlugin`（按 token 估算累加裁剪；保持顺序）
- [x] 3.4 重写 `mcs/plugins/phase1/summary.py`：
  - NodeExtension 管理 `extensions["summary"]["text"]` 与 `generated_at`
  - 实现 `render(node, purpose)` 返回 None（核心字段由 ContextRenderer 自取）
- [x] 3.5 重写 `mcs/plugins/phase1/source_tracking.py`：
  - NodeExtension 管理 `extensions["source_tracking"]["sources"]`
  - 实现 `render(node, purpose)`：仅 `purpose=synthesize` 时返回 "出处: ..."
  - 提供 `IdempotencyCheckPlugin`（PostprocessPluginInterface, position=write_preprocess）做 chunk 幂等
  - 保留 `update_document` / `purge_orphans` 公共 API
- [x] 3.6 新增 `mcs/plugins/phase1/fanout_reducer.py`：`FanoutReducerPlugin` 实现 `CompactionPluginInterface`；should_run 检查节点扇出超阈值；run 调 LLM `decide_hub` 选枢纽并提升其 role
- [x] 3.7 新增 `mcs/plugins/phase1/summary_regen.py`：`SummaryRegenPlugin` 实现 `CompactionPluginInterface`；should_run 检查 summary 缺失或内容变更；run 调 LLM `gen_summary` 重生成 `extensions["summary"]`
- [x] 3.8 重写 `mcs/plugins/phase1/sqlite_storage.py`：
  - 实现 `StorageInterface`，动态收集 schema 扩展构建 schema
  - 支持 `save` / `load` 全图快照、`save_node` / `save_edge` 单项持久化
- [x] 3.9 重写 `mcs/plugins/phase1/deepseek_llm.py`：
  - 实现 `LLMInterface._raw_call(system, user)` 厂商适配
  - 渲染、prompt 组装、解析全部继承自 `LLMInterface.call` 基类实现
  - 厂商插件零 prompt 模板

## 4. Prompt 模板

- [x] 4.1 重组 `mcs/prompts/`：删除旧 7 个模板常量；按 9 个 purpose 新建 `extract_concepts.py` / `judge_relations.py` / `decide_directions.py` / `decide_hub.py` / `navigate_hub.py` / `arbitrate.py` / `synthesize.py` / `gen_aliases.py` / `gen_summary.py`
- [x] 4.2 每个 prompt 文件导出三个常量：`SYSTEM_PROMPT: str` / `USER_TEMPLATE: str` / `parse(raw: str) -> ParsedType`
- [x] 4.3 `mcs/prompts/__init__.py` 提供 `DEFAULT_PROMPTS: dict[str, PromptBundle]` 注册中心

## 5. 测试

- [x] 5.1 更新 `tests/test_skeleton.py`：接口清单变化（删 2、新增 5）；smoke test 仍能通过（milestone A 完成，64 个用例全过）
- [x] 5.2 新增 `tests/test_context_renderer.py`：mock NodeExtension 验证 purpose 驱动渲染 + 贡献者聚合（8 用例）
- [x] 5.3 新增 `tests/test_pipeline_query.py`：mock LLM 跑通 5 段；验证 visited（含环图） / max_rounds / max_picked / 默认返回 List[Node] / existing_context 跳过种子定位 / 后置链输出形态自由（8 用例）
- [x] 5.4 新增 `tests/test_pipeline_write.py`：mock LLM 跑通 6 段；验证 ② 复用 query；验证 DecisionList 派发；验证 ⑥ 压缩链触发与跳过；WriteContext 字段流转（9 用例）
- [x] 5.5 新增 `tests/test_plugin_chains.py`：EntryPlugin 优先级降序；ArbitrationPlugin 单例约束；Postprocess 输出类型自由（6 用例）
- [x] 5.6 新增 `tests/test_decision_apply.py`：4 种 action 派发正确性 + 未知 action 抛 UnknownActionError（8 用例）
- [x] 5.7 新增 `tests/conftest.py` fixtures：`MockLLM` + `mock_llm` / `empty_graph` / `seeded_graph` / `default_config` / `mcs_with_mock_llm`

## 6. 示例与文档

- [x] 6.1 实现 `examples/basic_usage.py`：3 条 ingest + 1 个 query，mock / 真实双模式（`MCS_LLM_MODE` 环境变量切换）
- [x] 6.2 实现 `examples/wiki_example.py`：3 条 markdown chunk 摄入 → 两轮 query 复用 existing_context
- [x] 6.3 更新 `README.md`：安装步骤、`mcs.initialize()` 流程、mock 模式跑通示例、11 插件清单一致化
- [x] 6.4 创建 `examples/README.md`：mock / real 模式切换说明、典型输出

## 7. 验收

- [x] 7.1 `pytest` 全过（107 用例：skeleton 43 + renderer 8 + decisions 8 + pipeline_query 8 + pipeline_write 9 + chains 6 + chains 6 + decision_apply 8 + skeleton plugin/Node checks）
- [x] 7.2 `ruff check .` 零错
- [x] 7.3 当前 `.venv` 中 `pytest && ruff check .` 双绿（干净 venv 重做留给 CI/部署时验证）
- [x] 7.4 `examples/basic_usage.py` 在 mock 模式可跑完不报错；返回的 `query()` 结果是 `List[Node]`，长度 = 1
- [x] 7.5 `openspec validate phase1-implement-unified-workflow --strict` 通过
- [x] 7.6 在真实 DeepSeek API 上跑通 `examples/basic_usage.py`（2026-05-30 验证：model=`deepseek-v4-pro`，3 ingest 抽出 11 个概念，query "什么是深度学习？" 返回 4 个语义相关节点；验证过程中发现并修复两处问题：(1) LLM 输出带 ```json fence，新增 `mcs.utils.text_utils.strip_json_fence` 在 7 个 JSON parser 中统一调用；(2) 新增 `.env` / `.env.example` + examples 内联 dotenv loader 简化真实 API 使用）
