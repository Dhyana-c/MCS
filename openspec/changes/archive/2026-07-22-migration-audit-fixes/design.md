# Design — migration-audit-fixes

> 实现设计。每 finding 的精确修法已在 code-review 深挖阶段产出（15 agent 并行），本文摘设计要点
> 与横切校准；逐行改法见 `tasks.md` + 各 finding 的「精确改法」备注。

## 1. 总览

15 finding / 6 组 / 两簇：

| 组 | finding | 文件 | 修法核心 | 风险 |
|---|---|---|---|---|
| **A** agent multi-universe | A1 ingest work_id | memory/server/tools | 三层入口透传可选 work_id → IngestInput → ③b | medium |
| | A2 arbitrate universe | memory._do_arbitrate | get_related_events 传 universe=首事实 | low |
| | A3 recall universe | memory._do_recall + tools | 按 universe 过滤事件（默认 __reality__）+ 渲染 | low |
| | A4 render universe | memory._render_nodes | 非现实 universe 时标 [universe:xxx] | low |
| **B** shutdown 竞态 | B1 | memory + loop | _closed sentinel + MemoryShuttingDown + chat loop 短路 | low |
| **C** retire-framework 收尾 | C1 _traverse 默认 | query_engine | select_facts → select_facts_write | low |
| | C2 arbitrate 死分支 | context_renderer | 删 _ALL_SUMMARY_PURPOSES + 孤儿测试 + spec 枚举 | low |
| | C3 _run_preprocess 死壳 | query_engine | 删方法 + 2 调用点 + 1 测试 | low |
| **D** bench 收尾+指标 | D1 CapturingMemory | runner + agent_case_study | 捕获 associate 邻居（渲染仍走基类） | low |
| | D2 locomo track | __main__ | 删 track 传参 + argparse + docstring | low |
| **E** doc/spec 漂移 | E1 README query | README | mcs.query() → locate_seeds | low |
| | E2 spec Postprocess | bench-doc-rerank-plugin spec | 收敛到纯函数现状 | low |
| | E3 docstring/doc | memory + 2 md | 删 render_query_result / V4 / mcs.query 漂移 | low |
| **F** tests + cleanup/eff | F1 fake associate | 3 test 文件 | 改签名加 limit | low |
| | F2 prompt 抽公共 | prompts/_common.py + 13 prompt | NODE_CLASS_BY_LABEL 去重 + language_follow_clause | low |
| | F3 效率 | context + memory | 增量记账 + 批量 get_nodes | low |

全部**向后兼容**：核心公共 API 仅可选参数扩展（默认值与现状逐字一致）。

## 2. A 簇：agent multi-universe 完整性（宪法级，核心）

### 2.1 问题本质

`work-narrative-events` + `multi-universe-graph` 两个 change 把 universe 归属轴落到了**图模型 + 写管线**
（`IngestInput.work_id` → `_resolve_universe` → `extract_work_events` ③b 门控；载重双类过滤；每 universe
独立时间轴）。但 agent 时代主入口（`mcs_agent/memory.py` 的 `learn`/`arbitrate`/`recall`/`_render_nodes`
+ `mcs_mcp/server.py` 的 `run_ingest`）**没有跟上**，导致四条缺口：

```
A1: learn(text) ─str归一化─▶ IngestInput(work_id=None) ─▶ target_universe 恒 __reality__
                              └─ ③b extract_work_events 门控永不触发 ─▶ 作品叙事事件静默禁用
A2: _do_arbitrate ─▶ get_related_events(f.id, limit=k)  [universe=None 全返含跨universe]
                              └─ 互斥事实虽同universe、反查事件不限域 ─▶ 他世界事件污染裁决
A3: _do_recall ─▶ get_nodes_by_class(CLASS_EVENT)  [无universe过滤]
                              └─ 现实ISO(epoch≈1.78e9) 与 作品纪年(200) 混排 ─▶ 破坏独立时间轴
A4: _render_nodes ─▶ "i. [id:x] name — content"  [无universe]
                              └─ LLM 看不到节点归属 ─▶ timeline/link_cross_universe 决策缺信号
```

### 2.2 闭合设计

**A1（work_id 透传）**——三层入口逐层加可选 `work_id: str | None = None`：
- `MemoryStore._do_learn(text, work_id=None)` / `learn(text, work_id=None)`：work_id 非空走
  `mcs.ingest(IngestInput(content=text, work_id=work_id))`，空走原 `mcs.ingest(text)`（str 归一化路径保留）。
