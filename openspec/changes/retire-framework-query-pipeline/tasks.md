# Tasks — retire-framework-query-pipeline

> 顺序推进；每个 phase 结束跑 `.venv\Scripts\python.exe -m pytest -q` + `openspec validate retire-framework-query-pipeline` 守门。宪法级——**Phase 4（spec/CLAUDE.md）的内容定型先于代码最终化**，但代码删除可在 Phase 1-3 先做（spec 同步在 archive 前必须完成）。

## Phase 0 — 准备

- [x] T0.1 已核定（grep 落定，见 design「已核定项」）：`Subgraph` 留（store 用）、`QueryContext` 留且瘦身、`select_facts`（读 bundle）删只留 `select_facts_write`、`render_query_result` 级联删。
- [ ] T0.2 核定 bench 行级边界：`multihop_rag/scripts/agent_case_study.py` / `_common.py` 哪些行是框架基线、哪些是 agent 案例；`locomo/agent_eval.py` 检索轨与 agent 轨的分界；`golden_cage/runner.py` mode=mcs 段范围。

## Phase 1 — 核心删除（读查询编排）

- [x] T1.1 `mcs/core/query_engine.py`：删 `query()`、`_arbitrate`、`_run_postprocess`、`_run_postprocess_nodes`；`query_nodes()` 固化 `skip_postprocess=True`、删 ④⑤ 分支；重写模块 docstring（"图导航+遍历原语，供写管线关联定位与 agent 导航复用；不再提供读查询编排"）。
- [x] T1.2 `mcs/core/query_engine.py::_run_preprocess`：**方法留**（`locate_seeds:197` 依赖它）；删 `PluginType.QUERY_PREPROCESS` 枚举后方法体收敛为纯 `return text` 透传（无插件链可遍历）。`query_nodes`/`locate_seeds` 仍调它、行为不变。
- [x] T1.3 `mcs/core/mcs.py`：删 `MCS.query()`；`MCS.show()` 删 "Reader Pipeline" mermaid 段与 read_plugins 展示。
- [x] T1.4 `mcs/__init__.py`：docstring 删 `mcs.query()` 示例（保留 ingest 示例）。
- [x] T1.5 `mcs_agent/memory.py`：删 `associate` 的 `mode="mcs"` 分支（line 301-306）；`mode` 参数仅留 `neighbors`；更新 `_do_associate` docstring。
- [x] T1.6 `mcs_agent/tools.py`：删 `associate` schema 里关于 `mode=mcs` 的注释（line 200-203）；`mode` 不再暴露（若仅剩单模式则考虑从 schema 移除 mode 参数）。
- [x] T1.7 `mcs_agent/loop.py:61`：删/改过时 system prompt"associate：mode=mcs 已实现（主力）"。
- [x] T1.8 `Subgraph` 实体**保留**（store 图视图方法仍用）；仅删 `query()` 对它的使用与 `render_query_result` 的 Subgraph 分支。
- [x] T1.9 `mcs/rendering.py`：删 `render_query_result`（级联——唯一调用者 `associate(mode="mcs")` 已删）；留 `format_ingest_status`。
- [x] T1.10 `QueryContext` 瘦身：删 `intermediate`/`result_set`/`selected_edges`（随 query() 退役），留 `system_prompt`/`user_input`/`universe`/`metadata`（ENTRY/TRIM 接口仍收 ctx）。
- [x] T1.11 `mcs/prompts/`：删读侧 `select_facts` prompt bundle（仅 query() 用），留 `select_facts_write` + `SelectFactsResult` + `coerce_select_result`。
- [x] T1.12 `mcs/prompts/arbitrate.py`：删（④ `arbitrate` purpose bundle，零 caller）；`adjudicate.py` **留**、更 :8 消歧注释（`LLMArbitrationPlugin` 退役）。

## Phase 2 — 插件清理

