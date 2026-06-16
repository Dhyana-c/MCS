## 1. 创建 entities 包并搬运实体

- [x] 1.1 创建 `mcs/entities/__init__.py`：汇总 re-export（`Node, Edge, Subgraph` 来自 graph；`ConceptDraft, Decision, DecisionList, Community, MultiHubDecision, ActionType` 来自 decisions；`MCSConfig, PHASE1_SHARED_PLUGINS, PHASE1_WRITE_PLUGINS, PHASE1_READ_PLUGINS, PHASE1_DEFAULT_PLUGINS` 来自 config）
- [x] 1.2 创建 `mcs/entities/graph.py`：从 `mcs/core/graph.py` 逐字搬入 `Node`/`Edge`/`Subgraph`；**移除**末尾 `from mcs.core.store import StoreInterface` re-export、`GraphStoreInterface = StoreInterface` 别名，及 `__all__` 中的 `StoreInterface`/`GraphStoreInterface`（使实体包不反向依赖 core.store）
- [x] 1.3 创建 `mcs/entities/decisions.py`：从 `mcs/core/decisions.py` 逐字搬入（`ConceptDraft`/`Decision`/`DecisionList`/`Community`/`MultiHubDecision`/`ActionType`）
- [x] 1.4 创建 `mcs/entities/config.py`：从 `mcs/core/config.py` 逐字搬入（`MCSConfig` + `PHASE1_*` 常量 + `_add_llm_config`）；保留 `MCSConfig.knowledge_graph` 内 `from mcs.prompts.judge_relations_attr import ...` 延迟 import 不变

## 2. 迁移 import 路径 — mcs 包内

- [x] 2.1 `mcs/core/`：`write_pipeline.py`（runtime decisions；TYPE_CHECKING config/graph）、`query_engine.py`（TYPE_CHECKING graph）、`context_renderer.py`（TYPE_CHECKING graph）、`token_budget.py`（TYPE_CHECKING graph）、`store.py`（TYPE_CHECKING graph，token_budget 行不动）、`plugin_manager.py`（TYPE_CHECKING config）、`builder.py`（TYPE_CHECKING config）
- [x] 2.2 `mcs/stores/`：`in_memory.py`、`sqlite_store.py`（graph）
- [x] 2.3 `mcs/plugins/`：`trim/priority_trim.py`、`seed_selector/llm_seed_selector.py`、`preprocess/source_tracking.py`、`preprocess/cross_doc_linker.py`、`postprocess/summary.py`、`postprocess/rerank.py`、`index/alias_index.py`、`index/community_merger.py`、`entry/hub_fallback.py`、`maintenance/fanout_reducer.py`（保留 `import Node as GraphNode` 别名、仅改路径）、`maintenance/summary_regen.py`
- [x] 2.4 `mcs/prompts/`：`judge_relations.py`、`judge_relations_attr.py`、`extract_concepts.py`、`decide_hub.py`
- [x] 2.5 `mcs/interfaces/`：`compaction_plugin.py`、`seed_selector_plugin.py`、`trim_plugin.py`、`llm.py`、`index.py`、`node_extension.py`、`arbitration_plugin.py`、`entry_plugin.py`（graph 类型标注）
- [x] 2.6 `mcs/diagnostics/graph_quality.py`、`mcs/presets/phase1.py`
- [x] 2.7 `mcs/__init__.py`：`from mcs.core.config import MCSConfig` → `from mcs.entities.config import MCSConfig`

## 3. 删除旧模块与更新 core 入口

- [x] 3.1 删除 `mcs/core/graph.py`
- [x] 3.2 删除 `mcs/core/decisions.py`
- [x] 3.3 删除 `mcs/core/config.py`
- [x] 3.4 更新 `mcs/core/__init__.py` docstring：模块清单移除 graph/decisions/config 三项，注明已迁至 `mcs.entities`

## 4. 更新外部引用与文档

- [x] 4.1 `tests/test_skeleton.py`（**结构性修改，非简单 import 替换**）：`ALL_MODULES` 列表删除 `mcs.core.config`/`mcs.core.decisions`/`mcs.core.graph` 三项，新增 `mcs.entities`/`mcs.entities.graph`/`mcs.entities.decisions`/`mcs.entities.config` 四项；`test_source_lives_in_plugin_not_core` 把 `import mcs.core.graph as core_graph` 与断言字符串 `mcs.core.graph` 改为 `mcs.entities.graph`；函数体内其余 import（Node/Decision/MCSConfig）改 entities 路径；模块 docstring L7-8 同步
- [x] 4.2 其余 `tests/` 文件 import 路径替换（conftest、test_pipeline_write、test_pipeline_query、test_persistence、test_seed_graph、test_rerank、test_token_budget、test_attribute_node_model、test_decision_apply、test_community_merger、test_fanout_reducer、test_context_renderer、test_graph_quality、test_anti_regression、test_directed_hierarchy、test_directed_navigation、test_graph_direction、test_mcs_api、test_plugin_chains、test_cross_doc_linker、test_hub_fallback、test_dual_edge、test_bench_doc_rerank、test_ollama_llm 等）
- [x] 4.3 `examples/basic_usage.py`、`examples/wiki_example.py`
- [x] 4.4 `bench/plugins/doc_rerank.py`、`bench/multihop_rag/scripts/_common.py`
- [x] 4.5 `README.md` 示例 import（`from mcs.core.config import MCSConfig`）
- [x] 4.6 `docs/architecture.md` §8 目录树：从 `core/` 子树移除 `config.py`/`graph.py` 两行；新增 `entities/` 子树（含 `graph.py`/`decisions.py`/`config.py` 及注释）；其余过时行（storage.py、plugins/base.py 等）本次不动

## 5. 验证

- [x] 5.1 `.venv\Scripts\python.exe -m pytest -q` 全绿
- [x] 5.2 `ruff check .` 零错（`I` 规则验证 import 正确性）
- [x] 5.3 `python -c "import mcs"` 成功
- [x] 5.4 `python -c "from mcs.core.graph import Node"` 抛 `ModuleNotFoundError`（旧路径已删、无兼容层）
- [x] 5.5 `python -c "from mcs.entities import Node, Edge, Subgraph, MCSConfig"` 成功（顶层汇总 re-export）