- `ingest_structured(content, timestamp, work_id=None)` 同款。
- `MCPServer.run_ingest(text, work_id=None)` → `agent.memory.learn(text, work_id=work_id)`；fastmcp `ingest`
  工具 + `tools._learn` handler + ToolSpec schema `work_id` 可选字段。
- **不动**底层：`write_pipeline.py:155-156` 的 `str → IngestInput(content=data)` 归一化保持「str 入参 = 现实、
  无 work_id」语义；让上层显式传 work_id 而非改归一化默认（否则所有 str 入参都进作品 universe，破坏语义）。

**A2（arbitrate universe 派生）**——universe 是**派生值非入参**（互斥事实对构造上恒同 universe，是
`write_pipeline.py:419/461/488` 拒跨 universe 互斥 + `store.py:160` invariant 双护的结果）：
- `_do_arbitrate` 在 `if not facts` 之后取 `arb_universe = facts[0].universe`；
- 任一事实跨 universe（互斥前提已破）发 warning 仍按首事实 universe 反查（不污染、不拒整个裁决）；
- `get_related_events(f.id, universe=arb_universe, limit=k)`。
- 不动 `arbitrate` 公共签名（`MemoryStore.arbitrate` 调用方零改动），不动 store 默认 `universe=None` 语义
  （`spec.md:184-189` 明示该默认是「作品 fact 无参查出处」的刻意设计，改默认会破坏 narrative_timeline 等）。

**A3（recall universe 过滤）**——与 `narrative_timeline`（`query_engine.py:175-178`）同款，**应用层过滤**
而非下沉 `store.get_nodes_by_class`（后者 5 个调用方中 3 个不需要 universe 过滤，下沉会破坏）：
- `_do_recall(limit, universe)` + `recall(limit=5, universe=REALITY_UNIVERSE)`；
- `events = [n for n in get_nodes_by_class(CLASS_EVENT) if n.universe == universe]`；
- `tools._recall` 透传 + ToolSpec schema 加可选 `universe`（默认 `__reality__`，与 search 默认同口径）。
- 默认 `__reality__`：与 system prompt 把 recall 定位为「现实近期倒排」一致，且现有 6 个 recall 测试 helper
  默认 reality、零破坏。

**A4（render universe 标签）**——`_render_nodes` 每行 id 后、name 前，**仅当 `n.universe != REALITY_UNIVERSE`**
时标 `[universe:xxx]`（现实不标，避免单 universe 仓库噪音）：
- 5 个共享原语（search/associate/generalize/split/merge）一处改全覆盖；
- timeline/get_cross_universe_edges 已各自显式渲染 universe，不在 `_render_nodes` 路径，不改；
- **不渲染 node_class**（finding 未指、split 已有非概念拒绝护栏、prompt-language-following 已让协议层英文
  concept/fact 与 LLM 沟通）——最小改动原则下不顺手扩。

### 2.3 宪法对齐校准

| 宪法条目 | A 簇修复后 |
|---|---|
| 载重命根（核心不反查同 universe 事件） | A2 反查事件限同 universe；A3 recall 限同 universe |
| 每 universe 一条独立时间轴 | A3 不再跨 universe 混排 ISO/纪年 |
| universe 归属轴（与 node_class 并列）对 LLM 可见 | A4 非现实节点标 universe |
| 摄入行为事件固定 `__reality__`（载重） | A1 work_id 走 IngestInput、摄入事件仍 __reality__，③b 抽作品事件归 work universe |
| 跨 universe 不合并 / 不互斥 | A1 透传后由 `_resolve_universe` + 既有 invariant 保证 |
| 铁律一（估算==渲染） | A4 universe 标签同步进 estimate（material 整体算）；F3 增量记账复用同一 count 结果 |

## 3. B 簇：mcp shutdown 竞态

**根因**：CPython `ThreadPoolExecutor.shutdown(wait=True)` 进锁立即置 `_shutdown=True`（早于 worker join）。
`MemoryStore.shutdown` 先 `_submit(mcs.shutdown)` 再 `executor.shutdown(wait=True)`——后者一翻转，in-flight
chat（跑在 asyncio-executor 线程、不收 KeyboardInterrupt）下一轮 `_submit` 撞 `RuntimeError('cannot
schedule new futures')`，被 `_dispatch`（loop.py:344-351）兜成 `[error]`，loop 空转至 max_turns。

