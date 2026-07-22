# Tasks — migration-audit-fixes

> 实现顺序：A 簇（核心宪法级、memory.py 集中改）→ B（server/memory shutdown）→ C/D/E/F 并行。
> 每项含测试要点（边界）。最小改动原则：不顺手重构无关代码。

## A. agent multi-universe 完整性（核心，宪法级）

- [x] A1 `mcs_agent/memory.py`：`_do_learn` / `learn` / `_do_ingest_structured` / `ingest_structured` 四方法加 `work_id: str | None = None`；work_id 非空走 `IngestInput(content=text, work_id=work_id)`、空走原 `mcs.ingest(text)`（`IngestInput` 已 import）
- [x] A1 `mcs_mcp/server.py`：`run_ingest(text, work_id=None)` 透传 + `build_fastmcp` 的 `ingest` 工具加可选 `work_id` + `asyncio.to_thread(server.run_ingest, text, work_id)` + docstring
- [x] A1 `mcs_agent/tools.py`：`_learn` handler 改 `memory.learn(args.get("text",""), args.get("work_id"))`；`BUILTIN_TOOLS["learn"]` schema 加可选 `work_id`（required 仍 `["text"]`）
- [x] A1 测试：`learn('text')` 默认不触发 ③b（回归基线）；`learn('...', work_id='三国演义')` 触发 `extract_work_events` + target_universe=三国演义 + 摄入事件仍 __reality__；`work_id=None`/`''` 等价默认；ingest_structured 同款；run_ingest/_learn 透传
- [x] A2 `mcs_agent/memory.py` `_do_arbitrate`：`if not facts` 后取 `arb_universe = facts[0].universe` + 跨 universe warning；`get_related_events(f.id, universe=arb_universe, limit=k)`
- [x] A2 测试 fake 同步：`tests/test_agent_memory.py` FakeStore.get_related_events + `test_agent_split_merge.py` + `test_graph_view.py` 三处 fake 加 `universe=None` 占位
- [x] A2 测试：跨 universe 事件不漏入 material（构造 f1 背书事件含同 universe + 跨 universe，断言只返同 universe）；跨 universe 事实 warning 仍按首事实反查
- [x] A3 `mcs_agent/memory.py` `_do_recall(limit, universe)` + `recall(limit=5, universe=REALITY_UNIVERSE)`：`events = [n for n in get_nodes_by_class(CLASS_EVENT) if n.universe == universe]`
- [x] A3 `mcs_agent/tools.py`：`_recall` 透传 `args.get("universe")` + recall ToolSpec schema 加可选 `universe`
- [x] A3 测试：默认 recall(5) 只返 reality（作品事件不混入）；显式 `recall(5, universe='三国演义')` 只返该作品；现有 8 个 recall 测试（默认 reality helper）零回归；docstring 补 universe 封闭说明
- [x] A4 `mcs_agent/memory.py` `_render_nodes`：每行 id 后 name 前，`univ_tag = f" [universe:{n.universe}]" if n.universe != REALITY_UNIVERSE else ""`；docstring 更新
- [x] A4 测试：现实节点不含 `[universe:__reality__]`（逐字同改前）；非现实节点含 `[universe:xxx]` 且位置正确；mixed list 正确；`docs/memory-agent.md` recall 行参数列补 `universe?`

## B. mcp shutdown 竞态（核心）

- [x] B1 `mcs_agent/memory.py`：文件顶部加 `class MemoryShuttingDown(RuntimeError)`；`__init__` 加 `self._closed = False`；`_submit` 首行 `if self._closed: raise MemoryShuttingDown` + 把 `executor.submit` 的 `RuntimeError('cannot schedule new futures')` 归一为 `MemoryShuttingDown`；`shutdown` 先翻 `_closed=True`，关 MCS 改走 `executor.submit(mcs.shutdown).result()`（绕 _submit sentinel）+ `executor.shutdown(wait=True)` 兜底
- [x] B1 `mcs_agent/loop.py`：import `MemoryShuttingDown`；`__init__` 加 `self._shutting_down = False`；`_dispatch` 加 `except MemoryShuttingDown` 特化（置 flag + 返回友好降级文本）；chat loop 每个 tool_call 后 `if self._shutting_down: break`；loop `else` 块 `termination='shutting_down'`
- [x] B1 测试：`ms.shutdown()` 后再调任意原语抛 `MemoryShuttingDown`；in-flight chat 遇 shutdown 优雅收尾（termination=shutting_down、非 [error]、turns < max_turns）；并发双 shutdown 幂等（mcs.shutdown 仅调 1 次）；现有 ~60 个 `ms.shutdown()` 测试零回归