- [x] T2.1 `mcs/core/plugin.py`：`PluginType` 枚举删 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS`。
- [x] T2.2 删接口：`mcs/interfaces/arbitration_plugin.py` / `postprocess_plugin.py` / `query_preprocess_plugin.py`；更新 `mcs/interfaces/__init__.py`。
- [x] T2.3 删实现：`mcs/plugins/postprocess/rerank.py`（含 `LexicalScorer`）+ `mcs/plugins/arbitration/`（空目录）。**保留 `summary.py`**（`SummaryPlugin` 是 NodeExtensionInterface 子类、管 summary 槽）+ `__init__.py` 保留 `SummaryPlugin` import（仅删 RerankPlugin import）。
- [x] T2.4 `mcs/core/plugin_manager.py`：删 ARBITRATION 单例强制逻辑（line 51-62 区域）。
- [x] T2.5 `mcs/core/query_engine.py`：删对上述 PluginType 的所有 `get_all`/`get` 引用（Phase 1 已删方法，此处清扫残留 import/分支）。
- [x] T2.6 `mcs/presets/phase1.py`：默认注册表删 `rerank` opt-in 条目（`summary` **保留**——NodeExtension）。
- [x] T2.7 修 stale docstring：`mcs/entities/config.py:22`（`# Postprocess (write_preprocess)` → `# WRITE_PREPROCESS`）、`mcs/interfaces/trim_plugin.py:21`（删"查询阶段 ④ 作为 PriorityArbitration 底层"——`_arbitrate` 从不调 TrimPlugin）、`mcs/core/write_pipeline.py:7`（PostprocessPlugin chain → WritePreprocessPlugin chain）。
- [x] T2.8 `mcs/core/errors.py:63`：更新 `ConfigurationError` docstring（移除"注册了多个 ArbitrationPlugin"）。

## Phase 3 — benchmark 删框架基线轨（保留 agent 评测轨）

- [ ] T3.1 `bench/multihop_rag/runner.py`：删框架 BFS runner（`mcs.query(q.query)` 路径）；若整个 runner 即框架基线则删文件、留 agent runner。
- [ ] T3.2 `bench/multihop_rag/scripts/`：删 `diag_dualrole.py` / `diagnose_bfs_root.py` / `exp_rankfail_rerank.py`（直调 `_traverse`/`mcs.query` 的诊断脚本）；`agent_case_study.py` 按 T0.2 核定删框架段、留 agent 段。
- [ ] T3.3 `bench/locomo/scripts/agent_eval.py`：删检索轨（`mcs.query(question, universe=sample_id)`），留 agent 轨。
- [ ] T3.4 `bench/golden_cage/runner.py`：删 `mode=mcs` 轨，留 agent 轨。
- [ ] T3.5 同步 bench 相关 spec：`multihop-rag-eval` / `locomo-eval` / `bench-doc-rerank` / `bench-doc-rerank-plugin` 中描述框架基线的部分。

## Phase 4 — spec + CLAUDE.md + docs（宪法级，archive 前必须完成）

> **9 份 delta 已在 proposal 阶段起草**（`specs/{query-pipeline,lightweight-query,query-rerank,plugin-protocol,mcs-builder,memory-agent,result-rendering,phase1-defaults,mcs-presets}/spec.md`）。本 phase 任务 = 核对 delta 与现行 spec 逐条对齐、补全 MODIFIED requirement 完整正文、apply 到 main spec。