**修法（优雅停机 sentinel）**：
- `MemoryStore`：`__init__` 加 `_closed=False`；`_submit` 首行 `if self._closed: raise MemoryShuttingDown`，
  并把 `executor.submit` 的 `RuntimeError('cannot schedule new futures')` 归一为 `MemoryShuttingDown`；
  `shutdown` 先翻 `_closed=True`，关 MCS 改走 `executor.submit` 直连（绕 _submit sentinel）+ `executor.shutdown(wait=True)` 兜底。
- `mcs_agent/loop.py`：`_dispatch` 增 `except MemoryShuttingDown` 特化捕获（置 `_shutting_down=True`、返回友好降级文本）；
  chat loop 每个 tool_call 后 `if self._shutting_down: break`；loop `else` 块 `termination='shutting_down'`。
- **不加跨线程 lock**：stdio server 在 client EOF 后不会再发 tool call，竞态窗口只在「已 in-flight chat」，
  sentinel + loop 短路是对此窗口最小且充分的回应。

## 4. C 簇：retire-framework 退役收尾

- **C1**：`_traverse` 默认 `select_purpose: str = "select_facts"` → `"select_facts_write"`（唯一存活 bundle）。
  不删默认强制传参（Option B）——那要改 9 处测试调用签名、是 breaking change，违反最小改动。同步把
  `tests/test_traverse_primitives.py` 8 处 `set_response("select_facts", ...)` 改 `select_facts_write`，让
  mock 反映生产真实 purpose、真正覆盖新默认路径（而非靠 MockLLM 兜底）。
- **C2**：删 `context_renderer._ALL_SUMMARY_PURPOSES = frozenset({"arbitrate"})` + `render_node_full:117` 死分支
  + `tests/test_context_renderer.py:80-96` 孤儿测试 + `llm-interaction` spec 枚举里的 `arbitrate`（adjudicate
  才是 agent arbitrate 工具实际 purpose）。`_SUMMARY_PURPOSES`（decide_directions/decide_hub/navigate_hub/
  extract_concepts）保留——仍有活跃消费者。
- **C3**：删 `QueryEngine._run_preprocess` 死壳（方法 + `query_nodes`/`locate_seeds` 2 调用点 +
  `test_locate_seeds_delegates_preprocess_then_locate` 1 测试）。**不动** `WritePipeline._run_preprocess`
  （不同类、有真实 WRITE_PREPROCESS 插件链）、不动 `PluginType.PREPROCESS` 别名。

## 5. D 簇：bench 退役收尾 + 指标修复

- **D1**：`CapturingMemory._do_associate`（runner.py + agent_case_study.py）覆写**不再 super()**（super 仅返回
  渲染文本丢节点身份），改为：调 `super(MemoryStore, self)._do_associate(seed_id, limit)` 取渲染文本（与
  production 同口径、agent 行为零变化），同时用 `mcs.store.get_relations` 复算一跳邻居（互斥前置 +
  `cap=max(1,limit)` 截断、与基类同口径）入 `records['nodes']`。`exp_time_rule_ab.py` import 复用 CapturingMemory、自动受益。
- **D2**：`bench/locomo/__main__.py` 删 `:102` `track=args.track,` + `:57` `--track` argparse 定义 + `:6-7`
  docstring `--track retrieval` 示例（检索轨 + 该形参已随 retire-framework 退役，`run_eval` 签名已无 track）。

## 6. E 簇：文档 / spec 漂移

- **E1**：`README.md:42-45` 顶层快速上手 `mcs.query("什么是深度学习？")` → `mcs.query_engine.locate_seeds("深度学习")`
  （与 `__init__.py` docstring / `examples/README.md` / `docs/getting-started.md:77-83` 已迁移的范本一致）。
  保留 MCP `query` 工具的提及（那是 mcs_mcp 工具名、非 MCS.query 方法）。
- **E2**：`bench-doc-rerank-plugin` spec 收敛到现状——`DocRerankPlugin` 类 / `PostprocessPluginInterface` /
  `PluginType.POSTPROCESS` 三者随 retire-framework 删除，spec 改述为「bench-only 纯函数（无插件类）」+
  新增 `MUST NOT 定义/继承/引用` 反向 Scenario。**不动** `plugin-protocol` spec 的 postprocess 历史叙述
  （SummaryPlugin 仍住 postprocess/ 目录的命名陷阱说明）。
