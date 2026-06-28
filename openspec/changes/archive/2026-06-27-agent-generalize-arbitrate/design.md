## Context

记忆 agent 现有 5 个工具：4 个**纯读导航**（search / associate / reason / recall）+ 1 个**整段写入**（learn）。导航工具都是对 MCS 能力的薄封装、**不调 LLM**（search/associate/reason/recall 是 store 检索 + 渲染；learn 复用写管线）。缺一类「**对已捞到的若干节点做语义判断**」的只读工具——归纳（共性 / 公共上位概念）与仲裁（互斥事实谁对）。

关键现状（探查所得）：

- **`llm_caller` 就是 LLM 插件的 `.call` 方法**（`mcs/interfaces/llm.py:113`，`call(purpose, nodes_in, free_args) -> 解析结果`）；写 / 查管线把它线程化传给插件（如 `write_pipeline.py:611` 传 `self.llm.call`）。LLM 插件注册在 `PluginManager`，MCS 公开暴露 `read_manager` / `write_manager`（`mcs.py:52-53`），`run_maintenance` 已示范 `manager.get_all(PluginType.X)`（`mcs.py:101`）——**MemoryStore 可经 `mcs.read_manager.get_all(PluginType.LLM)` 拿到（单实例）LLM 插件、直接调 `.call`**。与 `learn` / `associate` 在 worker 线程触发 LLM 是同一既定模式。
- **既有提示词无一适配**：`synthesize` 是「按 query 合成答案」（查询阶段⑤、非找共性）；`decide_hub` 是「中心+子节点→多社区划分」（写入阶段⑥、结构过重）；`arbitrate` purpose 是「按 query 从候选选自洽子集」、**只返回 `list[str]`（无理由）、也不吃事件**（`mcs/prompts/arbitrate.py`）。故归纳 / 仲裁各需新 purpose。
- **事件反查原语就绪**：`StoreInterface.get_related_events(node_id, limit=None)`（`mcs/core/store.py:133`、QueryEngine + 两 store 都有）是**命题→事件的定向查**——绕过载重规则、时间倒排 + limit、不进常驻活跃视图。recall 已有 `_render_events` 的事件渲染口径 + 「对完整文本整体估算」的 T 截断纪律（`memory.py`）。
- **token 预算**：`query_engine.token_budget`（`.T` + `.estimate`），recall 已只读消费。
- **线程模型**：所有原语经 `_submit` 单 worker 线程（SQLite 亲和铁律）；LLM-in-worker-thread 已是既定（learn/associate 经 MCS 管线在 worker 线程调 LLM）。

约束：两工具**只读**、不改图、不触发写 / 守门 / 裂变；handler 保持 `(memory, args) -> str` 纯薄封装（trace / 异常隔离留在 `_dispatch`，见 recall design D5）；不动 `mcs/core` 逻辑。

## Goals / Non-Goals

**Goals:**

- `generalize(node_ids, focus?)`：N 个概念节点 → 新 purpose `generalize` → LLM 概括公共上位概念 → 文本；只读、输入素材 T 有界。
- `arbitrate(node_ids, question)`：N 个互斥事实 + 问题 → 反查每个事实的背书事件（`get_related_events`，最近 K 条）→ 组装「事实 + 事件」素材、T 有界截断 → 新 purpose `adjudicate` → LLM 裁决采信方 + 理由 → 文本；只读。
- 仲裁的「守门」= 读侧素材 T 有界 + 截断策略（事件过多时丢更早事件至 ≤ T，估算==渲染口径），**非写入期守门 / 裂变**。

**Non-Goals:**

- 不改图、不写裁决结果回图（裁决是建议性只读结论，非永久解决互斥）。
- 不做向上遍历 / LCA（归纳是 LLM 概括，非找现成祖先——MCS 无向上层级）。
- 归纳不做事件反查（概念节点，聚焦共性理解）。
- 不动 `mcs/core` 逻辑、不动写 / 查管线、不动存储；不把仲裁接入查询管线阶段④（它是 agent 工具，非查询 stage）。
- 不动共享 `arbitrate` purpose（新增 `adjudicate`、零侵入）。

