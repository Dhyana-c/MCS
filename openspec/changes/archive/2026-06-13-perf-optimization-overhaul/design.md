## Context

MCS 当前在 609 篇全量建图（~7h）和 1000 query 评测（~1.75h）下暴露出明显的性能瓶颈。经逐行代码分析和验证，瓶颈分布在三个层面：

1. **CPU 密集**：`estimate_node` 每次调用完整渲染 + CJK 字符计数，在 `_traverse` 的 while 循环中被 O(轮数 × 累积节点数) 调用，上限接近平方级。`queue.pop(0)` / `insert(0,..)` 在 list 上 O(n)。`batch_neighbors` 线性扫描查 id。
2. **LLM 调用过量**：写管线阶段②复用完整查询管线（含 rerank/summary），但目的只是找关联锚点。批量打包的 token 估算对共享邻居重复计数，导致批次被切得比实际需要的小。
3. **I/O 与正确性**：`SQLiteStore.delete_node` 遍历全图 O(V) 找入边。LLM 适配器无重试，429 直接吞成空结果。rerank 每次查询对每个候选节点现场 jieba 分词。`ctx.related` 的 isinstance 检查静默丢上下文。

现有架构约束：插件体系（`PluginType` 索引）、单向依赖（core 不依赖 interfaces）、语义边双单向边、hub 对 LLM 同构。

## Goals / Non-Goals

**Goals:**

- 消除 `estimate_node` 平方级 CPU 开销，遍历阶段纯 Python 开销降一个数量级
- 写管线阶段② LLM 调用量显著下降（轻量定位模式）
- 批量打包 LLM 调用次数减少（token 估算去重 + 更大批次）
- LLM 适配器对 429/网络抖动具备弹性重试能力
- `delete_node` 入边查找从 O(V) 降为 O(degree)
- rerank 查询侧分词开销降至 O(query)（候选节点走缓存）
- 修复 `ctx.related` 静默丢上下文的正确性 bug
- 消除架构洁癖问题（guard 打穿插件边界、prompt 换装竞态）
- 所有优化保持默认基线行为不变，已有测试通过

**Non-Goals:**

- 不做写入管线 chunk 级流水线并发（架构改动过大，后续独立 change）
- 不做查询侧并发（只读并发需更大范围改动）
- 不做 async LLM 接口改造
- 不改 rerank 的打分算法本身（只加缓存层）
- 不改 `estimate_node` 的估算口径（铁律一保证估算 == 渲染，缓存只是避免重复计算）

## Decisions

### D1：estimate_node 缓存放 QueryContext 还是 TokenBudget 内部？

**选择**：放在 `QueryContext` 上，作为 `metadata["estimate_cache"]` 的 `dict[str, int]`。

**理由**：
- 查询期间节点不变，缓存天然有效，无需失效逻辑
- 写路径上节点会变，不应使用缓存——放在 QueryContext 上自动隔离读写
- `TokenBudget` 被 read/write 共用，如果在 TokenBudget 内部缓存需要手动 invalidate，增加复杂度
- 替代方案（`functools.lru_cache` on `estimate_node`）：Node 对象不可 hash，需要 key 为 node_id，且需要手动清理，不如显式 dict 清晰

**实现细节**：
- `_traverse` 入口处初始化 `estimate_cache: dict[str, int] = {}`
- `TokenBudget` 新增 `estimate_node(node, cache=None)` 方法，cache 非空时先查后算
- `used_tokens` 改为增量累加：节点进 accumulated 时 `used_tokens += estimate_node(node, cache)`

### D2：轻量定位模式的接口形态

**选择**：`QueryEngine.query_nodes(text, max_rounds=1, skip_postprocess=True) -> List[Node]`

**理由**：
- 不改 `query()` 签名，零破坏性
- `skip_postprocess=True` 跳过整个后处理链（rerank/summary 等）
- `max_rounds=1` 限制遍历深度，默认一轮扩展足够定位锚点
- 返回 `List[Node]` 直接赋给 `ctx.related`，消除 isinstance 检查
- 替代方案（`query(text, mode="lightweight")`）：改 query 签名，所有调用方受影响

**实现细节**：
- `query_nodes` 内部走 ① 前置 → ② 种子定位（含异常隔离）→ ③ 遍历（max_rounds=1）→ 跳过 ④⑤
- 直接返回 `ctx.result_set`，不经后处理链

### D3：LLM 重试放在哪一层？

**选择**：放在 `LLMInterface` 基类的 `_call_with_retry` 方法内，三适配器共享。

**理由**：
- 三个适配器需要完全相同的重试逻辑，复制三份是维护负担
- 提升到基类后，一次实现覆盖所有适配器，未来新增适配器自动获得重试能力
- 厂商特化的错误识别仍由各适配器在 `_do_raw_call` 内完成（标记 `LLMCallError(retryable=True/False)`）
- `llm-interaction` spec 说"重试 MAY 添加在厂商插件内"——基类也是厂商插件的一部分，不冲突
- 退避参数通过 `self.config` 注入（`max_retries`, `base_delay`），各适配器可独立覆盖

