# memory-agent Delta

> migration-audit-fixes：补齐 agent 时代 multi-universe 完整性（A1 learn work_id 透传 / A2 arbitrate
> universe / A3 recall universe / A4 render universe）+ 同步 retire-framework 退役收尾（F1 associate
> 签名）。全部向后兼容（可选参数扩展，老调用零改动）。

## MODIFIED Requirements

### Requirement: 记忆工具集（导航 / 时间线视图 / 语义判断 / 概念重组 / 跨 universe）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航 / 时间线视图 / 语义判断 / 概念重组 / 跨 universe 工具集，**默认 12 个**（learn / search / associate / reason / recall / timeline / generalize / arbitrate / **split** / **merge** / get_cross_universe_edges / **link_cross_universe**），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用 / 禁用子集、覆盖参数：

- `learn(text, work_id?)` → `memory.learn`（`work_id` 非空时本次写入归该作品 universe、触发阶段 ③b 作品叙事事件抽取；省略 / None = 现实 universe，默认行为不变）
- `search(query, mode)` → `memory.search`
- `associate(seed_id, limit?)` → `memory.associate`（一跳邻居纯图读，`limit` 截断默认 60；原 `mode="mcs"` 已随读查询管线退役删除）
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit, universe?)` → `memory.recall`（`universe` 默认 `__reality__`，限该 universe 事件近期倒排；查作品世界时传作品名，与 timeline 同口径——跨 universe 时间不可比）
- `timeline(universe, limit?)` → `memory.timeline`（叙事时间线：某 universe 事件层按时间**升序**组装的只读虚拟视图、不落图）
- `generalize(node_ids, focus?)` → `memory.generalize`（归纳概括：LLM 概括若干节点的公共上位概念）
- `arbitrate(node_ids, question)` → `memory.arbitrate`（互斥裁决：反查背书事件、LLM 裁决采信方 + 理由）
- `split(node_id, focus?)` → `memory.split_concept`（概念拆分：LLM 判耦合 + 产方案 + 执行改图）
- `merge(node_ids, focus?)` → `memory.merge_concepts`（概念合并：LLM 判同义 + 产方案 + 执行改图）
- `get_cross_universe_edges(node_id, limit?)` → `memory.get_cross_universe_edges`（跨 universe 桥定向查：只读、绕载重，列出对端 universe 不同的关联 / 互斥边）
- `link_cross_universe(source_id, target_id)` → `memory.link_cross_universe`（建跨 universe 概念桥：写图、唯一创建路径，两端 universe 必须不同）

导航 / 判断 / 重组决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点找路径、**对哪几个节点归纳 / 仲裁 / 拆分 / 合并**。`generalize` / `arbitrate` 是**只读**语义判断工具（调 MCS 的 LLM 插件、不改图、不触发写 / 守门 / 裂变）；`learn` / `split` / `merge` / `link_cross_universe` 是**写图**工具——`ToolSpec.readonly=False`，自动排除出只读召回（`/recall` 白名单），保"召回 MUST NOT 写图"铁律。**新增写图工具 MUST 标 `readonly=False`**，否则被静默放进只读召回、破坏铁律。

`split` / `merge` 主 LLM 只给 `node_id(s) + focus`，拆分 / 合并方案由专用 purpose（`split` / `merge`）产出、`MemoryStore` 执行（同 `generalize` / `arbitrate` 模式，唯一区别是改图）。

#### Scenario: 默认暴露全部 12 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 12 个内置工具（learn / search / associate / reason / recall / timeline / generalize / arbitrate / split / merge / get_cross_universe_edges / link_cross_universe）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall / timeline / generalize / arbitrate / split_concept / merge_concepts / get_cross_universe_edges / link_cross_universe）

#### Scenario: 写图工具标 readonly=False

- **WHEN** 审查 `BUILTIN_TOOLS` 中 `learn` / `split` / `merge` / `link_cross_universe` 的 `ToolSpec`
- **THEN** 四者 `readonly` MUST 为 `False`
- **AND** `READONLY_TOOL_NAMES` MUST NOT 含 `learn` / `split` / `merge` / `link_cross_universe`（只读召回白名单排除它们）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用 `split`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（如 `{"reason": {"max_hops": 8}}` 或 `{"arbitrate": {"events_per_fact": 3}}`，key = 工具名）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）
- **AND** `params` 与 LLM 入参同名时 MUST 以 `params` 为准（合并口径 `handler(memory, {**llm_args, **params})`）

#### Scenario: learn 工具的 work_id 透传

- **WHEN** LLM 调用 `learn` 工具且 `arguments` 含 `work_id`（如作品文本摄入）
- **THEN** dispatch MUST 经 `memory.learn(text, work_id=work_id)` 透传（非空 → 触发 ③b 作品叙事事件抽取；省略 → 现实 universe 默认行为）
- **AND** `BUILTIN_TOOLS["learn"]` schema 的 `parameters.properties` MUST 含可选 `work_id` 字段（`required` 仍仅 `["text"]`）

#### Scenario: recall 工具的 universe 透传

- **WHEN** LLM 调用 `recall` 工具且 `arguments` 含 `universe`
- **THEN** dispatch MUST 经 `memory.recall(limit, universe)` 透传；省略 `universe` 时默认 `__reality__`
- **AND** `BUILTIN_TOOLS["recall"]` schema 的 `parameters.properties` MUST 含可选 `universe` 字段（`required` 为 `[]`）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

---

### Requirement: 工具返回携带节点 id

`search` / `associate` / `find_path` 的返回文本 SHALL 包含节点 id，使 LLM 能在后续工具调用中引用具体节点。多 universe 库下，非现实 universe（`universe != __reality__`）节点 SHALL 在 id 后、name 前显式标注 `[universe:xxx]`，使 LLM 能判断 `timeline` 取哪个世界、是否需 `link_cross_universe`（两端 universe 必须不同护栏）；现实 universe（`__reality__`）节点 MUST NOT 标注（避免单 universe 仓库噪音）。

#### Scenario: 返回含 id

- **WHEN** search / associate / find_path 返回节点
- **THEN** 文本 MUST 含可被 LLM 提取的节点 id（如 `[id:...]`）

#### Scenario: 非现实 universe 节点标注归属

- **WHEN** 返回的节点列表含 `universe != __reality__` 的节点
- **THEN** 该节点渲染行 MUST 在 `[id:...]` 后、name 前含 `[universe:xxx]` 标签
- **AND** `universe == __reality__` 的节点渲染行 MUST NOT 含 `[universe:__reality__]`（避免噪音）

---

### Requirement: learn 原语（写入）

`MemoryStore.learn(text, work_id=None)` SHALL 封装 MCS 写管线 `ingest`，返回写入状态摘要。`work_id` 非空时 SHALL 走 `mcs.ingest(IngestInput(content=text, work_id=work_id))`（经 universe 注册表规范化 target_universe、触发阶段 ③b `extract_work_events` 抽取作品纪年叙事事件；摄入行为事件 universe 仍固定 `__reality__`——载重命根）；`work_id` 省略 / None / 空串时 SHALL 走原 `mcs.ingest(text)`（str 归一化 = 现实 universe、时间 now、不触发 ③b，与现状逐字一致）。

#### Scenario: learn 即 ingest

- **WHEN** 调用 `learn(text)`
- **THEN** MUST 在 worker 线程执行 `mcs.ingest(text)` 并返回状态摘要

#### Scenario: learn 透传 work_id 触发 ③b

- **WHEN** 调用 `learn(text, work_id="三国演义")`
- **THEN** MUST 在 worker 线程执行 `mcs.ingest(IngestInput(content=text, work_id="三国演义"))`
- **AND** `ctx.target_universe` MUST 经 universe 注册表规范化为 `"三国演义"`（命中复用 / 未命中新建 universe 元节点）
- **AND** 阶段 ③b `extract_work_events` MUST 被触发（LLM 抽取带纪年的作品叙事事件 → `WorkEventDraft` → 作品 universe 事件节点）
- **AND** 摄入行为事件（阶段 ⓪）的 universe MUST 仍为 `__reality__`（载重命根：摄入行为固定现实）

#### Scenario: work_id 省略 / None / 空串等价默认

- **WHEN** 调用 `learn(text)` / `learn(text, work_id=None)` / `learn(text, work_id="")`
- **THEN** 行为 MUST 逐字一致（走 `mcs.ingest(text)`、`target_universe=__reality__`、不触发 ③b）

---

### Requirement: recall 原语（热点回忆）

`MemoryStore.recall(limit, universe=REALITY_UNIVERSE)` SHALL 返回**指定 universe 内**最近发生的事件：扫该 universe 的 `node_class=事件` 节点（`n.universe == universe`），按 `extensions.event_meta.timestamp` 时间倒排（无 timestamp 者排末尾、`node.id` 作次级键保确定性），**全文渲染**为含节点 id 的 LLM 可读文本（name==content 只写一份、每条附 timestamp；非现实 universe 时行含 `[universe:xxx]` 标签）；该 universe 无事件时返回空提示。排序口径为**纯近期时间线**——事件节点无专门「热度」字段，不掺热度加权。截断为**条数 `limit` 与 token 上界 T 双约束**：逐条判定，达 `limit` 条、或「纳入该条后的完整渲染文本」超 `token_budget.T` 即停（先到先停；对完整文本**整体估算**、含 header 与行间换行符，渲染口径 == 估算口径，禁止分段累加单条 estimate）；唯一例外是**最近 1 条无条件全文返回**（即使其单条就超 T）。recall 为只读原语、不经 LLM、不进核心活跃视图、不触发写 / 守门 / 裂变。

> 单 universe 独立时间轴：默认 `__reality__`（现实近期倒排，ISO timestamp）；查作品世界时调用方传 `universe=作品名`（作品纪年 `timestamp_sort_value`）。跨 universe 时间不可比（现实 epoch≈1.78e9 与作品纪年 200 混排无意义）——recall MUST 严格限单 universe。

#### Scenario: 时间倒排返回最近事件

- **WHEN** 图中存在多个带 `event_meta.timestamp` 的事件节点，调用 `recall(limit)`
- **THEN** MUST 按 `timestamp` 倒序（近期在前）返回，至多 `limit` 条
- **AND** 渲染文本 MUST 含每条事件的节点 id（如 `[id:...]`），可被后续工具引用

#### Scenario: 限 universe 过滤（每 universe 独立时间轴）

- **WHEN** 图中同时存在现实 universe（`__reality__`，ISO timestamp）与作品 universe（数字年纪年 timestamp）的事件节点
- **AND** 调用 `recall(limit)` 不传 `universe` 或传 `universe=__reality__`
- **THEN** MUST 仅返回 `universe == __reality__` 的事件
- **AND** MUST NOT 含作品 universe 事件（防 ISO epoch 与数字年纪年混排）

#### Scenario: 显式 universe 取作品世界

- **WHEN** 调用 `recall(limit, universe="三国演义")`
- **THEN** MUST 仅返回 `universe == "三国演义"` 的事件
- **AND** MUST NOT 含现实或其他作品 universe 事件

#### Scenario: 无 timestamp 排末尾

- **WHEN** 部分事件节点无 `event_meta.timestamp`
- **THEN** 这些事件 MUST 排在有 timestamp 的事件之后（末尾）

#### Scenario: limit 截断

- **WHEN** 事件数超过 `limit`
- **THEN** MUST 仅返回 `limit` 条（最近的那批）

#### Scenario: token 预算截断（不超 T）

- **WHEN** 纳入下一条后的完整渲染文本 token 将超过 `token_budget.T`
- **THEN** MUST 停止纳入更早事件，返回的渲染文本总 token MUST ≤ T
- **AND** 截断 MUST 为 `limit` 与 T 双上界、先到先停

#### Scenario: 单条超 T 至少返回最近 1 条

- **WHEN** 最近一条事件全文渲染就超过 T
- **THEN** MUST 仍完整返回该最近 1 条（全文、不截断正文、不返回空）
- **AND** 其余更早事件 MUST 严格受 T 约束

#### Scenario: 同 timestamp 确定性次序

- **WHEN** 多个事件 `timestamp` 相同
- **THEN** 其相对次序 MUST 确定（不依赖存储遍历顺序），便于测试稳定

#### Scenario: 无事件返回空提示

- **WHEN** 该 universe 无任何 `node_class=事件` 节点
- **THEN** MUST 返回空提示文本，MUST NOT 伪造事件、MUST NOT 跨 universe 拉事件凑数

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `recall`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_nodes_by_class(CLASS_EVENT)` 后按 `n.universe == universe` 过滤，MUST NOT 触发写 / 守门 / 裂变

