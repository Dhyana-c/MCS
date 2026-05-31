# 待修复清单（MultiHop-RAG 评测跑完后一起处理）

> 本清单汇总本轮评测过程中发现、但**暂缓修复**的问题。当前 200 篇 build 正在跑，先不动。

## 🔴 0. 大图诊断（最高优先级，根因已定位）

- [ ] **【首要修复 · 已离线验证】query 输出 reranker 插件**：query() 返回**无序宽集**（gold 文档中位 rank 36 / 共 ~165 篇）。零成本离线词法重排 POC（同一候选集）：recall@10 **0.14→0.81**、@4 0.03→0.68、@2 0.01→0.52；inference 类从**全 0 → 0.88@10**。证明 gold 一直在候选集里、纯粹是排名问题。
  - 方案：新增 `query_postprocess` 插件（`PostprocessPluginInterface`，`position="query_postprocess"`），用 `ctx.user_input`（查询）给 `List[Node]` 打分→过滤→排序。打分器可插拔：词法（零成本）→ 嵌入 / LLM（更强语义多跳）。**性价比最高的修复，建议先做。**
  - 涉及：新增 `mcs/plugins/.../rerank.py`，无需改 core。
- [ ] **source_tracking 序列化 bug**：`sqlite_storage.save_node` 用 `json.dumps(extensions, default=str)` 把 `Source` 存成**字符串**而非 dict（没走 `serialize()`），`load()` 也不 `deserialize`。后果：**reload 后检索全空**；本次只因 build+query 同进程才正常。**也是 reranker 廉价迭代的前置**——修好才能 reload 已建图、不必每次 ¥11 重建。
  - 涉及：`mcs/plugins/phase1/sqlite_storage.py:save_node/load`
- [ ] **图连通性/碎片化（降为次要）**：4380 节点 / 2901 边 / 度 1.32、34% 孤立、1681 分量、跨文档边仅 634。⚠️ 修正之前判断：**这不是本指标的根因**——POC 已证 gold 仍进候选集（召回 86%），连通性只是让候选网偏宽，可能影响最难多跳与那 14% 漏召。属次优先。
  - 边无向无类型（phase-1 设计如此，非 bug）：图模型偏薄，长远可考虑有向/带类型边以支撑更深多跳。
  - **CommunityMerger 设计了未实现**：`MCS技术方案.md` 与 `compaction_plugin.py` 注释把"社区合并（合并稠密区域）"列为 CompactionPlugin 之一，但 phase-1 只实装了 `fanout_reducer`+`summary_regen`，**无社区检测算法、无 community_merger 插件**。缺这一层高阶结构 → 图停在"每块抽概念 + 无向边"的原始态，34% 孤立 / 1681 碎片无人消化。属中长期图质量改进，**非本检索指标根因**。

## A. MCS core —— 持久化 / 健壮性

- [ ] **持久化提交时序**：`document_chunks`（续跑标记）在管线①就 commit，而节点在管线⑦ `save_node` 且**自己不 commit**（靠下一块顺带刷）。后果：① 最后一块在 shutdown 时丢失；② 硬崩溃+续跑时某块可能被标记"已完成"但节点没落盘 → 图出现空洞。
  - 最小修：`build_shared_graph` 每篇 ingest 后显式 `commit()`；更彻底：`write_pipeline._run_persist` 自带 commit。
  - 涉及：`mcs/core/write_pipeline.py:_run_persist`、`mcs/plugins/phase1/sqlite_storage.py:save_node/save_edge`
- [ ] **idempotency 过早标记**：`IdempotencyCheckPlugin` 在 preprocess 就记 `document_chunks`，导致中途出错的块也被标记完成、续跑不再重试。改成**成功后才标记**。
  - 涉及：`mcs/plugins/phase1/source_tracking.py:IdempotencyCheckPlugin`
- [ ] **LLM 瞬时错误处理**：429 / 网络抖动目前直接吞成空结果（计为 miss）。加**重试 + 退避**（并发时尤其必要）。

## B. Bench 质量

- [ ] **hotpot sp 过度预测**：`extract_supporting_facts` 把所有来源 title 全吐出（平均 7.5 个，gold 仅 2）→ 按 node rank 取 **top-N 剪枝**，提升 sp_em / 精确率。
  - 涉及：`mcs/bench/hotpot.py:extract_supporting_facts`
- [ ] **hotpot dry_run token 模型过时**：仍用 7900/条（实测 ~90K/条）→ 更新为实测模型（multihop 已用实测模型，可参照）。
  - 涉及：`mcs/bench/hotpot.py:dry_run`
- [ ] **multihop `--exclude-null` 选项**：小 corpus 子集下 null_query（恒 301）占绝大多数，干扰信号；加开关可只评非 null。

## C. 评测基础设施 / 性能

- [ ] **query 阶段并发**：query 是只读、彼此独立 → `ThreadPoolExecutor` 加速（multihop 与 hotpot 都适用），配合上面的重试/退避。build 是写共享图、必须串行，无法并发。
- [ ] **（战略改进）检索"召回好但精确率差"**：实测 MCS 段落召回 90%、但撒网过宽（query 结果未排序/剪枝）。给 `query()` 结果加**排序 + 剪枝**——这正是 MultiHop-RAG 的 MAP/MRR 会量化的核心改进方向。
  - 涉及：`mcs/core/query_engine.py`

## D. 收尾

- [ ] 归档两个完成的 change：`hotpot-eval-benchmark`、`multihop-rag-eval`（`openspec archive ...`）。
- [ ] 清理临时脚本：`_smoke_test.py`、`_run_eval.py`、`_measure_tokens.py` 及根目录 `*.log`、`_measure_tokens`/`bench_output*` 等评测产物。

---

## 备查：本轮**已修**（无需再处理）

- 决策清洗（attach_statement/merge 无 target_id 不再崩）、parser 容忍单对象、deepseek `max_tokens=8192`、bench 分段容错、UTF-8 安全 stdout、预测/检索结果增量落盘
- hotpot 官方指标聚合修正（12 键 + 正确 joint）、sp int 下标对齐、yes/no 门控
