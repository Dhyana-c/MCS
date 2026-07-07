## MODIFIED Requirements

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航 / 语义判断 / 概念重组工具集，**默认 9 个**（learn / search / associate / reason / recall / generalize / arbitrate / **split** / **merge**），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用 / 禁用子集、覆盖参数：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`
- `generalize(node_ids, focus?)` → `memory.generalize`（归纳概括：LLM 概括若干节点的公共上位概念）
- `arbitrate(node_ids, question)` → `memory.arbitrate`（互斥裁决：反查背书事件、LLM 裁决采信方 + 理由）
- `split(node_id, focus?)` → `memory.split_concept`（概念拆分：LLM 判耦合 + 产方案 + 执行改图）
- `merge(node_ids, focus?)` → `memory.merge_concepts`（概念合并：LLM 判同义 + 产方案 + 执行改图）

导航 / 判断 / 重组决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点找路径、**对哪几个节点归纳 / 仲裁 / 拆分 / 合并**。`generalize` / `arbitrate` 是**只读**语义判断工具（调 MCS 的 LLM 插件、不改图、不触发写 / 守门 / 裂变）；`learn` / `split` / `merge` 是**写图**工具——`ToolSpec.readonly=False`，自动排除出只读召回（`/recall` 白名单），保"召回 MUST NOT 写图"铁律。**新增写图工具 MUST 标 `readonly=False`**，否则被静默放进只读召回、破坏铁律。

`split` / `merge` 主 LLM 只给 `node_id(s) + focus`，拆分 / 合并方案由专用 purpose（`split` / `merge`）产出、`MemoryStore` 执行（同 `generalize` / `arbitrate` 模式，唯一区别是改图）。

#### Scenario: 默认暴露全部 9 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 9 个内置工具（learn / search / associate / reason / recall / generalize / arbitrate / split / merge）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall / generalize / arbitrate / split_concept / merge_concepts）

#### Scenario: 写图工具标 readonly=False

- **WHEN** 审查 `BUILTIN_TOOLS` 中 `learn` / `split` / `merge` 的 `ToolSpec`
- **THEN** 三者 `readonly` MUST 为 `False`
- **AND** `READONLY_TOOL_NAMES` MUST NOT 含 `learn` / `split` / `merge`（只读召回白名单排除它们）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用 `split`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（key = 工具名）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）
- **AND** `params` 与 LLM 入参同名时 MUST 以 `params` 为准（合并口径 `handler(memory, {**llm_args, **params})`）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

---

### Requirement: MemoryStore 单线程包装 MCS

`MemoryStore` SHALL 在单一 worker 线程内构造 MCS 并执行其全部调用（含 `generalize` / `arbitrate` / `split_concept` / `merge_concepts` 的 LLM 调用与改图），规避 MCS 非线程安全与 SQLite 线程亲和。

#### Scenario: 所有 MCS 调用经同一 worker 线程

- **WHEN** 多次并发调用 MemoryStore 的任一原语（learn / search / associate / find_path / recall / generalize / arbitrate / split_concept / merge_concepts）
- **THEN** 每次 MUST 经 `ThreadPoolExecutor(max_workers=1)` 串行执行
- **AND** 调用方线程 MUST NOT 直接触碰 MCS 实例（含 store 与 LLM 插件）

#### Scenario: 原语返回 LLM 可读文本

- **WHEN** 调用任一 MemoryStore 原语
- **THEN** MUST 在 worker 线程内执行对应 MCS 调用并返回 LLM 可读文本（含节点 id）

---

## ADDED Requirements

### Requirement: split 原语（概念拆分）

`MemoryStore.split_concept(node_id, focus=None)` SHALL 经单 worker 线程拆分一个**粒度耦合**的概念节点：①取 `node_id` 对应节点（不存在返回提示、不抛）→ ②加载其全部原边（`get_relations` 取 `关联` / `互斥`；`get_related_events` 取事件背书）→ ③自建 material（节点 content + 原边含对端 name，**不截断**——T 约束查询活跃视图 / 累积预算、非 LLM 单次 context，全部原边远在 context 内，截断会丢边、破坏后续边全覆盖校验）→ ④经 `split` purpose 调 MCS 的 LLM 插件判定**是否耦合了多个语义中心**、产出方案（`into[]` 产物 + `relation`（`is_a` / `none`）+ `edges[]` 每条原边归属）；未耦合返回 `action=noop` → ⑤`parse` 校验（`into` 非空、`edges` **覆盖全部原边**、跨关系边由 `role=fact` 产物承接）→ ⑥**原子执行**（`store.snapshot()` → 建 / 改 / 删 node+edge → 失败 `restore`）→ ⑦事件背书边自动迁 `target` 到 `parent`（不交 LLM）→ ⑧经 `self._mcs.run_compaction(产物节点)` 过守门（split 减扇出几乎必过）→ 返回结果文本。`split` 为**写图**原语：组合 store 已有 `add/delete/update` 原语，不动 core schema / 管线 / 铁律。

`delete_node` 连带删关联边——故删原节点前 MUST 先把该迁的边迁走（按 `edges[]` 归属改端点指向产物）。`split` 仅拆**概念节点**（事实带互斥/背书、事件/source 规则入库，拆它们破坏语义——非概念节点拒拆、不调 LLM）。`split` / `merge` 是 agent **显式写操作**（同 `learn`），**不在聚类 fanout 铁律适用范围**（铁律管自动裂变不波及关系边；显式写操作的边重分合法）。组织层级语义：原节点若为 hub（组织中心），parent 产物继承 `hub` 标记；下钻成员的层级由守门 `decide_hub` 重判。

#### Scenario: 拆分类别-特化耦合（is_a）

- **WHEN** 节点 content 把大类与某特化耦合（如"按摩"主要讲泰式特点），调用 `split_concept`
- **THEN** MUST 经 `split` purpose 判出耦合、产出 `relation=is_a` 的拆分方案（如"按摩"parent + "泰式按摩"child）
- **AND** MUST 原子执行：原节点删除、产物节点建立、原边按归属迁移到产物、产物间连 `关联`
- **AND** 返回文本 MUST 含产物节点 id

#### Scenario: 拆分多实体误并（none）

- **WHEN** 节点 content 是多个独立实体被误并（如"小明和小红"），调用 `split_concept`
- **THEN** MUST 产出 `relation=none` 的拆分方案（如"小明" + "小红"，平级、无 is_a）
- **AND** 跨两实体关系的原边（如"两人是夫妻"）MUST 由 `role=fact` 产物承接（谓词落其 content、连两端）

#### Scenario: noop 复核（专用 prompt 判未耦合）

- **WHEN** 专用 prompt 复核后判定节点未耦合多个语义中心（content 自洽）
- **THEN** MUST 返回 `action=noop`、**不执行任何改图**、返回提示文本

#### Scenario: 漏边降级（执行侧透明挂 parent）

- **WHEN** `split` purpose 返回的 `edges[]` 未覆盖全部原边（LLM 偶发漏指某些原边归属）
- **THEN** `_do_split` 执行侧 MUST 把漏指的原边透明挂到 `parent`（无 parent 则首个非 fact 产物）
- **AND** 返回文本 MUST 列出"暂挂"提示（哪些对端的边、暂挂到哪个产物）
- **AND** MUST NOT 抛异常、MUST NOT 拒绝执行（降级优于拒绝：LLM 偶发漏指仍完成拆分，归属下一轮可修）

#### Scenario: 原子回滚

- **WHEN** split 执行过程中任一步失败（如 `add_node` 抛异常）
- **THEN** MUST 经 `store.snapshot()` / `restore()` 回到操作前状态
- **AND** 图 MUST 无部分修改残留（无半拆分节点、无悬空边）

#### Scenario: 事件背书边自动迁移

- **WHEN** 原节点被事件背书（有事件 → 原节点的 `关联` 边）
- **THEN** 这些事件背书边的 `target` MUST 自动迁移到 `parent`（无 parent 则首个非 fact 产物），MUST NOT 交 LLM 决定、MUST NOT 随 `delete_node` 丢失

#### Scenario: 节点不存在

- **WHEN** `node_id` 在图中不存在
- **THEN** MUST 返回提示文本（MUST NOT 抛异常、MUST NOT 调 LLM）

#### Scenario: 经 worker 线程写图

- **WHEN** 调用 `split_concept`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 经 store 的 `add/delete/update` 原语改图、再经 `self._mcs.run_compaction(changed)` 过守门
- **AND** `split` 工具的 `readonly` MUST 为 `False`（不进只读召回白名单）

---

### Requirement: merge 原语（概念合并）

`MemoryStore.merge_concepts(node_ids, focus=None)` SHALL 经单 worker 线程合并若干**本就同一个**的节点：①取 `node_ids` 对应节点（不存在的跳过、全空返回提示）→ ②自建 material（各节点 content + 对端，**不截断**——同 split，T 非 LLM 单次 context 约束）→ ③经 `merge` purpose 调 MCS 的 LLM 插件判定**是否同义 / 重复**、产出方案（`keep` 保留、`absorb[]` 吸收删除、`merged_content`、`aliases_to_add`）；非同义返回 `action=noop` → ④**互斥安全闸**：`keep` 与任一 `absorb` 间若有 `互斥` 边，MUST 拒绝合并（塌缩矛盾）→ ⑤`parse` 校验（`keep` / `absorb` 均在传入 id 集合内、`keep` 不在 `absorb` 中）→ ⑥**原子执行**（`snapshot` → absorb 的关联 / 互斥 / 事件背书边迁向 `keep`、`absorb.name`/`aliases` 并入 `keep.aliases`、absorb 的 `hub` 标记继承到 `keep`、删 absorb 节点 → 失败 `restore`）→ ⑦经 `self._mcs.run_compaction(keep 节点)` 过守门（merge 增扇出，可能触发 `decide_hub` 裂变，由守门既有机制兜）→ 返回结果文本。互斥禁合三闸：`keep`↔`absorb` 互斥（塌缩）、`absorb`↔`absorb` 互斥（塌缩）、`absorb` 带互斥边且 `keep` 非 fact（无法承接、会丢互斥关系）。`merge` 为**写图**原语。不复用 `judge_relations` 的 merge（写入期对齐口径与 agent 手动合并不同）。

#### Scenario: 合并同义节点

- **WHEN** 传入多个同义 / 重复节点 id（如"苹果公司"与"Apple Inc."），调用 `merge_concepts`
- **THEN** MUST 经 `merge` purpose 判同义、产出 `keep` / `absorb` 方案
- **AND** MUST 原子执行：absorb 的边迁向 keep、aliases 并入 keep、absorb 节点删除
- **AND** 返回文本 MUST 含 keep 节点 id

#### Scenario: 互斥禁合（安全闸）

- **WHEN** `keep` 与某 `absorb` 之间存在 `互斥` 边（合并会塌缩矛盾）
- **THEN** 专用 prompt MUST 返回 `action=noop` 并说明；即便 prompt 漏判，机制层执行前 MUST 再扫互斥边、命中即拒绝、不执行改图

#### Scenario: noop（非同义）

- **WHEN** 专用 prompt 判定节点非同义（如同名异义"苹果"水果 vs 公司）
- **THEN** MUST 返回 `action=noop`、不执行改图、返回提示文本

#### Scenario: 增扇出守门

- **WHEN** merge 后 `keep` 的**层级 fanout**（下钻成员视图）超过 `token_budget.T`
- **THEN** MUST 经 `self._mcs.run_compaction(changed)` 过守门（可能触发 `decide_hub` 裂变收敛）
- **AND** 守门只兜**层级 fanout**（`_hierarchy_over_budget`，不含关系边 token）；merge 增的关系边使关系侧超 T 时，由查询渲染期 Phase 2 priority 截断兜（宪法：关系侧不聚类）
- **AND** 守门 / 裂变由 core 写路径既有机制兜，merge 不特殊处理

#### Scenario: 原子回滚

- **WHEN** merge 执行过程中任一步失败
- **THEN** MUST 经 `snapshot` / `restore` 回到操作前状态、无部分修改残留

#### Scenario: 别名收口

- **WHEN** absorb 节点有 `name` / `aliases`
- **THEN** 这些 MUST 并入 `keep.aliases`（异名收口），不丢失

#### Scenario: 节点不存在

- **WHEN** `node_ids` 含不存在的 id
- **THEN** 不存在的 id MUST 被跳过（不抛）；全部不存在或仅 1 个有效时 MUST 返回提示文本（MUST NOT 调 LLM、MUST NOT 改图）

#### Scenario: 经 worker 线程写图

- **WHEN** 调用 `merge_concepts`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 单 worker 线程执行
- **AND** MUST 经 store 原语改图、再经 `self._mcs.run_compaction(changed)` 过守门
- **AND** `merge` 工具的 `readonly` MUST 为 `False`（不进只读召回白名单）
