## 1. 新增 2 个提示词 purpose（mcs/prompts/）

- [x] 1.1 新建 `mcs/prompts/generalize.py`：`SYSTEM_PROMPT`（概括若干节点的公共上位概念 / 共性，禁止空洞聚合标签）+ `USER_TEMPLATE`（`{focus}` 可选、`{material}` 占位）+ `parse(raw) -> str`（strip 自由文本，解析失败抛 `LLMParseError("generalize", ...)`）
- [x] 1.2 新建 `mcs/prompts/adjudicate.py`：`SYSTEM_PROMPT`（给定互斥事实 + 各自背书事件 + 问题，裁决采信哪个事实并给理由；同槽位互斥只留一个）+ `USER_TEMPLATE`（`{query}`、`{material}`）+ `parse(raw) -> dict`（解析 `{"adopt": [id...], "reason": "..."}`，非法 JSON / 结构抛 `LLMParseError("adjudicate", ...)`）
- [x] 1.3 `mcs/prompts/__init__.py`：`DEFAULT_PROMPTS` 注册 `"generalize"` / `"adjudicate"` 两条 `PromptBundle`（同 `decide_hub` / `arbitrate` 注册方式）；import 两个新模块

## 2. MemoryStore 两原语（mcs_agent/memory.py）

- [x] 2.1 新增 `_get_llm_plugin()` helper：经 `self._mcs.read_manager.get_all(PluginType.LLM)` 取首个 LLM 插件；为空时抛清晰错误（由 `_dispatch` 隔离为 `[error]`）；补 `PluginType` import（`from mcs.core.plugin import PluginType`）
- [x] 2.2 实装 `_do_generalize(node_ids, focus)` + `generalize(node_ids, focus=None)`：worker 线程内 `store.get_node` 取节点（不存在的 id 跳过、全空返回提示）→ 渲染 material（复用 `_render_nodes` 口径）→ 超 `token_budget.T` 按序丢尾节点截断（对完整 material 整体估算）→ **显式传 material**：`llm.call(purpose="generalize", nodes_in=[], free_args={"focus": focus or "", "material": material})`（**禁止**只传 `nodes_in=nodes` 让 `call` 内部 `ContextRenderer` 自渲染——估算与投喂会不同源、可能反超 T，见 design D7）→ 返回结论文本；`generalize()` 经 `_submit`
- [x] 2.3 实装 `_do_arbitrate(node_ids, question, events_per_fact)` + `arbitrate(node_ids, question, events_per_fact=3)`：worker 线程内取事实节点（不存在跳过、全空提示）→ 每事实 `store.get_related_events(fact_id, limit=events_per_fact)` 反查背书事件 → **自建装配**「各事实全文 + 其事件行」material（事件复用**行级** `_render_event_line`，**不**套整函数 `_render_events`——避免 recall 专属 header 重复错位）→ 超 `token_budget.T` 按**轮转保底**截断（每轮丢「剩余事件最多的事实」里最旧一条、每事实至少留 1 条、再到 0；对完整 material 整体估算；事实全文本身超 T 仍全渲染）→ `llm.call(purpose="adjudicate", nodes_in=facts, free_args={"query": question, "material": material})`（material 显式传）→ 过滤幻觉 id（只留传入事实 id）→ 过滤后非空渲染「采信 [id:X]（...），理由：...」，**过滤后为空则渲染「无有效采纳方」+ 理由**；`arbitrate()` 经 `_submit`
- [x] 2.4 模块 docstring 补 `generalize` / `arbitrate` 两原语说明（只读语义判断、调 MCS LLM 插件、不改图）

## 3. 工具注册（mcs_agent/tools.py）

- [x] 3.1 新增 `_generalize(memory, args)` handler → `memory.generalize(args.get("node_ids", []), args.get("focus"))`；新增 `_arbitrate(memory, args)` handler → `memory.arbitrate(args.get("node_ids", []), args.get("question", ""))`
- [x] 3.2 `BUILTIN_TOOLS` 加 `generalize`（schema：`node_ids: array of string` required + `focus: string` optional；desc 说明「概括若干节点的公共上位概念、只读、不改图」）与 `arbitrate`（schema：`node_ids: array of string` required + `question: string` required；desc 说明「对互斥事实反查背书事件、裁决采信方+理由、只读」，**desc 明确「`node_ids` 应为事实节点 id」**）两个 `ToolSpec`；`_arbitrate` handler / docstring **注明「内部 purpose=`adjudicate`，与查询管线的 `arbitrate` purpose 无关」**（命名消歧，见 design D9）
- [x] 3.3 注释 / docstring 里「5 个内置工具」口径同步为 7（含 `ToolsetConfig.enabled` 的「None = 全部」说明）；`MEMORY_TOOLS` 废弃别名随之含 7（保外部 import 不断裂）

