# Changelog

> 所有归档 change 的按时间倒序索引。每个条目链接到对应的 `openspec/changes/archive/` 目录。

## 2026-07-19

- **[retire-framework-query-pipeline](openspec/changes/archive/2026-07-19-retire-framework-query-pipeline/)** — 退役框架读查询固定管线（`QueryEngine.query()` / `MCS.query()` 的 5 阶段编排）；读查询改由记忆 agent 驱动（`mcs_agent` 的 search/associate/reason/generalize/arbitrate/timeline 分步游走图底座——agent 的分步探索本身就是 BFS，无需再搬一套固定管线）。框架保留**图导航 + 遍历原语**（`locate_seeds` / `_traverse` / `query_nodes` / `get_related_events` / `narrative_timeline`）供 agent 与写管线复用。删 `PluginType.ARBITRATION`/`POSTPROCESS`/`QUERY_PREPROCESS` + 3 接口 + `RerankPlugin` + `render_query_result` + `associate(mode="mcs")`；bench 框架基线轨（runner/eval/query/test/3 诊断）删、agent 评测轨留。10 份 spec delta（8 走 archive apply + query-pipeline/query-rerank 整目录删——全退役无存活 requirement，`openspec archive` 不支持空 spec 故手动删）。顺带修 2 个 beta 漏洞（plugin-protocol/preprocess-plugin delta 标题错配）+ Phase 2 landmine（builder `rerank=True` 注册已删插件）。1084 测试绿。
- **[mcs-mem-extract-and-publish](openspec/changes/archive/2026-07-19-mcs-mem-extract-and-publish/)** — 发布底层 `mcs-core==0.1.0` 到 PyPI（分发名 `mcs-core`、import 名 `mcs`/`mcs_agent`/`mcs_mcp` 不变、entry `mcs-mcp`/`mcs-agent`）；拆 `mcs_mem` 到独立 repo [mcs-mem](https://github.com/Dhyana-c/mcs-mem)（private）+ 7 测试 + demo + 5 mem spec + `docs/memory-agent.md` mcs_mem 节 + 2 mcs_mem 图随迁；原仓清理 `mcs_mem/` + 7 测试 + demo + 5 spec + 2 图。TestPyPI 跳过（本地全验证覆盖；用户执行时决策）。

## 2026-06-25

- **[model-aware-token-estimation](openspec/changes/archive/2026-06-25-model-aware-token-estimation/)** — 模型感知 token 估算：`LLMInterface` 新增 `count_tokens` / `context_window_size`；DeepSeek/Ollama 用 tiktoken 本地精确计数（Ollama 走 ollama 族系数），Claude 运行时用 claude 族校准式（不调 API，避免 O(邻域) 网络调用与 429 降级破坏口径一致性，API 仅离线校准）；`TokenBudget` counter 改由 write_llm 注入、兜底统一为 `CalibratedEstimator("unknown")` ×1.7；`knowledge_graph()` 按上下文窗口自动算 T（保守上限 8000）。待跟进：7.4 校准系数实测验证

## 2026-06-24

- **[reposition-general-memory-engine](openspec/changes/archive/2026-06-24-reposition-general-memory-engine/)** — 重定位为通用记忆引擎：文档去除「核心赌注 / 局部性假设 / 面向单一领域」，局部性改述为「系统主动维持」；README「核心赌注」节→「核心定位」；doc-hierarchy spec 同步

## 2026-06-13

- **[perf-optimization-overhaul](openspec/changes/archive/2026-06-13-perf-optimization-overhaul/)** — 性能优化：estimate_node 缓存、写管线复用优化、LLM 重试退避、SQLiteStore.delete_node 优化、rerank 分词缓存
- **[fix-rich-content-gaps](openspec/changes/archive/2026-06-13-fix-rich-content-gaps/)** — 修复 rich-concept-content 引入的风险：merge content 无界增长、别名通道收窄、检索指标验证

## 2026-06-11

- **[rich-concept-content](openspec/changes/archive/2026-06-11-rich-concept-content/)** — 丰富概念描述 + 移除 statements 机制，解决 root 扇出过高和 navigate_hub 信息不足
- **[directed-edges-proactive-fanout](openspec/changes/archive/2026-06-11-directed-edges-proactive-fanout/)** — 定向边 + 主动扇出控制，修复扁平直挂反例

## 2026-06-09

- **[batch-neighbor-selection](openspec/changes/archive/2026-06-09-batch-neighbor-selection/)** — 批量邻居选择，减少频繁小规模 LLM 调用

## 2026-06-07

- **[unified-storage-abstraction](openspec/changes/archive/2026-06-07-unified-storage-abstraction/)** — 统一存储抽象，合并 GraphStoreInterface 和 StorageInterface
- **[token-budget-traverse](openspec/changes/archive/2026-06-07-token-budget-traverse/)** — token 预算驱动的遍历，替代 max_picked 节点计数
- **[preprocess-split](openspec/changes/archive/2026-06-07-preprocess-split/)** — 前置处理插件拆分（WRITE_PREPROCESS / QUERY_PREPROCESS）
- **[preprocess-plugin-type](openspec/changes/archive/2026-06-07-preprocess-plugin-type/)** — 前置/后置插件类型分离，类型系统静态约束
- **[plugin-type-reorg](openspec/changes/archive/2026-06-07-plugin-type-reorg/)** — 插件类型重组，目录按类型而非阶段分组
- **[mcs-builder-refactor](openspec/changes/archive/2026-06-07-mcs-builder-refactor/)** — MCS 退化为瘦门面，Builder 负责组装
- **[mcs-builder-abstraction](openspec/changes/archive/2026-06-07-mcs-builder-abstraction/)** — MCSBuilder 抽象，支持 Phase 1/2 不同构建策略

## 2026-06-06

- **[unify-plugin-base](openspec/changes/archive/2026-06-06-unify-plugin-base/)** — 统一插件基类 core/plugin.py
- **[storage-abstraction-layer](openspec/changes/archive/2026-06-06-storage-abstraction-layer/)** — 存储抽象层，GraphStore 与存储实现解耦
- **[seed-graph-directional-hierarchy](openspec/changes/archive/2026-06-06-seed-graph-directional-hierarchy/)** — 分层种子图 + 定向层级边
- **[max-context-reclustering](openspec/changes/archive/2026-06-06-max-context-reclustering/)** — 最大上下文重聚类，修复不变量违背
- **[bench-restructure](openspec/changes/archive/2026-06-06-bench-restructure/)** — 评测目录重构，bench/ 从 mcs/ 包中独立

## 2026-06-05

- **[subgraph-bounding](openspec/changes/archive/2026-06-05-subgraph-bounding/)** — 子图边界能力，量化诊断语义层空转问题
- **[ollama-llm-adapter](openspec/changes/archive/2026-06-05-ollama-llm-adapter/)** — Ollama 本地 LLM 适配器，零 token 成本
- **[graph-construction-quality](openspec/changes/archive/2026-06-05-graph-construction-quality/)** — 图构建质量研究，量化稀疏/碎片化问题

## 2026-06-02

- **[query-rerank-and-persistence](openspec/changes/archive/2026-06-02-query-rerank-and-persistence/)** — 查询重排 + 持久化修复，recall@10 从 0.14→0.81
- **[bench-doc-rerank](openspec/changes/archive/2026-06-02-bench-doc-rerank/)** — 文档级重排评测，量化节点→文档映射的稀释问题

## 2026-06-01

- **[multihop-rag-eval](openspec/changes/archive/2026-06-01-multihop-rag-eval/)** — MultiHop-RAG 评测框架，替代范式错配的 HotpotQA

## 2026-05-31

- **[add-claude-llm-adapter](openspec/changes/archive/2026-05-31-add-claude-llm-adapter/)** — Claude/Anthropic LLM 适配器
- **[add-auto-persistence](openspec/changes/archive/2026-05-31-add-auto-persistence/)** — 自动持久化机制，SQLite 增量落盘

## 2026-05-30

- **[phase1-implement-unified-workflow](openspec/changes/archive/2026-05-30-phase1-implement-unified-workflow/)** — Phase 1 完整实施：接口重写、核心引擎改造、5 个默认插件

## 2026-05-29

- **[unified-workflow-architecture](openspec/changes/archive/2026-05-29-unified-workflow-architecture/)** — 统一工作流架构定义（4 个 capability）

## 2026-05-28

- **[init-project-skeleton](openspec/changes/archive/2026-05-28-init-project-skeleton/)** — 项目骨架初始化
