## Why

记忆 agent 的概念图存在一个**对称缺口：有合无分**。

- **合**：core 写入管线（`judge_relations` 的 `merge`）与读取（read-repair）已在自动做"同义合并"——把过度分裂的重复概念收口。
- **分**：完全缺失。当一个概念节点**粒度判错**时，系统没有任何机制把它拆回正确粒度。

粒度判错是**增量抽取的固有后果**，不是偶发 bug：第一次见到某输入时，LLM 没有上下文判断一个概念是大类还是特化、是单实体还是多实体误并，只能按当前文本猜。典型两种：

1. **类别-特化耦合**：节点叫"按摩"，content 却主要在讲泰式按摩的拉伸特点——大类与某特化耦合进同一节点。
2. **多实体误并**：节点叫"小明和小红"，content 其实是两个独立实体被当成一个。

这类节点一旦建出，其上的边也跨了多个语义中心；而后续写入 / 读取都向前看、**不回头审**"这个老节点是不是耦合了"——架构里没有回审时机，过度耦合的图**无法收敛回正确粒度**。

触发"该拆"的信号弱（不像合并有"重名 / 同义"这种明确信号），适合 **LLM 主动判断**而非 core 自动——因此放 agent 工具层，由 agent 在使用中发觉并调用。core Store 的低层图编辑原语（`add/delete/update` node+edge）早已齐全（`merge` 同义一直在用同一组原语），故 split / merge 可纯组合这些原语、**core 零改动、铁律不动**。

顺手补 `merge` 工具对称：core 自动合并之外的残留重复，给 agent 一个手动收口入口。

## What Changes