## Decisions

### D1. 两工具均只读 → 不变量零影响

归纳 / 仲裁纯读 `store.get_node` / `get_related_events` + 调 LLM，不调任何 `add_node` / `add_edge` / `update_node`。

- **后果**：不触发写入期守门 / 裂变；铁律一（活跃视图 ≤ T）不受影响——仲裁虽反查事件，但用定向 `get_related_events`（绕载重规则的独立检索步、不进常驻活跃视图），T 截断的是**工具喂 LLM 的素材**而非活跃视图渲染。
- **Alt considered**：写入版（建 hub / 写裁决状态——拒——碰守门、改图、风险面大，用户已确认只读）。

### D2. LLM 来源 = MCS 的 LLM 插件（非 agent chat LLM）

MemoryStore 经 `self._mcs.read_manager.get_all(PluginType.LLM)` 取（单实例）LLM 插件、调 `plugin.call(purpose, nodes_in=[...], free_args={...})`。

- **理由**：与 `learn`（MCS 写 LLM 抽概念）/ `associate`（MCS 读 LLM 选事实）一致——「MCS 操作用 MCS 的 LLM」是既定模式；handler 仍是 `(memory, args) -> str` 纯薄封装，trace / 异常隔离留在 `_dispatch`，不破坏 recall design D5。
- **Alt considered**：用 agent chat LLM（`self.llm`）——拒——它在 `MemoryAgent`/loop、不在 MemoryStore；要用就得改 handler 签名或把 agent LLM 线程进 MemoryStore，破坏「handler 纯、导航决策权在 LLM」分层，且 agent chat LLM 与 MCS LLM 是两套（统一 provider 下同模型但不同调用面）。

### D3. 新增 2 个 purpose（`generalize` / `adjudicate`），不复用既有

- `generalize`：输入 N 节点 → 输出公共上位概念短文本。**不**复用 `synthesize`（按 query 合成答案、语义不符）、**不**复用 `decide_hub`（社区划分 + 结构化 `MultiHubDecision`、过重）。
- `adjudicate`：输入互斥事实 + 背书事件 + 问题 → 输出 `{采纳节点 id, 理由}`。**不**复用现有 `arbitrate` purpose——它只返 `list[str]`（无理由）、不吃事件、语义是「按 query 选自洽子集」（查询管线用）。新增 `adjudicate` 零侵入共享提示词。
- **注册**：`mcs/prompts/__init__.py` 的 `DEFAULT_PROMPTS` 加两条（同 `decide_hub` / `arbitrate` 注册方式）。

### D4. 仲裁反查事件用 `get_related_events`（定向查、绕载重规则）

对每个互斥事实 id，`store.get_related_events(fact_id, limit=K)` 取**最近 K 条背书事件**（时间倒排）。

- **理由**：这是命题→事件的**定向查**——绕过载重规则（核心侧 `get_relations` 已过滤事件边）、不进常驻活跃视图、时间倒排 + limit 天然支持「最近」语义；正是「需要出处 / 证据」的既定路径（store.py:134 docstring）。
- **Alt considered**：`get_relations`（拒——载重规则下核心侧已过滤事件边、查不到）；`get_all_nodes()` 全扫过滤事件（拒——昂贵、非定向、无「背书此事实」关联）。

### D5. 仲裁「守门」= 读侧素材 T 有界 + 截断策略（估算==渲染口径）

