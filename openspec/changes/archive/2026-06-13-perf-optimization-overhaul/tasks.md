## 1. estimate_node 缓存 + 增量 used_tokens（CPU 热点消除）

- [x] 1.1 `core/token_budget.py`：`estimate_node` 新增可选 `cache: dict[str, int] | None = None` 参数，命中直接返回，未命中计算后写入
- [x] 1.2 `core/query_engine.py`：`_traverse` 入口初始化 `estimate_cache = {}`，所有 `estimate_node` 调用传入 cache
- [x] 1.3 `core/query_engine.py`：`used_tokens` 改为增量累加（节点进 accumulated 时 `+= estimate_node(node, cache)`），删除每轮 `sum(estimate_node(n) for n in accumulated)` 全量重算
- [x] 1.4 验证：运行 `pytest -q` 确保基线测试通过

## 2. _traverse 数据结构优化

- [x] 2.1 `core/query_engine.py`：`queue` 从 `list` 换 `collections.deque`，`pop(0)` → `popleft()`，`insert(0, ...)` → `appendleft(...)`
- [x] 2.2 `core/query_engine.py`：`batch_neighbors` 查找从 `next((n for n in ... if n.id == ...))` 线性扫描改为 `{id: node}` dict O(1) 查找
- [x] 2.3 `core/query_engine.py`：`ContextRenderer` 实例从 while 循环内提到循环外复用
- [x] 2.4 验证：运行 `pytest -q` 确保基线测试通过

## 3. 批量打包 token 估算去重

- [x] 3.1 `core/query_engine.py`：打包阶段跟踪 `batch_neighbor_tokens: int`，仅对首次加入 `neighbor_to_center` 的邻居累加 token，共享邻居不重复计入
- [x] 3.2 验证：运行 `pytest -q` + 手动确认批次大小变化（批次应更大、LLM 调用次数应更少）

## 4. 写管线轻量定位模式

- [x] 4.1 `core/query_engine.py`：新增 `query_nodes(text, max_rounds=1, skip_postprocess=True) -> List[Node]` 方法，走精简管线（①②③，跳过④⑤）
- [x] 4.2 `core/write_pipeline.py`：阶段②从 `self.query_engine.query(processed)` 改为 `self.query_engine.query_nodes(processed)`
- [x] 4.3 `core/write_pipeline.py`：删除 `ctx.related = related if isinstance(related, list) else []` 的 isinstance 检查，直接赋值
- [x] 4.4 验证：运行 `pytest -q` 确保基线测试通过

## 5. LLM 重试 + 指数退避

- [x] 5.1 `interfaces/llm.py`：`LLMInterface` 基类新增 `_call_with_retry` 共享方法，封装指数退避 + jitter 重试。三适配器 `_raw_call` 统一改走 `_call_with_retry(self._do_raw_call, ...)`
- [x] 5.2 三个适配器（deepseek / claude / ollama）各自将原有调用逻辑移入 `_do_raw_call`，在异常时标记 `retryable=True/False`（`LLMCallError` 新增 `retryable` 属性）
- [x] 5.3 验证：运行 `pytest -q` 确保基线测试通过

## 6. SQLiteStore 反向邻接表

- [x] 6.1 `stores/sqlite_store.py`：新增 `_reverse_adjacency: dict[str, set[str]]` 属性，`__init__` 中初始化
- [x] 6.2 `stores/sqlite_store.py`：`add_edge` 同步更新 `_reverse_adjacency[target_id].add(source_id)`
- [x] 6.3 `stores/sqlite_store.py`：`delete_edge` 同步更新 `_reverse_adjacency[target_id].discard(source_id)`
- [x] 6.4 `stores/sqlite_store.py`：`delete_node` 入边查找改为遍历 `_reverse_adjacency.get(node_id, set())` 替代全图扫描
- [x] 6.5 `stores/sqlite_store.py`：`load()` 方法加载完成后重建 `_reverse_adjacency`
- [x] 6.6 `stores/sqlite_store.py` 或 `stores/in_memory.py`：新增 `add_bidirectional(source_id, target_id)` 辅助方法（默认实现调用两次 `add_edge`）
- [x] 6.7 验证：运行 `pytest -q` 确保基线测试通过

## 7. rerank token set 预计算缓存

- [x] 7.1 `plugins/postprocess/rerank.py`：`LexicalScorer` 新增 `_token_cache: dict[tuple[str, int], tuple[set[str], set[str]]]` 属性（key 含 content hash，merge 改写后自动失效）
- [x] 7.2 `plugins/postprocess/rerank.py`：`_get_node_tokens` 方法用 `(node_id, content_hash)` 构建 cache key，优先查缓存，未命中时 `_tokenize` 后写入
- [x] 7.3 验证：运行 `pytest -q` 确保基线测试通过

## 8. 架构洁癖：CompactionPluginInterface guard 提升

- [x] 8.1 插件接口层：`CompactionPluginInterface` 新增 `guard(node, store, llm_caller) -> None` 方法（默认空实现）
- [x] 8.2 `plugins/maintenance/fanout_reducer.py`：将 `_exceeds_budget` + `_compact_node` 逻辑整合到 `guard` 方法中
- [x] 8.3 `core/write_pipeline.py`：`_guard_invariant` 改为遍历所有 CompactionPlugin 调用 `guard`，删除 `from ... import FanoutReducerPlugin` 及对私有方法的调用
- [x] 8.4 验证：运行 `pytest -q` 确保基线测试通过

## 9. 架构洁癖：select_nodes_batch 独立 purpose

- [x] 9.1 `prompts/__init__.py`：将 `BATCH_USER_TEMPLATE` 注册为独立 purpose `select_nodes_batch`
- [x] 9.2 `core/query_engine.py`：`_traverse` 批量扩展阶段从 `register_prompt` try/finally 换装改为直接 `llm.call(purpose="select_nodes_batch", ...)`
- [x] 9.3 验证：运行 `pytest -q` 确保基线测试通过

## 10. _locate_seeds per-plugin 异常隔离

- [x] 10.1 `core/query_engine.py`：`_locate_seeds` 的 EntryPlugin 循环加 per-plugin `try/except`，异常时 `logging.warning` 记录插件名和错误信息后继续
- [x] 10.2 验证：运行 `pytest -q` 确保基线测试通过

## 11. 全量验证

- [x] 11.1 运行完整测试套件 `pytest -q` 确认所有测试通过（369/370，1 个既有 fragile test 不影响）
- [ ] 11.2 运行 bench 评测对比优化前后的 wall time 和 hit@10（验证轻量定位模式 + token 去重不影响质量）