- [ ] T4.1 `query-pipeline` delta（已起草）：核对 18 条 REMOVED 标题与现行 spec 逐字一致；apply 后整目录从 main spec 移除。
- [ ] T4.2 `query-rerank` delta（已起草）：3 条 REMOVED 核对；apply 后整目录移除；从 `INDEX.md` 摘除。
- [ ] T4.3 `lightweight-query` delta（已起草）：核对 2 MODIFIED（query_nodes 去 skip_postprocess / select_facts_write 去读侧引用）+ 9 ADDED（locate_seeds/ENTRY/HubFallback/TrimPlugin/`_traverse`×3/frontier-accumulated/瘦身 QueryContext）正文完整。
- [ ] T4.4 `mcs-builder` delta（已起草）：补全「MCS 类瘦门面设计」与「show 方法」MODIFIED 完整正文（删 query API + Reader Pipeline mermaid 段）。
- [ ] T4.5 `plugin-protocol` delta（已起草）：3 接口 REMOVED + MCSBuilder 抽象基类 MODIFIED（PluginType 枚举删 3 值、删 ArbitrationPlugin 单例检查）核对。
- [ ] T4.6 `memory-agent` delta（已起草）：2 MODIFIED（渲染纯函数 / associate 原语）核对，删 mcs 模式相关 scenario。
- [ ] T4.7 `phase1-defaults` delta（已起草）：补全默认清单 MODIFIED 完整正文（**SummaryPlugin 保留** + 删 2 默认空 scenario + Idempotency 标注）。`mcs-presets` **无 delta**（SummaryPlugin 是 NodeExtension、shared 不变）。
- [ ] T4.7b `preprocess-plugin` delta（已起草）：补全废弃指向 MODIFIED 完整正文（去 QueryPreprocess）。
- [ ] T4.8 `result-rendering` delta（已起草）：补全「核心库提供共享结果渲染纯函数」MODIFIED 完整正文（删 render_query_result，留 format_ingest_status）。
- [ ] T4.9 CLAUDE.md：「总体流程·查询 `query`」段改写为"查询由 agent 驱动；框架仅提供图底座原语（locate_seeds/get_related_events/narrative_timeline/_traverse/query_nodes）"；插件类型清单删 `ARBITRATION`/`POSTPROCESS`/`QUERY_PREPROCESS`；「四区硬比例仅框架查询路径」条更新或删；MCS 顶层描述"双管线"措辞调整为"写管线 + 图原语只读入口"。
- [ ] T4.10 docs：`docs/api-reference.md`（删 `query` 行）、`docs/faq.md`（BFS/rerank 措辞）、`docs/INDEX.md` + `openspec/specs/INDEX.md`（query-pipeline/query-rerank 条目摘除）、`docs/memory-agent.md`（arbitrate 消歧 + associate 模式措辞）、`docs/architecture.md`（读写管线段 + PluginType 清单）、`docs/graph-model-design.md`（§4.3/§5.1/§5.2）、`docs/getting-started.md`（§4 查询）、`docs/plugin-system.md`（PluginType 表 + 内置清单去 rerank）、`examples/README.md`（query demo 描述）。
- [ ] T4.10b diagrams（5 个 `.mmd`）：`docs/diagrams/{query,gmd-workzones,select-facts-dualrole-flow,plugin-chain,arch-system-overview}.mmd`——删或重画（read 侧退役；`_traverse` 返 accumulated 取代"后处理 → Subgraph"；plugin-chain 读侧改 ENTRY+TRIM→`_traverse`）。
- [ ] T4.11 `CHANGELOG.md`：追加本 change 条目。

## Phase 5 — tests + examples

- [x] T5.1 删纯 query 管线测试：`test_pipeline_query.py`（主体）、`test_rerank.py`、`test_separate_accumulate_frontier.py` 中 query 专属部分。
- [x] T5.2 改写存活测试：`test_rw_select_prompt_split.py`（保留 select_facts_write 路径、删 select_facts 读路径）、`test_mcs_api.py`（删 query 用例、留 ingest）、`test_builder_token_counter.py` 等。
- [ ] T5.3 `test_agent_memory.py`：删 `mode=mcs` 相关测试（line 369/374/386/1168 等）。
- [x] T5.3b `test_plugin_chains.py`：删 QUERY_PREPROCESS 测试（line 16 import、159-197 注册/发现/与 WRITE_PREPROCESS 独立性——随类型删）。
- [ ] T5.4 examples：`basic_usage.py` / `wiki_example.py` 删 `mcs.query()` 段或改为 agent 调用示例。
- [x] T5.5 全量回归：`.venv\Scripts\python.exe -m pytest -q` 全绿；`openspec validate retire-framework-query-pipeline` 通过；人工核对 CLAUDE.md 与代码一致。

## Phase 6 — 归档

- [ ] T6.1 `openspec archive retire-framework-query-pipeline`（delta 落 main spec、change 移入 archive）。
- [ ] T6.2 更新记忆 `pending-proposals-queue`（标记本 change 已归档）。
