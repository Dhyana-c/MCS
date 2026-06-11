## Why

609 篇全量建图耗时 7 小时、1000 query 评测耗时 1.75 小时。性能瓶颈分析定位到一组高杠杆优化点：`estimate_node` 无缓存导致遍历阶段平方级 CPU 开销、写管线阶段②复用完整查询管线（含 rerank/summary）、LLM 适配器无重试/退避（429 直接吞成空结果）、`SQLiteStore.delete_node` 遍历全图找入边 O(V)、rerank 每次查询对每个候选节点现场 jieba 分词。这些问题叠加后，系统在 CPU、LLM 调用量、I/O 三个维度都有明显浪费。此外还发现一个静默丢上下文的正确性 bug（`ctx.related = related if isinstance(related, list) else []`）和若干架构洁癖问题。

## What Changes

### CPU 热点消除（优化 1+2）

- `TokenBudget.estimate_node` 添加查询期 memoization：`QueryContext` 挂 `dict[node_id, int]` 缓存，写路径节点变更时 invalidate
- `_traverse` 的 `used_tokens` 改为增量累加（节点进 accumulated 时加一次），删除每轮 `sum(estimate_node(n) for n in accumulated)` 的全量重算
- `_traverse` 内部数据结构优化：`queue` 从 `list` 换 `collections.deque`；`batch_neighbors` 查找从线性扫描换 `{id: node}` 字典；`ContextRenderer` 实例提到 while 循环外
- 批量打包 token 估算去重：共享邻居的 token 不再重复计入每个中心节点，消除系统性高估 → 批次更大 → LLM 调用更少

### 写管线轻量定位模式（优化 3）

- `QueryEngine` 新增 `query_nodes(text, max_rounds=1, skip_postprocess=True)` 轻量模式：仅执行入口插件 + trim + 至多一轮扩展，跳过 rerank/summary 等后处理
- `WritePipeline` 阶段②改用 `query_nodes` 替代 `query`
- **附带修复**：删除 `ctx.related = related if isinstance(related, list) else []` 的静默丢上下文逻辑，轻量模式直接返回 `ctx.result_set`（始终为 `List[Node]`）

### LLM 重试 + 退避（优化 4）

- LLM 适配器 `_raw_call` 对 429（rate limit）和网络错误加指数退避重试（默认 3 次，初始 1s，系数 2）
- 成功返回或非可重试错误直接抛出

### SQLiteStore 反向邻接表（优化 5）

- 新增 `_reverse_adjacency: dict[str, set[str]]`，`add_edge` / `delete_edge` 时同步维护
- `delete_node` 的入边查找从 `for other_id in list(self._adjacency)` O(V) 改为查 `_reverse_adjacency` O(degree)
- 新增 `add_bidirectional(source_id, target_id)` 辅助方法，减少语义边写入的存在性检查

### rerank token set 预计算（优化 6）

- 索引时预计算每个节点的 `(name_tokens, content_tokens)` 缓存，挂在 `AliasIndexPlugin` 或独立 cache
- 节点更新时随 `update_entry` 失效
- 查询时只分词 query 本身，候选节点直接查缓存

### 架构洁癖（优化 7）

- `_guard_invariant` 不再 import `FanoutReducerPlugin` 并调私有方法；将守门检查提升为 `CompactionPluginInterface` 的正式方法 `guard(node, store, llm_caller)`
- `_traverse` 的 `register_prompt("select_nodes", BATCH_USER_TEMPLATE)` try/finally 换装改为注册独立 `select_nodes_batch` purpose，消除并发竞态风险

### 防御性收尾（优化 8）

- `_locate_seeds` 的 EntryPlugin 循环加 per-plugin `try/except`，异常时 log + 降级继续，不拖垮整次种子定位

## Capabilities

### New Capabilities

- `estimate-memoization`: 查询期 `estimate_node` 缓存机制 + 增量 `used_tokens` 累加，消除遍历阶段平方级 CPU 开销
- `lightweight-query`: `QueryEngine.query_nodes()` 轻量查询模式，供写管线阶段②关联定位使用，跳过后处理链
- `llm-retry-backoff`: LLM 适配器对 429/网络错误的指数退避重试机制

### Modified Capabilities

- `token-budget-traverse`: 增量 `used_tokens` 替代全量重算的终止条件检查；批量打包 token 估算去除共享邻居重复计数
- `batch-neighbor-traverse`: 内部数据结构优化（deque、dict lookup、ContextRenderer 复用）不改 spec 语义，仅补充性能约束
- `store-interface`: `add_bidirectional` 辅助方法；`delete_node` 性能从 O(V) 改为 O(degree) 的反向邻接表保证
- `query-rerank`: 节点 token set 预计算缓存 + 更新时失效机制
- `plugin-protocol`: `CompactionPluginInterface` 新增正式 `guard(node, store, llm_caller)` 方法；`_locate_seeds` per-plugin 异常隔离
- `llm-interaction`: 新增 `select_nodes_batch` purpose，替代 try/finally 动态换装
- `write-pipeline`: 阶段②改用轻量查询模式；删除静默丢上下文的 isinstance 检查
- `query-pipeline`: `_locate_seeds` per-plugin 异常隔离保证

## Impact

### 受影响代码

| 文件 | 变更类型 |
|------|----------|
| `core/token_budget.py` | 新增 memoization 机制 |
| `core/query_engine.py` | 增量 used_tokens、deque、dict、轻量模式、异常隔离、独立 purpose |
| `core/write_pipeline.py` | 阶段②调用改为 query_nodes、guard 提升后不再 import FanoutReducerPlugin |
| `core/context_renderer.py` | 实例复用（无 API 变更） |
| `stores/sqlite_store.py` | 反向邻接表、add_bidirectional |
| `plugins/llm/deepseek_llm.py` | 重试 + 退避 |
| `plugins/index/rerank.py` | token set 缓存 |
| `plugins/maintenance/fanout_reducer.py` | 私有方法提升为接口方法 |
| `prompts/select_nodes.py` | 新增 BATCH_USER_TEMPLATE 注册为独立 purpose |

### 非破坏性变更

所有优化均保持默认基线行为不变。`query_nodes` 是新增方法，不改变 `query()` 签名。`add_bidirectional` 是新增方法。`CompactionPluginInterface.guard` 带默认实现（调用已有的 `_exceeds_budget` + `_compact_node`），现有插件无需改动。

### 依赖

无新增外部依赖。`collections.deque` 为标准库。

### 风险

- **轻量定位模式**可能降低建图时关联锚点质量（少一轮扩展、无 rerank）——需要 bench 对比验证
- **token 估算去重**使批次更大，单次 LLM 调用输入更长——但仍在 T 预算内，不应触发截断
- **重试 + 退避**增加单次 LLM 调用的最坏延迟（3 次重试 × 指数退避）——可通过配置调整