- **E3**：`memory.py:24` docstring 删 `render_query_result`；`select_facts_model_differences.md` 4 处「当前
  读侧=V4」勘正为「V4 为读侧历史版本、已随 retire 删除」；`bench/locomo/README.md:52` 检索轨 `mcs.query`
  改述为「agent 触达节点 + doc_rerank 离线映射」。顺带勘正 `locomo-eval` spec.md 的 mcs.query 检索轨描述（同簇漂移）。

## 7. F 簇：tests fake + cleanup / efficiency

- **F1**：3 处坏 fake（`test_agent_tools.py:104` / `test_agent_trace.py:269,363`）改 `associate(self, seed_id,
  limit=60)`。**跳过**已正确的 4 处（`test_agent_context.py:36` / `test_agent_loop.py:34,173`——均带 limit）。
  顺带勘正 `memory-agent` spec.md:176 `associate(seed_id, mode)` → `associate(seed_id, limit?)`。
- **F2**：新建 `mcs/prompts/_common.py`——`NODE_CLASS_BY_LABEL`（原 `_NODE_CLASS_BY_LABEL` 两份合一、去前导
  下划线因跨模块共享）+ `language_follow_clause(subject, *, extra="")`（参数化辅助函数：统一「MUST 跟随原文
  语言、MUST NOT 翻译」骨架，subject 是各 prompt 的生成字段名、extra 是 unique 约束尾句如别名的「MUST NOT
  跨语言对译」）。13 个 prompt 的 `SYSTEM_PROMPT` 末尾调它，**保持模块属性名 + 英文枚举字面值不变**（27 个
  baseline 测试自动通过）。`_common.py` 不进 `__init__.py` import 清单（避免被 DEFAULT_PROMPTS 注册误扫）。
  **不并入** `mcs_agent/loop.py` 的 `LANGUAGE_FOLLOW_PROMPT`（另一 altitude：agent 回答侧 vs prompt 包层）。
- **F3**：`context.py` `_render` 单遍渲染记 `per_msg_tokens`，`base` 改累加、`est = base + count(budget_section)`
  （不再全量 sum）；`assemble` evict 循环改 O(1) 增量更新（`est -= 原 per_msg_tokens[i] + count(墓碑)`）。`memory._do_associate`
  合并两次 `[get_node(i)]` 为单次 `get_nodes(shown_mutex + shown_assoc)` 批量取 + 按 id 映射分派。**铁律一不破**：
  estimate 是纯函数确定性，复用同一文本的 count 结果与逐次调用同值（铁律一约束「同一函数对要发送文本计 token」、不约束调用次数）。

## 8. 横切校准

- **向后兼容**：所有公共 API 改动都是可选参数扩展（默认值 = 现状），老调用逐字不变。`mcs-mem` 0.1.1 的
  `ingest_structured(content, timestamp)` 位置参数调用不受影响。
- **铁律一（估算口径==渲染口径）**：A4 universe 标签同步进 estimate（material 整体算）；F3 增量记账复用同一
  count 结果——两处都保证「对要发送的文本用同一函数计 token」。
- **测试策略**：每 finding 至少 1 个边界测试（见 tasks.md 各 task 的测试要点）；A 簇加 integration（真实
  deepseek multi-universe 端到端：work_id 透传触发 ③b、recall 不跨 universe 混排）；全量 `.venv\Scripts\python.exe -m pytest -q` 回归零破坏；实现后 Workflow 6 维对抗审查（correctness / universe-闭合 / regression / doc-sync / test-coverage / altitude）。
- **存量数据**：零迁移。A1 是「补缺失能力」（之前传不进 work_id）、A2/A3 运行时过滤、B1 竞态防护、C/D/E/F
  死代码 / 文档 / 效率。本仓 bench 图库（locomo/golden_cage/multihop）均不经 agent.learn 建图（locomo builder
  直调 `mcs.ingest(IngestInput(work_id=...))`），无需重建；D1 修复后查询阶段需重跑（图不变）以反映新 touched 口径。
- **风险汇总**：medium 1（A1 触及 mcs-mem 已发布硬契约，但可选参数向后兼容、无升版压力）；其余 14 项 low。
  F2 是 13 文件机械改造、F3 触 hot path——两者靠 baseline 测试 + 对抗审查兜底。
