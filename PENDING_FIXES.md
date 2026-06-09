# 待修复清单（MultiHop-RAG 评测跑完后一起处理）

> 本清单汇总本轮评测过程中发现、但**暂缓修复**的问题。当前 200 篇 build 正在跑，先不动。

## 🔴 0. 大图诊断（最高优先级，根因已定位）

> ✅ 本节 reranker 与序列化修复已由 change `query-rerank-and-persistence` 完成（见各项 ✅）；
> 图连通性/碎片化（下方第 3 项）经 POC 证实**非本检索指标根因**，已转入研究型 change
> `openspec/changes/graph-construction-quality/`。

- [x] **【首要修复 · 已离线验证】query 输出 reranker 插件**：query() 返回**无序宽集**（gold 文档中位 rank 36 / 共 ~165 篇）。零成本离线词法重排 POC（同一候选集）：recall@10 **0.14→0.81**、@4 0.03→0.68、@2 0.01→0.52；inference 类从**全 0 → 0.88@10**。证明 gold 一直在候选集里、纯粹是排名问题。
  - 方案：新增 `query_postprocess` 插件（`PostprocessPluginInterface`，`position="query_postprocess"`），用 `ctx.user_input`（查询）给 `List[Node]` 打分→过滤→排序。打分器可插拔：词法（零成本）→ 嵌入 / LLM（更强语义多跳）。**性价比最高的修复，建议先做。**
  - 涉及：新增 `mcs/plugins/.../rerank.py`，无需改 core。
- [x] **source_tracking 序列化 bug**：`sqlite_storage.save_node` 用 `json.dumps(extensions, default=str)` 把 `Source` 存成**字符串**而非 dict（没走 `serialize()`），`load()` 也不 `deserialize`。后果：**reload 后检索全空**；本次只因 build+query 同进程才正常。**也是 reranker 廉价迭代的前置**——修好才能 reload 已建图、不必每次 ¥11 重建。
  - 涉及：`mcs/plugins/phase1/sqlite_storage.py:save_node/load`
- [x] **图连通性/碎片化（降为次要 · 已由 research change `graph-construction-quality` 收口）**：原始诊断 4380 节点 / 2901 边 / 度 1.32、34% 孤立、1681 分量、跨文档边仅 634。⚠️ 修正之前判断：**这不是本指标的根因**——POC 已证 gold 仍进候选集（召回 86%），连通性只是让候选网偏宽，可能影响最难多跳与那 14% 漏召。属次优先。
  - **结论（2026-06-05）**：经 `seed_graph_bounding`+`fanout_reducer` 后，现网图（`multihop_chat_200_v2.db`）已是**单连通分量 / 0 孤立 / 度 5.23**，原始碎片化问题已不复现；剩余空间在**跨文档连通性**（跨文档边 15.6%）。
  - **图质量诊断**：已落地 `mcs/diagnostics/graph_quality.py`（+ `scripts/diagnose_graph.py`、`tests/test_graph_quality.py`），作为可复现回归基线。
  - **跨文档链接**：已实装 `mcs/plugins/phase1/cross_doc_linker.py`（name/alias 匹配，零 LLM 成本）+ `scripts/cross_doc_link_pass.py`，可**落盘**；实测跨文档边 1555→1987（+27.8%）。作为 build 后可选步骤，未入默认管线。
  - **CommunityMerger 已实现**：`mcs/plugins/phase1/community_merger.py`（CompactionPlugin，聚类系数启发式 + LLM 造枢纽），已在插件注册表登记、可经 config 启用，但**默认关闭**（大规模 A/B 待评估需要时再开）。
  - 边无向无类型（phase-1 设计如此，非 bug）：经评估**成本/收益不划算**，建议拆为后续独立 change，不在本轮做。

## A. MCS core —— 持久化 / 健壮性

- [x] **持久化提交时序**：`document_chunks`（续跑标记）在管线①就 commit，而节点在管线⑦ `save_node` 且**自己不 commit**（靠下一块顺带刷）。后果：① 最后一块在 shutdown 时丢失；② 硬崩溃+续跑时某块可能被标记"已完成"但节点没落盘 → 图出现空洞。
  - 最小修：`build_shared_graph` 每篇 ingest 后显式 `commit()`；更彻底：`write_pipeline._run_persist` 自带 commit。
  - 涉及：`mcs/core/write_pipeline.py:_run_persist`、`mcs/plugins/phase1/sqlite_storage.py:save_node/save_edge`