**实现细节**：
- `LLMInterface._call_with_retry(fn, *args, **kwargs)` 封装退避循环
- 各适配器 `_raw_call` 改调 `self._call_with_retry(self._do_raw_call, system, user)`
- `_do_raw_call` 内捕获厂商异常，标记 `retryable` 后抛 `LLMCallError`
- 指数退避 + jitter：`delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)`
- 默认 `max_retries=3`, `base_delay=1.0`

### D4：反向邻接表的数据结构

**选择**：`SQLiteStore` 新增 `_reverse_adjacency: dict[str, set[str]]`

**理由**：
- `add_edge(A→B)` 时同时 `_reverse_adjacency[B].add(A)`
- `delete_edge(A→B)` 时同时 `_reverse_adjacency[B].discard(A)`
- `delete_node(X)` 的入边查找变为 `for source_id in self._reverse_adjacency.get(X, set())`
- 内存开销：每条边多一个反向索引条目，MCS 边数通常 < 10k，忽略不计
- 替代方案（仅在 `_adjacency` 上做惰性扫描）：不改，但 O(V) 问题依旧

### D5：rerank token set 缓存的归属

**选择**：缓存在 `LexicalScorer` 内部，`dict[tuple[str, int], tuple[set[str], set[str]]]`，key 为 `(node_id, content_hash)`。

**理由**：
- `LexicalScorer` 是唯一消费者，不需要暴露到 AliasIndexPlugin
- 节点内容在查询间不变，缓存永不过期（查询期间）
- cache key 含 `content_hash`（`hash(node.content)`），确保 `_dispatch_merge` 原地改写 content 后缓存自动失效（hash 变化 → miss → 重新分词），无需额外失效逻辑
- 跨查询缓存需要在 write 路径上 invalidate，目前 rerank 只在 read 路径，暂不跨查询缓存
- 后续如需跨查询缓存，可以在 `AliasIndexPlugin` 上加 hook

### D6：CompactionPluginInterface guard 方法的提升

**选择**：在 `CompactionPluginInterface` 新增 `guard(node, store, llm_caller) -> None` 方法，带默认空实现。

**理由**：
- 默认空实现 → 不关心守门的插件（如 SummaryRegenPlugin）无需改动
- `FanoutReducerPlugin` 覆写此方法，实现原有的 `_exceeds_budget` + `_compact_node` 逻辑
- `_guard_invariant` 遍历所有 CompactionPlugin，调用 `guard`，不再 import 具体插件类
- 替代方案（新增 `GuardPluginInterface`）：过度设计，守门和压缩是同一职责

### D7：select_nodes_batch 独立 purpose

**选择**：在 `prompts/select_nodes.py` 中将 `BATCH_USER_TEMPLATE` 注册为独立 purpose `select_nodes_batch`。

**理由**：
- 消除 try/finally 换装的竞态风险
- `select_nodes` 和 `select_nodes_batch` 是两个不同的 purpose，各有自己的 template
- `_traverse` 中直接 `llm.call(purpose="select_nodes_batch", ...)` 即可

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| 轻量定位模式可能降低建图时关联锚点质量 | 可通过 bench 对比 hit@10 验证；最坏情况 `max_rounds=2` 仍比完整管线轻量 |
| token 估算去重使批次更大，单次 LLM 输入更长 | 仍在 T × 0.8 阈值内，不会超窗口 |
| 重试增加单次 LLM 调用最坏延迟（3× 重试 + 退避 ≤ 7s） | 可通过 `max_retries` 配置调整；429 本身意味着需要等待 |
| 反向邻接表增加内存开销 | 每条边多一个 set 条目，10k 边约 < 1MB |
| `estimate_cache` 不感知节点变更 | 仅在查询期使用，写路径不使用此缓存，安全隔离 |
| `CompactionPluginInterface.guard` 默认空实现可能被遗忘 | `_guard_invariant` 遍历所有 COMPACTION 插件调用 guard，即使某插件不实现也不影响其他插件 |

## Migration Plan

本次变更为纯代码优化，无数据迁移、无配置格式变更、无 API breaking change。

**部署顺序**：

1. **Phase 1 — 零风险纯性能优化**（不改任何行为）：
   - estimate_node 缓存 + 增量 used_tokens
   - deque + dict lookup + ContextRenderer 复用
   - LLM 重试 + 退避
   - SQLiteStore 反向邻接表 + add_bidirectional
   - _locate_seeds per-plugin 异常隔离

2. **Phase 2 — 行为微调**（需 bench 验证）：
   - 批量打包 token 估算去重
   - 写管线轻量定位模式
   - rerank token set 预计算

3. **Phase 3 — 架构清理**（不影响运行时）：
   - CompactionPluginInterface guard 提升
   - select_nodes_batch 独立 purpose

**回滚策略**：每个优化独立，可单独回滚。轻量定位模式可一步回滚到 `query_engine.query()`。

**验证**：
- 每个 Phase 完成后跑 `.venv\Scripts\python.exe -m pytest -q` 确保基线测试通过
- Phase 2 完成后跑 `bench/` 全量评测对比 hit@10 和 wall time