组装素材 = 各互斥事实全文 + 各自最近 K 条事件。事件**复用行级渲染 `_render_event_line`**（带 timestamp、name==content 去重），**不套整函数 `_render_events`**——后者会写 recall 专属常量 header「最近发生的事件（时间倒排）」，对每事实重复一次将出现多段错位 header，语义不符仲裁；故 arbitrate **自建素材装配**（每事实块：事实全文 + 其事件行），对装配后的整串估算。`K` 默认保守（如 3），可经 `ToolsetConfig.params` 覆盖。

- **估算口径 == 渲染口径（同 recall D8 纪律）**：对**装配出的同一完整素材文本**（即喂 prompt `{material}` 的那串）整体 `tb.estimate(material)`，**禁止**分段累加单行 estimate——会漏 join 分隔符、系统性低估、致超 T。同样**禁止**套 `TokenBudget.estimate_node`（守门口径、字段不同）。
- **截断顺序（多事实公平）**：若「完整素材」token 超 `token_budget.T`，按**轮转保底**逐条丢事件至 ≤ T——每轮在「当前剩余事件数最多的事实」里丢其**最旧一条**（并列时取 id 序最大者，保确定性），**每事实至少保留 1 条事件**（除非该事实全文本身已逼近 T，见下）。**禁止**单纯按全局时间戳丢——会把某事实事件全削光、另一事实满 K 条，证据失衡致裁决系统性偏向证据未被削方。
- **边界**：① 各事实保 1 条后仍超 T，则继续轮转丢至每事实 0 条事件（仅留事实全文）；② 事实全文本身（零事件）就超 T 时，仍**至少渲染所有事实全文**（仲裁核心是判事实，残缺事实无意义），事件全丢光不影响事实裁决。
- **Alt considered**：只硬截事件条数 K（拒——事实本身大时总 token 仍超 T，未真正有界）；累加单行 estimate（拒——recall 教训）；单纯全局最旧截断（拒——多事实证据失衡，见上）。

### D6. 裁决输出含理由（结构化 `{采纳, 理由}`）

`adjudicate` purpose 的 LLM 返回结构化 JSON `{adopt: [id...], reason: "..."}`（或 `{winner: id, reason}`），`parse` 解析 + 幻觉 id 过滤（只保留传入事实 id）；工具渲染为「采信 [id:X]（...），理由：...」。

- **理由**：用户明确「理由包进去」；结构化便于解析可靠 + 过滤幻觉 id（同 `decide_hub.validate_and_repair` 思路）。**幻觉 id 过滤在 `_do_arbitrate` 层做**（`parse` 不知传入 id 集合，只解析结构）。
- **边界（全过滤为空）**：若过滤后 `adopt` 为空（LLM 只给了幻觉 / 不存在的 id），工具**仍返回理由文本 + 明示「无有效采纳方」**——不抛、不崩、不把图中不相关节点伪造为采纳方。理由对 agent 仍有参考价值。
- **Alt considered**：自由文本裁决（拒——难稳定提取采纳方 id）。

### D7. 归纳输入同样 T 有界（防爆 LLM 上下文）

`generalize` 把 N 节点渲染进 material；若超 T，按序丢尾节点至 ≤ T（归纳是「理解这些概念」，节点过多时取靠前 / 相关的，诚实提示截断）。口径简单于仲裁（无事件反查）。

- **material 必须显式传入 free_args（估算 == 投喂同源）**：用 `_render_nodes` 建好 material 后，MUST 经 `free_args={"focus": ..., "material": material}` 显式传给 `llm.call`（`call` 内对 `material` 用 `setdefault`，显式值不被覆盖）。**禁止**只传 `nodes_in=nodes` 而让 `llm.call` 内部经 `ContextRenderer.render(nodes, "generalize")` 自渲染——那条路径的渲染格式与 `_render_nodes` 不同、且会附加 NODE_EXTENSION 片段（summary / event_meta 等），导致「截断估算串 ≠ 实际投喂串」、且常态偏长可能反超 T（与 arbitrate 显式传 material 同一纪律）。`nodes_in` 可传 `[]`（material 已自带 id），或仅供 `_emit_record` 的 `n_nodes` 可观测。