- [x] **idempotency 过早标记**：`IdempotencyCheckPlugin` 在 preprocess 就记 `document_chunks`，导致中途出错的块也被标记完成、续跑不再重试。改成**成功后才标记**。
  - 涉及：`mcs/plugins/phase1/source_tracking.py:IdempotencyCheckPlugin`
- [ ] **LLM 瞬时错误处理**：429 / 网络抖动目前直接吞成空结果（计为 miss）。加**重试 + 退避**（并发时尤其必要）。
- [x] **navigate_hub 解析对 LLM 不规整输出的容错**（2026-06-01 重排评测中发现并修复）：`navigate_hub.parse` 原先 `json.loads` 一失败就 `raise LLMParseError`，经 `hub_fallback` 抛出后**拖垮整条 query**（计 miss）。不规整形态包括 max_tokens 截断的未闭合数组、`JSON:` 前缀污染、对象数组 `[{"id":..}]`、对象包裹 `{"ids":[..]}`。
  - 已修：`parse` 改为**宽容解析**——去前缀 + 兼容上述各形态抽 id；截断则抢救已闭合串；实在解析不出返回 `[]`（优雅降级、**绝不抛异常**），下游 `get_node` 过滤无效 id。
  - 涉及：`mcs/prompts/navigate_hub.py:parse`（+ `tests/test_prompt_parse_lenient.py`）
- [x] **reload 后索引未重建**（2026-06-01 重排评测中发现并修复，比 source 序列化更隐蔽）：`MCS.initialize` 先 `initialize_all`（`AliasIndexPlugin` 在**空图**上 build 索引）→ 再 `_try_load_from_storage`（才加载节点），导致 reload 后倒排索引一直为空 → `alias_entry` 全失效 → 候选集召回从 86% 崩到 7%、检索指标全面崩塌。**这让"reload 复用图再 query"实际是坏的。**
  - 已修：`_try_load_from_storage` 加载完节点/边后重建所有 `IndexInterface` 索引。验证：reload 后 alias 索引 0→10489、候选召回 7%→86%、recall@10 0.064→0.226。
  - 涉及：`mcs/__init__.py:_try_load_from_storage`（+ `tests/test_pipeline_write.py`）
- [ ] **`_locate_seeds` 单 entry 插件容错（防御性，残留）**：目前任一 EntryPlugin 的 `locate` 抛异常会拖垮整个种子定位。navigate_hub 宽容后已大幅缓解，但仍建议 `_locate_seeds` 对单插件异常 try/except 降级。
  - 涉及：`mcs/core/query_engine.py:_locate_seeds`

## B. Bench 质量

- [x] **multihop `--exclude-null` 选项**：小 corpus 子集下 null_query（恒 301）占绝大多数，干扰信号；加开关可只评非 null。

## C. 评测基础设施 / 性能

- [ ] **query 阶段并发**：query 是只读、彼此独立 → `ThreadPoolExecutor` 加速，配合上面的重试/退避。build 是写共享图、必须串行，无法并发。
- [x] **（战略改进）检索"召回好但精确率差"**（reranker 已实装；量化见本 change 的 6.2，待付费重跑）：实测 MCS 段落召回 90%、但撒网过宽（query 结果未排序/剪枝）。给 `query()` 结果加**排序 + 剪枝**——这正是 MultiHop-RAG 的 MAP/MRR 会量化的核心改进方向。
  - 涉及：`mcs/core/query_engine.py`

## D. 收尾

- [ ] 归档完成的 change：`multihop-rag-eval`（`openspec archive ...`）。
- [ ] 清理临时脚本：`_smoke_test.py`、`_run_eval.py`、`_measure_tokens.py` 及根目录 `*.log`、`_measure_tokens`/`bench_output*` 等评测产物。

---

## 备查：本轮**已修**（无需再处理）

- 决策清洗（attach_statement/merge 无 target_id 不再崩）、parser 容忍单对象、deepseek `max_tokens=8192`、bench 分段容错、UTF-8 安全 stdout、预测/检索结果增量落盘