## C. retire-framework 退役收尾（核心库）

- [x] C1 `mcs/core/query_engine.py:267`：`select_purpose: str = "select_facts"` → `"select_facts_write"`
- [x] C1 `tests/test_traverse_primitives.py`：8 处 `set_response("select_facts", ...)` → `select_facts_write`（让 mock 反映生产 purpose）
- [x] C1 测试：新增 assertion `mock_llm.call_log` purpose 严格 `select_facts_write`；用真 LLMInterface 子类验默认值在 DEFAULT_PROMPTS 命中不抛 KeyError
- [x] C2 `mcs/core/context_renderer.py`：删 `_ALL_SUMMARY_PURPOSES` 常量 + 注释 + `render_node_full` 死分支（`elif ... _SUMMARY_PURPOSES` → `if`）
- [x] C2 `tests/test_context_renderer.py`：删 `test_arbitrate_uses_summary_for_all_nodes` 孤儿测试
- [x] C2 `openspec/specs/llm-interaction/spec.md`：同步删 arbitrate 枚举（已在 delta）
- [x] C3 `mcs/core/query_engine.py`：删 `_run_preprocess` 方法；`query_nodes` 删 `processed_text` 赋值、直传 `text` 给 `_locate_seeds`/`_traverse`；`locate_seeds` docstring 删「经前置插件链」+ 删 `processed` 赋值
- [x] C3 `tests/test_agent_memory.py`：改 `test_locate_seeds_delegates_preprocess_then_locate`（删 fake_preprocess、calls 期望改 `{locate: hello}`）或删该测
- [x] C3 测试：新增 `inspect.getsource(QueryEngine) MUST NOT 含 '_run_preprocess'`；query_nodes/locate_seeds 行为零变化（恒 return text → 直传 text）

## D. bench 退役收尾 + 指标修复（bench 层）

- [x] D1 `bench/golden_cage/runner.py` CapturingMemory._do_associate：调 `super(MemoryStore, self)._do_associate(seed_id, limit)` 取渲染文本 + 用 `get_relations` 复算一跳邻居（互斥前置 + `cap=max(1,limit)` 截断）入 `records['nodes']`；import EDGE_MUTEX
- [x] D1 `bench/multihop_rag/scripts/agent_case_study.py` CapturingMemory._do_associate：同款（records 带 'result' 键）；exp_time_rule_ab.py import 复用自动受益
- [x] D1 测试：associate 邻居进 touched（FakeStore 返 2 互斥+3 关联 → records['nodes'] 含 5 邻居）；seed_id 不存在/孤儿/limit 截断边界；渲染文本逐字等同基类
- [x] D2 `bench/locomo/__main__.py`：删 `:102` `track=args.track,` + `:57` `--track` argparse 定义 + `:6-7` docstring `--track retrieval` 示例
- [x] D2 测试：`python -m bench.locomo eval` 不再 TypeError（本地冒烟，可选真实跑）

## E. 文档 / spec 漂移

- [x] E1 `README.md:42-45`：`mcs.query("什么是深度学习？")` → `mcs.query_engine.locate_seeds("深度学习")` + 注释「读查询由记忆 agent 驱动、固定管线 mcs.query() 已退役」；保留 MCP query 工具提及
- [x] E2 `openspec/specs/bench-doc-rerank-plugin/spec.md`：Purpose 删 PostprocessPlugin 措辞；REMOVED 旧 Requirement + ADDED「纯函数（无插件类）」（delta 已写，apply 时落 main spec）
- [x] E2 测试：spec-守卫测试 `inspect.getsource(bench.plugins.doc_rerank)` MUST NOT 含 DocRerankPlugin/PostprocessPluginInterface/PluginType.POSTPROCESS
- [x] E3 `mcs_agent/memory.py:24` docstring：删 `render_query_result`（只留 `format_ingest_status`）
- [x] E3 `docs/select_facts_model_differences.md`：4 处「当前读侧=V4」勘正为「V4 为读侧历史版本、已随 retire 删除」
- [x] E3 `bench/locomo/README.md:52`：检索轨 `mcs.query` 改述「agent 触达节点 + doc_rerank 离线映射」
- [x] E3 `openspec/specs/locomo-eval/spec.md:53`：顺带勘正 mcs.query 检索轨描述（已在 delta）