- **新增 `split` 工具（拆分·写图）**：给定一个节点 id + 可选 focus → 工具加载该节点完整 content + 全部边（含对端）→ 经新 purpose `split` 让 LLM 判断**是否耦合了多个语义中心**，若是则产出拆分方案（产物 `into[]` + 产物间 `relation`（`is_a` / `none`）+ 每条原边归属 `edges[]`）→ 执行（core 原语建 / 删 / 改）→ 过守门 → 返回结果。**主 LLM 只给 `node_id + focus`，方案由专用 prompt 产出**（同 `generalize` / `arbitrate` 模式，唯一区别是改图）。
- **新增 `merge` 工具（合并·写图）**：给定若干节点 id + 可选 focus → 工具加载这些节点 → 经新 purpose `merge` 判定**是否本就同一个**（异名 / 同义 / 重复建）→ 产出合并方案（保留谁 `keep`、吸收谁 `absorb`、合并后 content）→ 执行（边 / 背书 / 互斥安全迁移 + 删被吸收节点）→ 过守门 → 返回。**互斥对禁合**（合并会塌缩矛盾）。
- **split 的双重防误触发**：① 主 LLM 凭对话上下文判断"该拆"才调；② 专用 prompt 复核——确认未耦合时返回 `action=noop`、不执行。两道闸都过才改图。
- **边的处理交 LLM、机制层只守硬底线**：每条原边归属由专用 prompt 给出（split 强制全覆盖；LLM 偶发漏指的边执行侧透明挂 `parent` + 返回提示——降级优于拒绝；跨两产物关系的边 → 由 prompt 产出一个 `role=fact` 节点承接，复用"谓词落事实 content"的本职）。机制层只守：**守门**（产物邻域 ≤ T）、**原子事务**（全成或全回滚）、**不破互斥 / 背书**（边迁移不撕裂互斥对、不断事件背书）、**不丢信息**。
- **2 个新提示词**：`mcs/prompts/split.py`、`mcs/prompts/merge.py`，注册进 `DEFAULT_PROMPTS`。两 prompt 同 `generalize` / `adjudicate` 骨架（system / template / parse），含两类 few-shot（按摩型 / 小明小红型）与 `noop` 闸；**不复用 `judge_relations`**——其 merge 是写入期对齐、口径与 agent 手动合并不同。
- **`readonly=False` 必标**：split / merge 是写图工具，`ToolSpec.readonly=False`，自动排除出只读召回（`/recall` 白名单），保"召回 MUST NOT 写图"铁律。
- **默认工具集 7 → 9**（增量、非破坏）：`ToolsetConfig` 默认 `enabled=None` 现含 `split` / `merge`；`DEFAULT_SYSTEM_PROMPT` 补两工具说明（含"何时不该调"红线）。
- **core 仅加一个 public 守门入口**：split / merge 改图后必须过守门（merge 增扇出可能超 T），而 `WritePipeline._run_compaction`（阶段⑥守门）是私有、MCS 无 public 守门入口。故 core 加 `WritePipeline.run_compaction(changed)` + `MCS.run_compaction(changed)`（薄转发阶段⑥），供 split / merge 与未来其他图手术改图后保证不变量。**此外 core 一行不改**——不动 schema、写 / 查管线逻辑、聚类、Store 接口、两条铁律；图操作仍纯组合 store 的 `add/delete/update` node+edge 原语。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-agent`：
  - `记忆工具集` requirement 由「默认 7 个」改为「默认 9 个（learn / search / associate / reason / recall / generalize / arbitrate / **split** / **merge**）」，补两条分发映射；split / merge 标 `readonly=False`。
  - 新增 `split 原语（概念拆分）` requirement：给定节点 id + focus → 加载节点 + 全部边 → split purpose 判耦合（noop 复核）→ 产拆分方案（into / relation / edges，边全覆盖校验）→ 执行 core 原语 → 守门 + 原子事务 → 文本；写图。
  - 新增 `merge 原语（概念合并）` requirement：给定节点 id 列表 + focus → merge purpose 判同义（互斥禁合）→ 产合并方案（keep / absorb / merged_content）→ 边 / 背书 / 互斥安全迁移 + 删被吸收节点 → 守门（增扇出可能触发裂变）+ 原子事务 → 文本；写图。
- `llm-interaction`：
  - 新增 `split` / `merge` 两个 purpose（注册进 `DEFAULT_PROMPTS`，system / template / parse 三元组）。
- `write-pipeline`：
  - 新增 `WritePipeline.run_compaction(changed)` public 守门入口 requirement（薄转发阶段⑥，供外部图手术 split / merge 改图后过守门、保证不变量）。

## Impact

- **代码**：
  - `mcs/core/write_pipeline.py`：新增 public `run_compaction(changed_nodes)`（转发 `_run_compaction`，供外部图手术过守门）。
  - `mcs/core/mcs.py`：新增 public `run_compaction(changed_nodes)`（转发 `write_pipeline.run_compaction`）。
  - `mcs/prompts/split.py`、`mcs/prompts/merge.py`（新 purpose 的 system / template / parse，含 noop 闸、边全覆盖校验、两类 few-shot）+ `mcs/prompts/__init__.py` 注册进 `DEFAULT_PROMPTS`。
  - `mcs_agent/memory.py`：新增 `split_concept(node_id, focus?)` / `merge_concepts(node_ids, focus?)` 两原语（worker 线程：加载节点 + 边 → 调 LLM 插件出方案 → 执行 core 原语 → 守门 → 原子事务 → 渲染返回）。
  - `mcs_agent/tools.py`：`BUILTIN_TOOLS` 加 `split` / `merge` 两 `ToolSpec`（`readonly=False`）+ handler；`MEMORY_TOOLS` 废弃别名随之含 9。
  - `mcs_agent/loop.py`：`DEFAULT_SYSTEM_PROMPT` 补两工具说明（含触发红线）。
- **测试**（含边界）：split 两类（按摩 `is_a` / 小明小红 `none`）、split `noop`（专用 prompt 复核拒绝）、split 漏边（强制全覆盖 + parse 校验）、split 跨关系边物化 fact；merge 同义合并、merge **互斥禁合**、merge 增扇出过守门（可能触发裂变）；split / merge **原子回滚**（中途失败恢复原图）；split / merge `readonly=False` 不进只读召回；专用 prompt LLM 解析失败隔离为 `[error]`。
- **文档**：`docs/graph-model-design.md` 补「概念拆分 / 合并（agent 工具层）」段——区别于 core 聚类重组（split 是节点**自身**分裂、波及关系边；聚类 fanout 只动组织层级）；`docs/memory-agent.md` 工具表加两行、7→9。
- **API / 依赖**：无新增依赖；工具名 `split` / `merge` 为增量新增，公共 API 签名 `(*, node_id | node_ids, focus?) -> str`，无 BREAKING。
- **不变量**：split / merge 是 agent **显式写操作**（同 `learn`），走写路径、过守门——**不在聚类 fanout 铁律的适用范围**（铁律管自动裂变不波及关系边；显式写操作的边重分合法，与 `learn` 建边同性质）。split 减扇出（邻域变小、守门几乎必过）；merge 增扇出（认真过守门、可能触发 `decide_hub` 裂变，由守门既有机制兜）。core 图模型、两条铁律、Store 接口、写 / 查管线逻辑均不动——仅加 `run_compaction` public 方法（薄转发阶段⑥）。
- **实现风险**（详见 design）：① 原子事务——store 暴露单条 add/delete/update、未见批量 / 事务接口；② merge 增扇出触发裂变的流程衔接；③ 漏边降级（专用 prompt 强制全覆盖 + parse 校验为主线，LLM 仍不配合时的兜底）。