### D8. 经 `_submit` worker 线程（同所有原语）

两原语都 `xxx() -> _submit(_do_xxx, ...)`；LLM 调用在 worker 线程内（同 learn / associate——它们经 MCS 管线在 worker 线程触发 LLM）。调用方线程不触碰 MCS / store / LLM 插件（线程安全铁律）。

### D9. 命名：工具 `generalize` / `arbitrate`，purpose `generalize` / `adjudicate`

工具名（对 LLM）= `generalize` / `arbitrate`（与现有英文工具名一致；`arbitrate` 工具名与查询管线的 `arbitrate` purpose 同名但**不同域**——前者 agent dispatch key、后者 LLM prompt purpose——技术上不冲突）。仲裁工具内部用新 purpose `adjudicate`（不动共享 `arbitrate` purpose，见 D3）。

- **可读性 footgun（须落注释）**：工具 `arbitrate` 内部走 purpose `adjudicate`，而库里另存在用途不同的 `arbitrate` purpose（查询管线 `LLMArbitrationPlugin`、只返 `list[str]`）。二者命名空间隔离、不会真冲突，但易混。`tools.py` 的 handler / `ToolSpec` 与 `docs/memory-agent.md` MUST 显著注明「本工具内部 purpose = `adjudicate`，与查询管线的 `arbitrate` purpose 无关」，避免后续维护误改。
- **Alt considered**：工具也命名 `adjudicate`（与 generalize 工具名==purpose 名对称）——拒，`arbitrate` 对 LLM 更直觉；改以注释消歧。

## Risks / Trade-offs

- **[LLM 插件检索]** `read_manager.get_all(PluginType.LLM)` 假设恰好 1 个（共享）LLM 插件。→ Mitigation：取首个；若 0（未配 LLM）返回 `[error] 无可用 LLM`，不崩。LLM 插件经 `register_shared_plugin` 注册到两侧，read_manager 恒有。
- **[T 截断口径失准]** 估算与实际喂 LLM 的 material 不一致会致超 T 或漏截。→ Mitigation：估算**构建出的同一 material 字符串**（喂 prompt `{material}` 的那个），复用 recall D8 纪律；测试用小 T 验证截断。
- **[事件 K 调参]** 每事实默认 K 是猜测。→ Mitigation：`ToolsetConfig.params` 覆盖（如 `{"arbitrate": {"events_per_fact": 3}}`），默认保守。
- **[裁决正确性]** LLM 可能选错事实。→ Mitigation：只读建议性结论 + 附理由，最终答复由 agent / LLM 综合判断；非永久解决互斥。文档注明「advisory」。
- **[默认工具集 5→7]** 现有 agent 自动多两工具。→ Mitigation：增量、非破坏；`ToolsetConfig.enabled` 仍可排除任一（既有契约）。

## Migration Plan

- 无数据 / 配置迁移。新增两工具 + 两 purpose，纯增量。
- 默认工具集 5→7：现有 agent 自动获得两新工具（增量、非破坏）；想保持 5 个的用 `ToolsetConfig(enabled=[...])` 显式指定。
- 回滚：删 `mcs_agent/{tools,memory,loop}.py` 的两工具 / 原语 / prompt 行 + `mcs/prompts/{generalize,adjudicate}.py` + 注册两行即可。

## Open Questions

- 归纳是否也该拉取每个概念的邻域上下文（而非只概念节点本身）？当前只节点本身，聚焦共性理解；待用。
- `adjudicate` 输出结构（`{adopt: [ids]}` 多选 vs `{winner: id}` 单选）——倾向 `adopt` 列表（允许「多个都对 / 都保留」+ 单选作特例）。
- 仲裁是否处理「非互斥但冲突」的输入（任意若干事实）？当前面向互斥事实，但 LLM 可判任意提供的事实，语义不硬卡互斥——待用。
