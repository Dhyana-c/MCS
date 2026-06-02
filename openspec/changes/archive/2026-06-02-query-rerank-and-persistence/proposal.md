## Why

MultiHop-RAG 评测把 MCS 的检索瓶颈精确定位到了**排名**，而非召回或建图：`query()` 返回一坨无序宽集（gold 文档中位 rank 36 / 共 ~165 篇），但零成本离线词法重排 POC（同一候选集）把 recall@10 从 **0.14→0.81**、@4 从 0.03→0.68，inference 类从全 0→0.88@10。同时评测暴露了几个真持久化 bug——`source_tracking` 落盘成字符串、提交时序滞后、idempotency 过早标记——导致"图落盘后复用 / 续跑 query"实际是坏的。这批修复确定性高、ROI 高，值得一次做对。

## What Changes

- 新增 `query_postprocess` **reranker 插件**：用 `ctx.user_input` 给 `query()` 返回的 `List[Node]` 打相关性分 → 过滤 → 排序 → 截断 top-N。打分器**可插拔**（先词法 baseline，预留嵌入/LLM）。默认 **opt-in**，无需改 core。
- **修 `source_tracking` 序列化 round-trip**：`save_node`/`load` 改走 NodeExtension 插件的 `serialize()/deserialize()`，使持久化的 `Source` 是 dict 而非 `default=str` 字符串；reload 后 `retrieved_docs` 能正常取 `doc_id`。
- **修持久化提交时序**：`write_pipeline._run_persist` 保存节点/边后自己 `commit()`，不再滞后一块、不再在 shutdown 丢最后一块。
- **idempotency 改 mark-on-success**：`IdempotencyCheckPlugin` 改为成功后才记 `document_chunks`，避免出错的块被标记完成、续跑留空洞。
- **bench 质量（顺带收口）**：hotpot `extract_supporting_facts` top-N 剪枝；hotpot `dry_run` 换实测 token 模型；multihop 加 `--exclude-null`。

## Capabilities

### New Capabilities
- `query-rerank`: 查询输出的相关性重排/过滤——postprocess 插件对 `query()` 结果按查询相关性打分、过滤、排序、截断，打分器可插拔

### Modified Capabilities
- `auto-persistence`: 持久化必须**保真 round-trip**（load 重建的扩展数据可直接使用，而非字符串化）、提交**及时可靠**（每次 ingest 落定、不丢最后一块）、续跑**无空洞**（idempotency 标记与节点落盘一致）

## Impact

- 新增一个 postprocess 插件（注册进 plugin registry；默认 opt-in，不动既有默认链行为）
- 改 `mcs/plugins/phase1/sqlite_storage.py`（序列化）、`mcs/core/write_pipeline.py`（`_run_persist` commit）、`mcs/plugins/phase1/source_tracking.py`（idempotency 时机）
- 改 `mcs/bench/hotpot.py`、`mcs/bench/multihop_rag.py`（质量项，不改 core spec）
- **验证近乎零成本**：修完序列化后 reload 现有 `multihop_bench.db`（已建好的那张图）+ 启用 reranker 重跑 query，直接对比 Hit@k/MAP/MRR，**无需重新建图**
- 不改 LLM 调用次数（reranker 词法 baseline 零额外调用；嵌入/LLM 打分器为后续增强）