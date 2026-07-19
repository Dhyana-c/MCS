# Design — retire-framework-query-pipeline

## 决策 D0：P1（删）而非 P2（搬到 agent 重实现）

用户的最初表述是"把 BFS 管线移动到 agent 部分实现"。经核查，BFS 在代码里是**三层捆在一起**，不是一个东西：

```
QueryEngine 今天 = 三层：

  (C) 读查询编排   query() = ①preprocess · ②locate_seeds · ③traverse · ④arbitrate · ⑤postprocess
        └─ 只服务"读查询"（+ agent 那个 mode="mcs" escape hatch）   ← 唯一能动的层

  (B) BFS 遍历原语  _traverse() / query_nodes()   [select_facts / select_facts_write]
        └─ 写管线 ingest 关联定位也走它（write_pipeline.py:181）       ← 搬不走，写管线依赖

  (A) 图导航 helper  locate_seeds · get_related_events · narrative_timeline · token_budget
        └─ agent 的 search/recall/timeline/arbitrate 全靠它            ← 搬不走，agent 底座
```

所以"搬 BFS 到 agent"严格讲只能搬 (C)。(B) 是写管线依赖、必须留框架；(A) 是 agent 自己的底座、更不能动。而 (C) 的唯一 agent 侧调用者是 `associate(mode="mcs")`——一个已被项目自身藏出 LLM enum、判定劣等的逃生口。

**把一个已被判定劣等、唯一调用者是隐藏逃生口的能力"搬家保留"，不如删掉。** agent 的 `search` + `associate(neighbors)` + `reason` **本身就是分步 BFS**，就是"agent 部分的实现"——不需要再把 (C) 搬过去。故选 P1：删 (C)，(A)+(B) 原地保留。

> 与用户确认过：agent 已定性更优，benchmark 基线不保留。

## 决策 D1：`QueryEngine` 类名保留，不改名

改名面 = **249 处 / 37 文件**（其中 ~20 是 tests、4 是 bench——本来都要改）。生产面就 8 个文件。但：

- 类瘦身后仍做"图查询/导航/遍历"（`locate_seeds` 是 query、`query_nodes` 是查询、`_traverse` 是图遍历）——名 `QueryEngine` 并非完全失实，失实的只是"5 段固定管线"这个**模块定位**。
- 项目规则第 6 条「最小改动」：249 引用的纯改名 churn 对一个已明确"删 (C)"的 change 是额外风险面，收益（语义更准）有限。
- **结论**：保留类名 `QueryEngine`；仅重写 `query_engine.py` 模块 docstring（从"5 阶段读取管道"改为"图导航 + 遍历原语，供写管线关联定位与 agent 导航复用；不再提供读查询编排"）。
- 若后续要改名（如 `NavigationEngine` / `GraphReads`），另起一个纯机械改名 change，与本 change 解耦。

## 决策 D2：插件归属表

| PluginType | 实现 | 谁调用 | 裁决 | 理由 |
|---|---|---|---|---|
| `ENTRY` | `HubFallbackEntryPlugin` / `AliasEntryPlugin` | `locate_seeds`（agent search + 写管线 query_nodes 经 `_locate_seeds`） | **留** | 写管线 + agent 共用 |
| `TRIM` | `PriorityTrimPlugin` / `SemanticTrimPlugin` | `locate_seeds` | **留** | 同上 |
| `ARBITRATION` | （空目录、无实现） | `_arbitrate`（仅 query/query_nodes 非 skip） | **删类型 + 接口 + 空目录** | 零实现、删 query() 即死 |
| `POSTPROCESS` | `RerankPlugin`（**唯一 Postprocess 子类**） | `_run_postprocess` / `_run_postprocess_nodes`（仅 query/query_nodes 非 skip） | **删类型 + 接口 + RerankPlugin** | **命名陷阱**：`SummaryPlugin` 同在 `mcs/plugins/postprocess/` 但是 `NodeExtensionInterface` 子类（`summary.py:20`、管 `extensions['summary']` 槽、`SummaryRegenPlugin` 再生）——**保留**，只删 `rerank.py`、留 `summary.py`、`__init__.py` 保留 SummaryPlugin import。`write_pipeline.py:7`"PostprocessPlugin chain"是过时笔误（实际走 WRITE_PREPROCESS） |
| `QUERY_PREPROCESS` | （零注册） | `_run_preprocess`（locate_seeds/query/query_nodes 都触达，但无实现=纯 no-op 透传） | **删类型 + 接口** | presets 零注册、删掉 no-op 循环即可 |
| `WRITE_PREPROCESS` | `IdempotencyCheckPlugin` 等 | 写管线 ① | **留** | 与本 change 无关 |
| `INDEX` / `LLM` / `NODE_EXTENSION` / `EDGE_EXTENSION` / `STORAGE_SCHEMA_EXT` / `COMPACTION` / `MAINTENANCE` | … | … | **留** | 与读查询管线无关 |