## 4. system prompt（mcs_agent/loop.py）

- [x] 4.1 `DEFAULT_SYSTEM_PROMPT` 的「工具」段补两行：`generalize`（概括若干节点的共性 / 公共上位概念，帮理解概念关系）+ `arbitrate`（对若干互斥事实反查背书事件、裁决采信哪个 + 理由）；强调二者只读、节点 id 由前序工具（search/associate）返回的 `[id:...]` 提供
- [x] 4.2 「何时探索记忆图」段补一句：撞见多个相关概念想找共性、或撞见矛盾说法时，可用 generalize / arbitrate 做语义判断

## 5. 测试（tests/test_agent_memory.py 等）

- [x] 5.1 FakeStore 补 `get_related_events(node_id, limit=None)`（返回预设事件、记录调用）；FakeQueryEngine 的 `token_budget` 已就绪（recall 已补）；FakeLLMPlugin（实现 `call(purpose, nodes_in, free_args)` 按 purpose 返回脚本化结果）或经 `read_manager` 注入 mock LLM 插件
- [x] 5.2 `generalize` 正向：多节点 → 调 `generalize` purpose、返回概括文本；边界：节点不存在跳过、空入参返回提示、material 超 T 截断（小 T 验证）、LLM 解析失败隔离为 `[error]`、经 worker 线程只读（断言不触发写/守门/裂变）；**估算==投喂**：断言 FakeLLMPlugin 收到的 `free_args["material"]`（即 prompt `{material}`）与截断时估算的 material 串**逐字相同**
- [x] 5.3 `arbitrate` 正向：互斥事实 + 事件 → 调 `adjudicate` purpose、返回「采信 [id:X] + 理由」、反查了 `get_related_events`；边界：无背书事件仍裁决、**事件过多 T 截断的轮转公平性**（多事实 + 小 T，验证不把某事实事件全削光、每事实至少留 1 条直至各事实均剩 1 条）、幻觉 id 过滤、**采纳 id 全过滤后返回「无有效采纳方」+ 理由**、事实不存在跳过、LLM 解析失败隔离、经 worker 线程只读、裁决结果不写回图；**估算==投喂**：断言喂 LLM 的 material 与截断估算串逐字相同
- [x] 5.4 `events_per_fact` 参数覆盖：`ToolsetConfig.params={"arbitrate": {"events_per_fact": 1}}` 生效（合并口径 `params` 覆盖）
- [x] 5.5 `tests/test_agent_tools.py`：默认工具集含 7 个 schema（ generalize/arbitrate 在内）；禁用其一不暴露；分发到 `memory.generalize` / `memory.arbitrate`（mock）；`test_agent_loop.py` / `test_agent_trace.py` 的 mock 工具集补齐两新工具名（测调度而非实现）

## 6. 文档（docs/memory-agent.md）

- [x] 6.1 「5 个导航工具」标题 / 段落改为「7 个（含 generalize / arbitrate 两类只读语义判断）」；工具表加两行（参数 / 作用 / 状态✓）
- [x] 6.2 补一节说明：generalize / arbitrate 是**只读 LLM 判断工具**（调 MCS LLM 插件、不改图）；仲裁反查背书事件 + T 守门素材截断；工具返回带 `[id:...]` 供链式引用

## 7. 验证

- [x] 7.1 `openspec validate agent-generalize-arbitrate --strict` 通过
- [x] 7.2 `.venv\Scripts\python.exe -m pytest tests/test_agent_memory.py tests/test_agent_tools.py tests/test_agent_loop.py tests/test_agent_trace.py -q` 通过
- [x] 7.3 回归：`.venv\Scripts\python.exe -m pytest -q` 全量不退化（两新工具为增量、不改既有行为）