---

### Requirement: arbitrate 原语（互斥裁决）

`MemoryStore.arbitrate(node_ids, question)` SHALL 经单 worker 线程对给定**互斥事实**做只读裁决：①取 `node_ids` 对应事实节点 → ②对每个事实经 `store.get_related_events(fact_id, universe=U, limit=K)` **定向反查**其背书事件（`U` 取互斥事实同 universe——invariant，派生自首事实 `facts[0].universe`；任一事实跨 universe 发 warning 仍按首事实 universe 反查；时间倒排、绕载重规则、取最近 K 条、K 可经 `ToolsetConfig.params["arbitrate"]["events_per_fact"]` 覆盖）→ ③**自建装配**「各事实全文 + 其背书事件行」material（事件复用**行级** `_render_event_line` 口径、带 timestamp；MUST NOT 套整函数 `_render_events`——其 recall 专属 header 对每事实重复将语义错位）→ ④**素材 T 有界截断**（守门）→ ⑤经 `adjudicate` purpose 调 MCS 的 LLM 插件裁决**采信方 + 理由**（material 经 `free_args["material"]` 显式传）→ ⑥过滤幻觉 id（只保留传入事实 id）→ 返回「采信 [id:...] + 理由」文本。`arbitrate` 为**只读**原语：不改图、不写裁决结果、不触发写 / 守门 / 裂变。