> 注意 `mcs/plugins/preprocess/` 目录名误导：里面的 `SourceTrackingPlugin` 是 `NODE_EXTENSION`+`STORAGE_SCHEMA_EXT`、`IdempotencyCheckPlugin` 是 `WRITE_PREPROCESS`——**都不是 QUERY_PREPROCESS**。删 QUERY_PREPROCESS 不影响这个目录。

## 决策 D3：bench 手术原则（遵循 framework-vs-bench-layer-separation）

记忆 `framework-vs-bench-layer-separation`：通用框架改进与评测层杠杆不混进同一 change。本 change 的 bench 改动是**"删被废弃 API 的死调用方"**（框架基线 runner 调的就是要删的 `mcs.query`），不是"评测层杠杆"（改进命中率/语料），故同 change 可接受。

**原则：仅删框架-BFS 基线轨，保留所有 agent 评测轨。** bench 文件分两类（grep 已核定）：
- **框架专属、整文件删**：`bench/multihop_rag/runner.py`（框架 runner）、`scripts/{diag_dualrole,diagnose_bfs_root,exp_rankfail_rerank}.py`（直调 `_traverse`/`mcs.query` 的诊断脚本）。
- **双模文件、手术删框架轨留 agent 轨**：`bench/multihop_rag/scripts/{agent_case_study,_common}.py`、`bench/locomo/scripts/agent_eval.py`（删检索轨 `mcs.query(question, universe=sample_id)`、留 agent 轨）、`bench/golden_cage/runner.py`（删 `mode=mcs` 轨、留 agent 轨）。
- `bench/agent_build.py`（顶层共享 agent 建图）**留**。

## 决策 D4：spec 手术策略（整体退役 + 存活原语下沉到 lightweight-query）

`query-pipeline` capability 的 Purpose 即"读流程 5 段固定管线"——删 (C) 后 capability **失去存在意义，整体退役**：**18 条 requirement 全部 REMOVED**（见 `specs/query-pipeline/spec.md` delta）。

存活原语**不在 query-pipeline 内"半删半留"**（那会留下无归属 requirement），而是**全部 ADDED 到 `lightweight-query`**（见 `specs/lightweight-query/spec.md` delta），其 Purpose 拓宽为"QueryEngine 图导航 + 遍历原语"。

> **为什么不放 `seed-selector-plugin`**：该 capability 已是 **REMOVED 状态**（接口早先移除、语义筛选并入 TrimPlugin），不可作为下沉目标。故种子定位存活 requirement 与遍历存活 requirement 一并收敛到 `lightweight-query`（query_nodes / locate_seeds / `_traverse` 本就是 QueryEngine 同一族方法）。

下沉映射（query-pipeline REMOVED → lightweight-query ADDED）：

| query-pipeline 原 requirement（REMOVED） | lightweight-query 新 requirement（ADDED） |
|---|---|
| 入口为字面 foothold + 反查 + 多种 | locate_seeds 入口为字面 foothold + 反查 + 多种 |
| 入口插件链累积合并并按优先级排序 | locate_seeds 经 ENTRY 插件链累积合并并按优先级排序 |
| 顶点导航兜底作为最低优先级入口插件 | HubFallbackEntryPlugin 作为最低优先级入口插件 |
| 种子裁剪使用 TrimPlugin 链 | 种子裁剪使用 TrimPlugin 链 |
| 语义理解 Loop 为 BFS 且维护 visited | `_traverse` 为 BFS 且维护 visited 集合 |
| 语义理解 Loop 的安全阀 | `_traverse` 的安全阀 |
| 语义理解 Loop 使用 select_facts 筛选候选 | `_traverse` 使用 select_facts_write 筛选候选（写路径口径） |
| frontier 与 accumulated 解耦 | frontier 与 accumulated 解耦 |
| QueryContext 含四个状态字段 | QueryContext 为导航/遍历的轻量上下文（**瘦身**：删 `intermediate`/`result_set`/`selected_edges`，留 `system_prompt`/`user_input`/`universe`/`metadata`） |

其余 9 条（5 段固定管线、①PreprocessPlugin、query 返回 Subgraph、多轮驻留、短边优先、entity-anchored、仲裁、后置链、select_facts 宽召回）为**纯读查询编排**，REMOVED 后不下沉（职责转移至 agent）。

`query-rerank` capability 同理**整体退役**（3 条 requirement 全 REMOVED，随 POSTPROCESS/RerankPlugin 删）。

## 决策 D5：分阶段执行（一个 change、内部 phase）

一个 change（避免 change 碎片化），tasks.md 内分 5 个 phase 顺序推进，每 phase 后 pytest + openspec validate 守门：
1. **核心删除**：删 `query()` / 5 阶段方法 / `MCS.query()` / `mode="mcs"` / loop.py 注释；`query_nodes` 瘦身；QueryContext 瘦身。
2. **插件清理**：删 ARBITRATION/POSTPROCESS/QUERY_PREPROCESS 类型+接口+实现+空目录。
3. **bench 删基线轨**（仅框架轨，保留 agent 轨）。
4. **spec + CLAUDE.md + docs** 改写（先于代码定型——宪法级）。
5. **tests + examples** 改写/删除。

