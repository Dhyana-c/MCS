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

- [x] T3.1 `bench/multihop_rag/runner.py`：整文件删（框架 BFS runner，`mcs.query` 路径）+ `__main__.py`（import 已删 runner）+ `scripts/{eval,query,test}.py`（纯框架，调 `_common.run_queries`→`mcs.query`）。
- [x] T3.2 `bench/multihop_rag/scripts/`：删 `diag_dualrole.py` / `diagnose_bfs_root.py` / `exp_rankfail_rerank.py`（直调 `_traverse`/`mcs.query` 的诊断脚本）；`agent_case_study.py` 删 `_do_associate` 的 `mode=mcs` 分支（含 `mcs.query` + `render_query_result` import）、对齐 Phase 1 后 base 签名 `(seed_id, limit)`；`_common.py` 删框架查询循环（`run_queries`/`_make_reranker`/`_print_metrics`/`add_query_args`/`_built_titles`/`_count_llm_calls` + 死 import），留 agent + build/compact 共用 utils。
- [x] T3.3 `bench/locomo/scripts/agent_eval.py`：删检索轨（`run_retrieval_eval` + `track` 参数 + `--track` CLI + `retrieved_sessions` import），留 agent QA 轨；`tests/test_locomo_eval.py` 删 `TestRunRetrievalEval`。
- [x] T3.4 `bench/golden_cage/runner.py`：`mode=mcs` 轨已于 Phase 1 删（`_do_associate(seed_id, limit)` 签名、无 `mcs.query`）；本 phase 核定无需再动。
- [x] T3.5 同步 bench spec：加 `bench-utils` delta（MODIFIED「.env 加载」去 runner 场景 +「功能替代」改指 `agent_full_run.py`）——唯一 LIVE spec 引用退役 runner 处；`multihop-rag-eval`/`locomo-eval`/`bench-doc-rerank` 等 spec 不引用框架基线 API、无需动。
- [x] T3.6 **Phase 2 连带 landmine 修复**：`bench/multihop_rag/builder.py::_make_mcs` 删 `if rerank:` 块（删 RerankPlugin 后所有 bench 建图 rerank=True 会炸；locomo builder 透传同款修复）；`case_study_failures.py`/`cf_corpus_rerank.py` 修 broken import（`mcs.plugins.postprocess.rerank._tokenize` → `bench.plugins.doc_rerank._tokenize`）。

## Phase 4 — spec + CLAUDE.md + docs（宪法级，archive 前必须完成）

> **10 份 delta**（`specs/{query-pipeline,lightweight-query,query-rerank,plugin-protocol,mcs-builder,memory-agent,result-rendering,phase1-defaults,preprocess-plugin,bench-utils}/spec.md`）。本 phase = 核对 delta 与现行 spec 逐条对齐、补全 MODIFIED 完整正文、同步 CLAUDE.md/docs/diagrams（delta apply 到 main spec 在 Phase 6 archive 自动完成）。

- [x] T4.1 `query-pipeline` delta：18 条 REMOVED 标题与现行 spec 逐字核对一致（archive 时整目录移除）。
- [x] T4.2 `query-rerank` delta：3 条 REMOVED 核对一致；`openspec/specs/INDEX.md` + `docs/INDEX.md` 摘除 query-rerank。
- [x] T4.3 `lightweight-query` delta：2 MODIFIED（query_nodes 去 skip_postprocess / select_facts_write 去读侧引用）+ 9 ADDED（locate_seeds/ENTRY/HubFallback/TrimPlugin/`_traverse`×3/frontier-accumulated/瘦身 QueryContext）正文完整。
- [x] T4.4 `mcs-builder` delta：「MCS 类瘦门面设计」与「show 方法」MODIFIED 完整正文（删 query API + Reader Pipeline mermaid 段）。
- [x] T4.5 `plugin-protocol` delta：3 接口 REMOVED + **修正 beta 漏洞**（原误把「MCSBuilder 抽象基类」MODIFIED 放此 capability——该 requirement 实属 mcs-builder；拆为正确标题的 2 MODIFIED：`PluginType 类型枚举` 删 3 值 + `PluginManager 支持新插件接口的注册与查找` 删 ArbitrationPlugin 单例检查）。
- [x] T4.6 `memory-agent` delta：2 MODIFIED（渲染纯函数 / associate 原语）核对，删 mcs 模式相关 scenario。
- [x] T4.7 `phase1-defaults` delta：默认清单 MODIFIED 完整正文（**SummaryPlugin 保留** + 删 2 默认空 scenario + Idempotency 标注）。`mcs-presets` **无 delta**。
- [x] T4.7b `preprocess-plugin` delta：**修正 beta 漏洞**（原 MODIFIED「废弃指向」标题在 preprocess-plugin live spec 不存在——废弃 requirement 归 plugin-protocol；本 delta 改为 REMOVED「查询管线阶段 ① 使用 PreprocessPlugin 类型」+ Purpose 收敛）；**代码侧** `mcs/interfaces/preprocess_plugin.py` DeprecationWarning 去 `QueryPreprocessPluginInterface`。
- [x] T4.8 `result-rendering` delta：「核心库提供共享结果渲染纯函数」MODIFIED 完整正文（删 render_query_result，留 format_ingest_status）。
- [x] T4.9 CLAUDE.md：「总体流程·查询 `query`」段改写为 agent 驱动 + 图底座原语；插件类型清单删 `ARBITRATION`/`POSTPROCESS`/`QUERY_PREPROCESS`；「四区硬比例仅框架查询路径」改为 `_traverse` 内部结构。
- [x] T4.10 docs：`api-reference.md`（删 query 行 + 读查询不经门面注）、`faq.md`（rerank→评测层 doc_rerank）、`docs/INDEX.md` + `openspec/specs/INDEX.md`（query-pipeline 条目摘除、lightweight-query/preprocess-plugin 描述更新）、`memory-agent.md`（LLMArbitrationPlugin 消歧）、`architecture.md`（PluginType 10 类 + postprocess 目录注）、`graph-model-design.md`（插件清单去重排 + query 图退役注）、`getting-started.md`（§4 查询改 agent + locate_seeds）、`plugin-system.md`（表删 3 行 + rerank 内置注）、`evaluation.md`（dir 树去 runner/__main__ + 命令改 agent_full_run）。
- [x] T4.10b diagrams：`query.mmd/.png` 删（退役流程）；`gmd-workzones`/`select-facts-dualrole-flow`（_traverse 内部机制，改 select_facts_write + accumulated、去后处理）；`plugin-chain`（读侧塌缩为 ENTRY+TRIM→locate_seeds）；`arch-system-overview`（门面去 query、QueryEngine→图原语、read_manager→ENTRY/TRIM）——4 图 .mmd 修正 + 文档内嵌 mermaid（mmdc 未装、.png 删）。
- [ ] T4.11 `CHANGELOG.md`：**Phase 6 archive 时追加**（条目绑定 archive 日期 + `archive/` 路径，见文件头「所有归档 change 的索引」）。

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
