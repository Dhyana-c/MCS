## 1. estimate_node 缓存 + 增量 used_tokens（CPU 热点消除）

- [ ] 1.1 `core/token_budget.py`：`estimate_node` 新增可选 `cache: dict[str, int] | None = None` 参数，命中直接返回，未命中计算后写入
- [ ] 1.2 `core/query_engine.py`：`_traverse` 入口初始化 `estimate_cache = {}`，所有 `estimate_node` 调用传入 cache
- [ ] 1.3 `core/query_engine.py`：`used_tokens` 改为增量累加（节点进 accumulated 时 `+= estimate_node(node, cache)`），删除每轮 `sum(estimate_node(n) for n in accumulated)` 全量重算
- [ ] 1.4 验证：运行 `pytest -q` 确保基线测试通过

## 2. _traverse 数据结构优化

- [ ] 2.1 `core/query_engine.py`：`queue` 从 `list` 换 `collections.deque`，`pop(0)` → `popleft()`，`insert(0, ...)` → `appendleft(...)`
- [ ] 2.2 `core/query_engine.py`：`batch_neighbors` 查找从 `next((n for n in ... if n.id == ...))` 线性扫描改为 `{id: node}` dict O(1) 查找
- [ ] 2.3 `core/query_engine.py`：`ContextRenderer` 实例从 while 循环内提到循环外复用
- [ ] 2.4 验证：运行 `pytest -q` 确保基线测试通过

## 3. 批量打包 token 估算去重

- [ ] 3.1 `core/query_engine.py`：打包阶段跟踪 `batch_neighbor_tokens: int`，仅对首次加入 `neighbor_to_center` 的邻居累加 token，共享邻居不重复计入
- [ ] 3.2 验证：运行 `pytest -q` + 手动确认批次大小变化（批次应更大、LLM 调用次数应更少）

## 4. 写管线轻量定位模式

- [ ] 4.1 `core/query_engine.py`：新增 `query_nodes(text, max_rounds=1, skip_postprocess=True) -> List[Node]` 方法，走精简管线（①②③，跳过④⑤）
- [ ] 4.2 `core/write_pipeline.py`：阶段②从 `self.query_engine.query(processed)` 改为 `self.query_engine.query_nodes(processed)`
- [ ] 4.3 `core/write_pipeline.py`：删除 `ctx.related = related if isinstance(related, list) else []` 的 isinstance 检查，直接赋值
- [ ] 4.4 验证：运行 `pytest -q` 确保基线测试通过

## 5. LLM 重试 + 指数退避

- [ ] 5.1 `plugins/llm/deepseek_llm.py`：`_raw_call` 对 429（`RateLimitError`）和网络错误（`APIConnectionError`）加指数退避重试（默认 3 次，base_delay=1s，factor=2）
- [ ] 5.2 `plugins/llm/deepseek_llm.py`：构造函数新增 `max_retries: int = 3` 和 `base_delay: float = 1.0` 可配置参数
- [ ] 5.3 验证：运行 `pytest -q` 确保基线测试通过

## 6. SQLiteStore 反向邻接表

- [ ] 6.1 `stores/sqlite_store.py`：新增 `_reverse_adjacency: dict[str, set[str]]` 属性，`__init__` 中初始化
- [ ] 6.2 `stores/sqlite_store.py`：`add_edge` 同步更新 `_reverse_adjacency[target_id].add(source_id)`
- [ ] 6.3 `stores/sqlite_store.py`：`delete_edge` 同步更新 `_reverse_adjacency[target_id].discard(source_id)`
- [ ] 6.4 `stores/sqlite_store.py`：`delete_node` 入边查找改为遍历 `_reverse_adjacency.get(node_id, set())` 替代全图扫描
- [ ] 6.5 `stores/sqlite_store.py`：`load()` 方法加载完成后重建 `_reverse_adjacency`
- [ ] 6.6 `stores/sqlite_store.py` 或 `stores/in_memory.py`：新增 `add_bidirectional(source_id, target_id)` 辅助方法（默认实现调用两次 `add_edge`）
- [ ] 6.7 验证：运行 `pytest -q` 确保基线测试通过

## 7. rerank token set 预计算缓存

- [ ] 7.1 `plugins/index/rerank.py`：`LexicalScorer` 新增 `_token_cache: dict[str, tuple[set[str], set[str]]]` 属性
- [ ] 7.2 `plugins/index/rerank.py`：`score` 方法优先查 `_token_cache`，未命中时 `_tokenize` 后写入缓存
- [ ] 7.3 验证：运行 `pytest -q` 确保基线测试通过

## 8. 架构洁癖：CompactionPluginInterface guard 提升

- [ ] 8.1 插件接口层：`CompactionPluginInterface` 新增 `guard(node, store, llm_caller) -> None` 方法（默认空实现）
- [ ] 8.2 `plugins/maintenance/fanout_reducer.py`：将 `_exceeds_budget` + `_compact_node` 逻辑整合到 `guard` 方法中
- [ ] 8.3 `core/write_pipeline.py`：`_guard_invariant` 改为遍历所有 CompactionPlugin 调用 `guard`，删除 `from ... import FanoutReducerPlugin` 及对私有方法的调用
- [ ] 8.4 验证：运行 `pytest -q` 确保基线测试通过

## 9. 架构洁癖：select_nodes_batch 独立 purpose

- [ ] 9.1 `prompts/select_nodes.py` 或对应文件：将 `BATCH_USER_TEMPLATE` 注册为独立 purpose `select_nodes_batch`
- [ ] 9.2 `core/query_engine.py`：`_traverse` 批量扩展阶段从 `register_prompt` try/finally 换装改为直接 `llm.call(purpose="select_nodes_batch", ...)`
- [ ] 9.3 验证：运行 `pytest -q` 确保基线测试通过

## 10. _locate_seeds per-plugin 异常隔离

- [ ] 10.1 `core/query_engine.py`：`_locate_seeds` 的 EntryPlugin 循环加 per-plugin `try/except`，异常时 `logging.warning` 记录插件名和错误信息后继续
- [ ] 10.2 验证：运行 `pytest -q` 确保基线测试通过

## 11. 全量验证

- [ ] 11.1 运行完整测试套件 `pytest -q` 确认所有测试通过
- [ ] 11.2 运行 bench 评测对比优化前后的 wall time 和 hit@10（验证轻量定位模式 + token 去重不影响质量）