## 已核定项（原"待核定"，grep 落定）

- **`Subgraph` 实体 → 留**：`sqlite_store.py` / `in_memory.py` 有图视图方法返回 `Subgraph(focus_id=...)`，不只是 query() 用。仅 query() 的使用随其删除，实体保留。
- **`QueryContext` → 留（瘦身）**：`EntryPlugin.locate` / `TrimPlugin.trim` 接口签名收 `ctx: QueryContext`（ENTRY/TRIM 留 → ctx 留）。删 `intermediate`/`result_set`/`selected_edges` 三字段（随 query() 退役），留 `system_prompt`/`user_input`/`universe`/`metadata`。
- **`select_facts`（读 prompt bundle）→ 删**：仅 query() 用；删 query() 即死。`select_facts_write` 留（query_nodes 用）。
- **`render_query_result` → 级联删**：唯一调用者是 `associate(mode="mcs")`（`memory.py:306`）；删 mode=mcs 后变死代码，连同 `result-rendering` spec 条目一并清理（`format_ingest_status` 留）。
- **`mcs_builder` 的 `show()` Reader Pipeline mermaid → 删**：描述的就是退役的 5 阶段。

## impl 期核定（不阻塞 proposal）

- **`bench/multihop_rag/scripts/agent_case_study.py`** 同时含 agent 与框架段——核定哪些行是基线、哪些是 agent 案例（文件级 grep 已知双模，行级边界 impl 定）。
- 各 MODIFIED delta 的完整 requirement 正文（`mcs-builder` show 方法、`result-rendering`、`phase1-defaults` 清单、`preprocess-plugin` 废弃指向）——proposal 阶段给出变更要点 + load-bearing scenario，完整正文 impl 期对照现行 spec 定稿。
- `README.md:198-204` multihop_rag eval 数字、`docs/api-reference.md:134-148` create_mcs 默认插件——核定是否仍引用 mcs.query / rerank（审计标 verify-manually）。
- `tests/conftest.py::make_query_engine` helper——在删 read-query 测试后 grep 其存活消费者，决定 keep/delete（审计标 conditional）。

## 交叉验证结论（workflow wy4usudjk，6 agent 全成）

5 审计 + 综合独立扫一遍后，与 proposal 逐条 diff。结论：

**确认 proposal 正确**（审计实证、行号对齐）：三层切分、write_pipeline 仅触 `query_nodes`（B 干净存活，永不到 ④⑤）、ENTRY/TRIM 留（`_locate_seeds` 被 query_nodes+locate_seeds 共用）、ARBITRATION 删（零实现、目录不存在）、mode=mcs 删、bench 手术边界（golden_cage:82 留/:106 删、agent_case_study:75 留/:99 删、locomo 检索轨删/QA 轨留）、Subgraph 留（store 用）、render_query_result 级联删、select_facts 读 bundle 删/write+SelectFactsResult+coerce 留、MCP 不受影响。

**已采纳的纠正**（本 proposal 据此 patch）：
1. **SummaryPlugin 命名陷阱**（我的真错误）——它是 `NodeExtensionInterface` 非 Postprocess，**保留**；只删 `rerank.py`。已修 D2 表 / proposal / phase1-defaults delta / tasks。
2. **`mcs/prompts/arbitrate.py` 漏删**——④ prompt bundle 零 caller，删；`adjudicate.py` 留、更 :8 注释。已加 proposal + tasks。
3. **QUERY_PREPROCESS 收紧**——`_run_preprocess` 方法**留**（locate_seeds 依赖），仅删 `PluginType.QUERY_PREPROCESS` + 接口 + 测试。已收紧 tasks T1.2。
4. **stale docstring 三处**（`config.py:22` / `trim_plugin.py:21` / `write_pipeline.py:7`）+ **`test_plugin_chains.py:16,159-197`** QUERY_PREPROCESS 测试连带删 + **5 个 diagrams `.mmd`** + `docs/getting-started.md`/`plugin-system.md`/`examples/README.md` + `preprocess-plugin:42`/`plugin-protocol:148` 废弃指向——已加 tasks。

**非分歧**：rename。综合产物建议 `NavigationEngine`，但其 `rename_plan` 明确"**land rename AFTER retire archives**（省 ~60 处 churn）"——与我 D1 延迟理由一致。故 retire change 仍保留 `QueryEngine` 名，rename 另起 change。

**审计自相矛盾处**（已裁定）：`doc_spec_updates` 写"move summary out of shared"与 `plugin_fate`"SummaryPlugin stays"冲突——以 `plugin_fate`（查了继承）为准，SummaryPlugin 留、mcs-presets 无 delta。已 grep `summary.py:20 class SummaryPlugin(NodeExtensionInterface)` 实证。