#### Scenario: 裁决互斥事实返回采纳方与理由

- **WHEN** 传入多个互斥事实 id + 问题
- **THEN** MUST 反查各事实背书事件、经 `adjudicate` purpose 调 LLM，返回「采信哪个事实 + 理由」文本
- **AND** 返回文本 MUST 含被采信事实的节点 id（如 `[id:...]`）

#### Scenario: 反查背书事件限同 universe

- **WHEN** 裁决某互斥事实
- **THEN** MUST 经 `store.get_related_events(fact_id, universe=U, limit=K)` 取该事实的背书事件（`U = facts[0].universe`、时间倒排、最近 K 条）
- **AND** 反查事件 MUST 限同 universe（MUST NOT 含跨 universe 事件进裁决 material——保载重命根 / 单 universe 时间轴封闭）
- **AND** 事件素材 MUST 含 timestamp、复用行级 `_render_event_line` 渲染口径（MUST NOT 套整函数 `_render_events`，见 requirement 正文 ③）

#### Scenario: 跨 universe 事实 warning 仍按首事实反查

- **WHEN** 传入的事实 `node_ids` 中存在 `universe != facts[0].universe` 的成员（互斥前提已破）
- **THEN** MUST 发 warning、仍按首事实 universe 反查事件（MUST NOT 抛异常、MUST NOT 拒整个裁决）

