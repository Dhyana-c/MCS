## 0. 包独立化（结构变更）

- [x] 0.1 `git mv mcs/agent mcs_agent`（保留历史）
- [x] 0.2 改 mcs_agent 内部 import：`mcs.agent.*` → `mcs_agent.*`（对 mcs 的 `from mcs.*` 保留）
- [x] 0.3 `__main__.py`：`python -m mcs_agent`
- [x] 0.4 改 `tests/test_agent_*.py` import 为 `mcs_agent.*`
- [x] 0.5 `pyproject.toml`：`[agent]` deps + 包发现覆盖 mcs_agent
- [x] 0.6 全量测试通过（迁移无回归）

## 1. MemoryStore 细粒度原语

- [x] 1.1 加 `learn(text)`（= ingest 封装）
- [x] 1.2 加 `search(query, mode)`：keyword（种子定位）/ direct（根高层节点）/ vector（空壳）
- [x] 1.3 加 `associate(seed_id, mode)`：mcs（mcs.query(existing_context)）/ hot、random（空壳）
- [x] 1.4 加 `find_path(source_id, target_id, max_hops=6)`：双向 BFS，不连通/不存在返回提示
- [x] 1.5 加 `recall(limit)`（空壳）
- [x] 1.6 节点 id 渲染 helper（工具返回带 `[id:...]`）
- [x] 1.7 删除旧 query/ingest 文本方法（decision 8，确认无外部引用）

## 2. QueryEngine 公共薄方法（decision 5）

- [x] 2.1 加 `QueryEngine.locate_seeds(query) -> list[Node]`
- [x] 2.2 测试 locate_seeds 等价 `_locate_seeds`、不改 query 行为

## 3. loop 工具表与系统提示词

- [x] 3.1 `MEMORY_TOOLS` 换 5 工具 + 完整 description
- [x] 3.2 `DEFAULT_SYSTEM_PROMPT` 改导航导向
- [x] 3.3 `_dispatch` 分发 5 工具 + 参数解析

## 4. 测试

- [x] 4.1 `test_agent_loop`：5 工具分发、多步 id 传递、空壳模式返回"未实现"、未知工具、JSON 错误、max_turns 回退
- [x] 4.2 `test_agent_memory`：search keyword/direct/vector、associate mcs/hot/random、find_path 连通/不连通/不存在节点、recall 空壳、learn 转发
- [x] 4.3 全量回归通过

## 5. 验收

- [x] 5.1 全量测试通过（584）
- [ ] 5.2 端到端（可选，需 key）：接真实 LLM 跑一轮 search→associate 导航对话 —— 未做（可选，需真实 LLM 凭据）
