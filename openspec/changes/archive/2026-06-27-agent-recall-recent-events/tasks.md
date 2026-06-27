## 1. 实装 recall 原语（mcs_agent/memory.py）

- [x] 1.1 补 `CLASS_EVENT` import（与现有 `EDGE_ASSOC, Edge, Node` 同组，来自 `mcs.entities.graph`）
- [x] 1.2 新增事件渲染 helper：`_render_event_line(node)` 渲染单条（全文：name==content 只写一份 + 带 `[id:...]` + `event_meta.timestamp` 行），`_render_events` join 多条 + header（空列表返回 header + 空提示）；估算与最终渲染共用 `_render_events`（铁律一）
- [x] 1.3 实装 `_do_recall(limit)`：`store.get_all_nodes()` 过滤 `node_class==CLASS_EVENT` → 无事件返回 `_render_events([])` → 按 `event_meta.timestamp` 倒排（无 timestamp 排末尾、`node.id` 作次级排序键保证确定性）→ **双上界截断**：经 `self._mcs.query_engine.token_budget` 对「纳入后的完整渲染文本」`_render_events(candidate)` **整体估算**（含 header 与换行符，禁止分段累加单条 estimate），达 `limit>0` 条数或超 `.T` 即停（先到先停）；最近 1 条无条件全文纳入（即使超 T）；`limit<=0` 仅受 T 约束 → 全文渲染

## 2. 文案去「未实现」

- [x] 2.1 `mcs_agent/tools.py`：`recall` schema 的 `description` 去「未实现」，改为「回忆最近发生的事件（时间倒排）」
- [x] 2.2 `mcs_agent/loop.py`：`DEFAULT_SYSTEM_PROMPT` 的 recall 行去「（未实现）」，改为「回忆最近发生的事件（时间倒排）」
- [x] 2.3 `mcs_agent/memory.py`：模块 docstring 把 recall 从「未实现空壳」清单移除（向量 / hot / random 仍保留）

## 3. 测试（tests/test_agent_memory.py）

- [x] 3.1 FakeStore 补 `get_all_nodes()`；FakeQueryEngine 补 `token_budget`（真 `TokenBudget(max_tokens=小值)` 以可控 T 测截断）；改写 `test_recall_unimplemented` → `test_recall_recent_events`；模块 docstring 去「（空壳）」
- [x] 3.2 正向用例：多个带 timestamp 的事件 → 严格按 timestamp 倒序返回、全文渲染含节点 id 与 timestamp
- [x] 3.3 边界用例：无事件返回空提示；`limit` 截断（事件数 > limit 只返回最近 limit 条）；无 timestamp 事件排末尾；同 timestamp 确定性次序
- [x] 3.4 T 预算截断用例：小 T 下渲染总 token ≤ T（超 T 前停、少返回更早事件）；单条全文超 T 时仍完整返回最近 1 条
- [x] 3.5 线程安全：recall 经 `_submit` 单 worker 线程、只读 `get_all_nodes()`，不触发写 / 守门 / 裂变（FakeStore 断言只读）

## 4. 文档同步（docs/memory-agent.md）

- [x] 4.1 recall 工具表行：`✗（依赖事件热点排序）` → `✓（最近事件时间倒排）`
- [x] 4.2 第 41 行「未实现模式空壳」措辞同步（recall 已实装，不再属未实现模式）

## 5. 验证

- [x] 5.1 `openspec validate agent-recall-recent-events --strict` 通过
- [x] 5.2 `.venv\Scripts\python.exe -m pytest tests/test_agent_memory.py -q` 通过
- [x] 5.3 回归：`.venv\Scripts\python.exe -m pytest tests/test_agent_tools.py tests/test_agent_loop.py tests/test_agent_trace.py -q` 不退化（这些文件的 mock recall 测调度而非实现，应保持绿）