#### Scenario: 无背书事件仍可裁决

- **WHEN** 某事实无背书事件（`get_related_events` 返回空）
- **THEN** MUST 仅据事实本身裁决（不抛、不伪造事件）

#### Scenario: 事件过多 T 截断（守门，多事实公平）

- **WHEN** 「事实 + 事件」完整 material token 超过 `token_budget.T`
- **THEN** MUST 按**轮转保底**逐条丢事件至 material ≤ T：每轮在「当前剩余事件数最多的事实」里丢其**最旧一条**（并列取 id 序最大者），且**每事实至少保留 1 条事件**，直至各事实均剩 1 条后方继续轮转丢至 0 条
- **AND** MUST NOT 单纯按全局时间戳丢更旧事件（会把某事实事件全削光、致证据失衡与裁决偏置）
- **AND** 截断 MUST 对完整 material 文本整体估算（估算口径 == 渲染口径，禁止分段累加单行 estimate）
- **AND** 事实本身（零事件）超 T 时仍 MUST 至少渲染所有事实全文（裁决核心是判事实）

#### Scenario: 幻觉 id 过滤

- **WHEN** LLM 返回的采纳 id 不在传入事实 id 集合内
- **THEN** 该 id MUST 被过滤掉（MUST NOT 把图中不相关 / 不存在的节点当成采纳方）