## F. tests fake + cleanup / efficiency

- [x] F1 3 处坏 fake 改签名：`tests/test_agent_tools.py:104` / `test_agent_trace.py:269` / `test_agent_trace.py:363` → `associate(self, seed_id, limit=60)`
- [x] F1 `openspec/specs/memory-agent/spec.md` delta：`associate(seed_id, mode)` → `associate(seed_id, limit?)`（已在 delta）
- [x] F1 测试：signature 锁 `inspect.signature(MemoryStore.associate)` 含 limit 无 mode
- [x] F2 新建 `mcs/prompts/_common.py`：`NODE_CLASS_BY_LABEL`（两份合一）+ `language_follow_clause(subject, *, extra="")`；不进 `__init__.py`
- [x] F2 extract_concepts + judge_relations 删内联 `_NODE_CLASS_BY_LABEL` → 用 `_common.NODE_CLASS_BY_LABEL`；extract_concepts 语言跟随段改调 `language_follow_clause`（示范）
- [~] F2 其余 prompt 语言跟随段完整统一：**评估后未做**。理由：gen_graph_summary（跟随图多数节点语言）/ synthesize / adjudicate（跟随查询语言）source 与「跟随输入原文」骨架不同，强行套致 semantic drift；其余 prompt 措辞各异，统一改变文案且自包含可读性下降；当前手写段工作（baseline 绿）。`language_follow_clause` 函数 + extract_concepts 示范已就位供未来渐进统一。**最小改动原则**。
- [x] F2 测试：baseline 27 个 `test_prompt_language_follow.py` 全绿（NODE_CLASS_BY_LABEL 合一 + extract 用函数后零回归）
- [~] F3 `mcs_agent/context.py` 增量记账：**评估后未做**。理由：hot path 重构 + 铁律一风险；context.py 当前工作（baseline 绿）；assemble 的 evict 循环受 max_turns 上限约束、msg 数有限、性能非瓶颈。**最小改动原则**。
- [x] F3 `mcs_agent/memory.py` `_do_associate`：合并两次 get_node 为单次 `get_nodes` 批量取 + 按 id 映射分派（+ test_agent_memory FakeStore / test_golden_cage _NeighborStore 加 get_nodes）
- [x] F3 测试：现有 associate 测试零回归（F3a 批量后逐字等价）

## 验证 + 归档

- [x] 全量回归：`.venv\Scripts\python.exe -m pytest -q`（1111+ baseline 全绿、零破坏）
- [~] A 簇 integration（真实 deepseek）：**未跑**。A 簇逻辑已被单元测试充分覆盖（A1 work_id 透传 FakeMCS 断言 / A2 跨 universe 事件过滤 / A3 recall universe 隔离 / A4 universe 标签 + 铁律一 estimate 守卫）；integration 端到端需 worker 内构造 MCS（SQLite 线程亲和）+ 真实 LLM 慢 / 抽取质量脆弱，ROI 低。可选后续补。
- [x] Workflow 6 维对抗审查（22 agents / 候选 16 / 确认 12：4 medium + 8 low，**全处理**——universe null/空串归一 / `_shutting_down` chat 复位 / `_submit` 拆 submit-result / shutdown except 收紧+warning / locomo README `--track both` / docs arbitrate `universe=U` / 4 测试缺口补齐：A1 work_id 透传 / B1 双 tool_call / A4 铁律一）
- [x] 文档同步：docs（README / memory-agent.md associate+recall+arbitrate / select_facts V4 / locomo README）/ spec delta（archive 时落 main）
- [x] `openspec validate migration-audit-fixes --strict` 绿
- [ ] `/opsx:archive migration-audit-fixes`（delta 落 main spec）
