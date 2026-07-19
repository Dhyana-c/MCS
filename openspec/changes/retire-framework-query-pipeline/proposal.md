## Why

框架的读查询管线（`QueryEngine.query()` 5 阶段：前置 → 种子定位 → 语义 BFS → 仲裁 → 后处理）已被记忆 agent 取代。multihop RAG / LoCoMo / golden_cage 三套实测均证明 agent 的分步游走（`search` + `associate` + `reason`）在命中率与成本上优于框架的一次性 BFS（见 `framework-to-agent-handoff` 决策）。该管线在代码里的最后栖息地只剩 benchmark 基线对照与一个被刻意藏出 LLM enum 的 `associate(mode="mcs")` 逃生口——项目自身已判定它劣等、不应被选用（`mcs_agent/tools.py:200` 注释）。

继续保留它有三重成本：
- **维护负担**：`query_engine.py` 864 行中约一半是 5 阶段编排 + 仅服务读查询的 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS` 插件类型与实现（其中 `ARBITRATION` 目录全空、`QUERY_PREPROCESS` presets 零注册纯 no-op）。
- **认知负担**：CLAUDE.md「总体流程」与 `query-pipeline` spec 仍把 5 阶段描述为框架活能力，与"查询由 agent 驱动"的现实矛盾；`mcs_agent/loop.py:61` 的 system prompt 甚至仍称 `mode=mcs` 为"主力"——已过时且误导。
- **架构模糊**："框架有查询管线"与"agent 负责查询"两套心智模型并存。

本 change 把读查询的职责**正式、干净地归 agent 独占**：删除框架的 5 阶段编排及其独占插件链与 benchmark 基线，**保留**被写管线 ingest（`query_nodes` / `_traverse` / `select_facts_write`）与 agent 导航原语（`locate_seeds` / `get_related_events` / `narrative_timeline` / `token_budget`）依赖的图遍历底座。

> 注：BFS 遍历原语（`_traverse`）**不是**纯读侧能力——写管线 ingest 的关联定位也走它（`write_pipeline.py:181` → `query_nodes` → `_traverse(select_facts_write)`）。故本 change 删的是"读查询编排"（C 层），不是"遍历原语"（B 层）。详见 `design.md`「三层切分」。

## What Changes

### 删除（框架不再拥有读查询管线）

- `QueryEngine.query()` 整体移除；`query_nodes()` 收缩为**写管线内部专用**（`skip_postprocess=True` 固化、删除 ④⑤ 分支与 `_run_postprocess_nodes`）。
- 5 阶段编排方法：`_run_preprocess` 的 `QUERY_PREPROCESS` 分支、`_arbitrate`、`_run_postprocess`。
- `MCS.query()` 公共 API（`Subgraph` 实体**保留**——`sqlite_store` / `in_memory` 的图视图方法仍返回它，非 query 专属）。
- `mcs/rendering.py::render_query_result`（**级联删除**：唯一调用者是 `associate(mode="mcs")`，删 mode 后变死代码；`format_ingest_status` 留）。
- `mcs_agent/memory.py` 的 `associate(mode="mcs")` 逃生口（唯一 agent 侧对 `mcs.query` 的调用，`memory.py:301-306`）+ `mcs_agent/loop.py:61` 过时 system prompt。
- 读侧独占插件类型 + 接口 + 实现：
  - `PluginType.ARBITRATION` + `ArbitrationPluginInterface`（`mcs/plugins/arbitration/` 空目录）。
  - `PluginType.POSTPROCESS` + `PostprocessPluginInterface` + `RerankPlugin`（仅被 query ⑤ 调用）。**命名陷阱**：`SummaryPlugin` 虽位于 `mcs/plugins/postprocess/` 但实为 `NodeExtensionInterface` 子类（管 `extensions['summary']`、由 `SummaryRegenPlugin` 再生）——**保留**，只删 `rerank.py`、留 `summary.py`、`__init__.py` 保留 SummaryPlugin import。
  - `PluginType.QUERY_PREPROCESS` + `QueryPreprocessPluginInterface`（presets 零注册、纯 no-op 透传）。
- `mcs/prompts/arbitrate.py`（④ `arbitrate` purpose prompt bundle，零 caller；`mcs/prompts/adjudicate.py` **留**——agent `arbitrate` 工具用，仅更 :8 消歧注释）。
- benchmark **框架-BFS 基线轨**（仅删基线、保留 agent 评测轨——见 `design.md`「bench 手术原则」）：
  - `bench/multihop_rag/runner.py`（框架 runner）+ `scripts/{diag_dualrole,diagnose_bfs_root,exp_rankfail_rerank}.py`（直调 `_traverse`/`mcs.query` 的诊断脚本）。
  - `bench/locomo/scripts/agent_eval.py` 检索轨（`mcs.query(question, universe=sample_id)`）。
  - `bench/golden_cage/runner.py` 的 `mode=mcs` 轨。
- `examples/*.py` 的 `mcs.query()` 示例、`mcs/__init__.py` docstring 示例、`mcs/core/mcs.py::MCS.show()` 的 "Reader Pipeline" mermaid 段。

### 保留（写管线 + agent 共用的图底座，`QueryEngine` 类瘦身后仍在）

- `locate_seeds()`（ENTRY + TRIM 插件链）—— agent `search` + 写管线 `query_nodes` 经 `_locate_seeds` 依赖。
- `_traverse()` / `query_nodes()` / `select_facts_write` prompt —— 写管线 ingest 关联定位依赖。
- `get_related_events()` / `narrative_timeline()` / `token_budget` —— agent `recall` / `timeline` / `arbitrate` / `generalize` 依赖。
- ENTRY / TRIM 插件类型与实现（`HubFallbackEntryPlugin` / `PriorityTrimPlugin` / `SemanticTrimPlugin`）—— locate_seeds 共用。

### Spec / 宪法同步（先改 spec / CLAUDE.md 再改代码——项目规则第 4 条）

- `query-pipeline` capability **整体退役**（18 条 requirement 全 REMOVED）；存活原语 ADDED 到 `lightweight-query`（`seed-selector-plugin` 已是 REMOVED 状态、不可收纳——见 design D4）。
- `query-rerank` capability 退役（3 条 requirement 全 REMOVED，rerank 插件随 `POSTPROCESS` 删除）。
- CLAUDE.md「总体流程·查询 `query`」段改写为"查询由 agent 驱动；框架仅提供图底座原语"；插件类型清单移除 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS`；「四区硬比例仅框架查询路径」条更新。
- 已建 10 份 delta：`query-pipeline`（全删 18）/ `lightweight-query`（收纳存活）/ `query-rerank`（全删）/ `plugin-protocol`（删 3 接口 + Preprocess 废弃指向去 QueryPreprocess）/ `mcs-builder`（删 query API + show Reader 段）/ `memory-agent`（删 associate mcs 模式 + render_query_result 复用）/ `result-rendering`（删 render_query_result）/ `phase1-defaults`（SummaryPlugin 保留 + 删 2 默认空 scenario + Idempotency 标注）/ `preprocess-plugin`（废弃指向去 QueryPreprocess）/ `bench-utils`（MODIFIED：.env 加载去 runner 场景 + 功能替代改指 `agent_full_run.py`——框架 runner 退役的 LIVE spec 唯一引用处）。`mcs-presets` **无 delta**（SummaryPlugin 是 NodeExtension、保留，shared 清单不变）。
- `docs/api-reference.md`（删 `query` 条）、`docs/faq.md`、`docs/INDEX.md`、`openspec/specs/INDEX.md` 同步。

## Capabilities

### Removed Capabilities
- `query-pipeline`：5 段固定读管线整体退役（存活原语下沉到 lightweight-query 等既有 capability，不在本 change 新建 spec）。
- `query-rerank`：读查询重排插件随 `POSTPROCESS` 类型删除。

### Modified Capabilities
- `lightweight-query`：`query_nodes` 重新定位为"写管线 ingest 关联定位内部原语"，不再作为"轻量读查询"对外；保留 ②③（种子定位→限深遍历），删 ① 前置（`QUERY_PREPROCESS`）；同时收纳 query-pipeline 退役后存活的 9 条导航/遍历原语 requirement（见 design D4 下沉映射）。
- `mcs-builder`：移除 `MCS.query()` / `QueryEngine.query()` API 契约；`MCS` 双管线瘦身为"写管线 + 图原语只读入口"。
- `plugin-protocol`：移除 `ArbitrationPluginInterface` / `PostprocessPluginInterface` / `QueryPreprocessPluginInterface` 三个读侧接口与对应 `PluginType` 枚举值。
- `memory-agent`：`associate` 工具删除 `mcs` 模式（仅留 `neighbors`）；spec 中"`mcs` 模式"相关条目随模式删除。
- `phase1-defaults`：默认清单中 `SummaryPlugin` 实为 NodeExtension（**保留**，非 Postprocess）；删 2 个默认空 scenario（Arbitration/Postprocess）；`IdempotencyCheckPlugin` 标注校正为 WRITE_PREPROCESS。
- `preprocess-plugin`：废弃 `PreprocessPluginInterface` 的迁移指向去掉 `QueryPreprocess`。
- `result-rendering`：`render_query_result` REMOVED（级联自 mode="mcs" 删除），`format_ingest_status` 留。

## Impact

- **受益**：架构清晰（查询职责单一归 agent）、减负（删 ~400+ 行 5 阶段代码 + 3 个死/空插件类型 + 过时文档/spec）、消除 `loop.py:61` 等过时口径与现实的矛盾。
- **风险**：
  - bench 框架基线轨删除后失去"框架 vs agent"对照复现能力（用户已认定 agent 定性更优、明确接受此代价）。
  - `query-pipeline` spec 18 条 requirement 的存活/退役判定需逐条核对（见 `design.md`「spec 手术表」）。
  - `QueryEngine` 类名保留但语义已变（仅图底座，非查询管线）——文档需讲清，避免后续读代码者误解。
- **不受影响**：写管线 ingest（`learn`）、agent 全部 12 工具的正常路径、MCP server（已全量委托 agent、不 import `mcs.query`，`mcs_mcp/server.py:8` 注释为证）、图存储与核心不变量。
- **验证**：`.venv\Scripts\python.exe -m pytest -q` 全绿（删一批 query 管线测试、改写 `query_nodes` / `locate_seeds` 相关测试为"写管线内部原语"口径）；`openspec validate retire-framework-query-pipeline` 通过；CLAUDE.md 与 spec 自洽。