#### Scenario: 采纳 id 全被过滤（无有效采纳方）

- **WHEN** LLM 返回的采纳 id 经过滤后为空（全是幻觉 / 不存在 id）
- **THEN** MUST 仍返回 LLM 的理由文本 + 明示「无有效采纳方」（MUST NOT 抛异常、MUST NOT 把图中不相关节点伪造为采纳方）

#### Scenario: 事实节点不存在

- **WHEN** `node_ids` 含不存在的事实 id
- **THEN** 不存在的 id MUST 被跳过（不抛）；全部不存在时 MUST 返回提示文本（MUST NOT 伪造裁决）

#### Scenario: 经 worker 线程只读

- **WHEN** 调用 `arbitrate`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 只读 `store.get_node` / `get_related_events` + LLM 插件，MUST NOT 触发写 / 守门 / 裂变、MUST NOT 把裁决结果写回图

---

### Requirement: MemoryStore 结构化 ingest 原语

`MemoryStore` SHALL 提供 `ingest_structured(content: str, timestamp: str, work_id: str | None = None) -> str`：在单 worker 线程（`_submit`）内执行 `wctx = self._mcs.ingest(IngestInput(content=content, timestamp=timestamp, work_id=work_id))`，返回 `wctx.event_node.id`。该原语用于整合管线把精炼条目逐条入图，事件时间忠实落 `event_meta.timestamp`；`work_id` 非空时归该作品 universe、触发 ③b。调用方线程 MUST NOT 直接触碰 MCS。

> 偏离历史：旧 `personal-memory-system` 设计靠子类化 `MemStore(MemoryStore)` 规避改 `mcs_agent`；现架构"走 agent"，直接在 `MemoryStore` 上新增此原语，无需子类。原有 `learn(text, work_id=None)`（只收 str、时间盖 now）保留。

#### Scenario: 结构化 ingest 落事件时间

- **WHEN** 调用 `ingest_structured("今天和团队讨论了新方案", "2026-06-27T14:30:00")`
- **THEN** MUST 在 worker 线程内 `mcs.ingest(IngestInput(content=..., timestamp="2026-06-27T14:30:00"))`
- **AND** 返回的事件节点 `event_meta.timestamp` MUST 为 `2026-06-27T14:30:00`（非调用时刻）
- **AND** MUST 返回该事件节点 id

#### Scenario: 结构化 ingest 透传 work_id

- **WHEN** 调用 `ingest_structured(content, timestamp, work_id="三国演义")`
- **THEN** MUST 在 worker 线程内 `mcs.ingest(IngestInput(content=..., timestamp=..., work_id="三国演义"))`
- **AND** `ctx.target_universe` MUST 经 universe 注册表规范化为 `"三国演义"`、阶段 ③b MUST 被触发

#### Scenario: 经单 worker 线程

- **WHEN** 调用 `ingest_structured`
- **THEN** MUST 经 `_submit` 排入单 worker 线程执行（调用方线程 MUST NOT 直接触碰 MCS）
