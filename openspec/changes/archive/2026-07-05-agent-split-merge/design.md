# Design: agent-split-merge

> 配套 `proposal.md`。本文展开三个实现风险、关键决策、`split` / `merge` prompt 骨架与边安全迁移规则，使 `tasks.md` 可直接执行。

## 背景（一句话）

系统**有合无分**：`merge` 同义在 core 写入 / 读取自动跑，`split` 完全缺失——增量抽取的粒度判错（类别-特化耦合 / 多实体误并）无法收敛回正确粒度。本 change 在 mcs_agent 层加 `split` / `merge` 两工具，**core 零改动**。

## 关键设计决策

### D1：放 agent 工具层，core 仅加 public 守门入口

触发"该拆"的信号弱（无"重名 / 同义"这种明确标志），适合 **LLM 主动判断**而非 core 自动——故放 agent 工具层。core Store 的低层图编辑原语（`add/delete/update` node+edge）与回滚（`snapshot` / `restore`）早已齐全，split / merge 纯组合这些原语。**唯一 core 改动**：加 `run_compaction` public 守门入口（薄转发阶段⑥，见 D8）——split / merge 改图后必须过守门、但原入口私有。core schema / 管线逻辑 / 铁律不动。

### D2：方案 (ii)——专用 prompt 产方案，跟 `generalize` / `arbitrate` 同构

主 LLM 只给 `node_id(s) + focus`；工具内部加载节点 + 全部边 → 调专用 purpose 产结构化方案 → 执行。**否决方案 (i)**（主 LLM 在 tool_call args 里直给 `into[]/edges[]`）：① 反 MCS 模式——现有所有"调 LLM 的工具"（learn 经管线、generalize、arbitrate）都是"主 LLM 给目标 + 素材指针，工具内部用专用 prompt 产方案"，无一让主 LLM 直吐结构化语义方案；② 主 LLM 看到的是 `associate` 返回的**有界子图，未必看全边**，看不全就在 args 里给不全归属 → 漏边的根源。专用 prompt 由工具加载**完整边集**，从源头治漏边。

### D3：双重防误触发（主 LLM 判断 + 专用 prompt `noop` 复核）

- 第一道：主 LLM 凭对话上下文判断"该拆 / 该合"才调工具（工具描述写清触发红线）。
- 第二道：专用 prompt 复核——确认未耦合 / 非同义时返回 `action=noop`、不执行。

两道闸都过才改图。误触发代价高（制造噪音节点 + 错分边），双重闸把误触发压到最低。

### D4：边的处理交 LLM，机制层只守四条硬底线

每条原边归属由专用 prompt 给出（split 强制全覆盖、parse 校验）；机制层不替 LLM 做"漏边落 parent"这种语义默认，只守：

1. **守门**——产物邻域 ≤ T（split 减扇出几乎必过；merge 增扇出认真过）。
2. **原子事务**——全成或全回滚（用 `snapshot` / `restore`，见 D5）。
3. **不破互斥 / 背书**——边迁移不撕裂互斥对、不断事件背书（见「边安全迁移规则」）。
4. **不丢信息**——LLM 漏指的边不随 `delete_node` 消失（见「风险 3」）。

### D5：原子事务用 `store.snapshot()` / `restore()`

`StoreInterface` 已提供 `snapshot() -> dict` 与 `restore(snapshot)`（fanout 裂变失败回滚在用，保留边 id 与变更跟踪集）。`split_concept` / `merge_concepts` 在执行前 `snap = store.snapshot()`，任一步失败 `store.restore(snap)` 回到操作前。**零新增事务机制**。

### D6：跨实体边物化 fact 节点

split 时，描述"两产物之间关系"的原边（如"小明和小红是夫妻"）无处安放——专用 prompt 在 `into[]` 里产出一个 `role=fact` 节点承接，再在 `edges[]` 里把该边归到这个 fact。复用"谓词落事实 content"的本职，不破边类型极简。

### D7：merge 互斥安全闸 + 增扇出守门

- **互斥禁合**：`keep` 与任一 `absorb` 之间若有 `互斥` 边，合并会塌缩矛盾——专用 prompt 判出即 `noop`；机制层再加一道保险，执行前扫互斥边、命中即拒。
- **增扇出守门**：merge 把多个邻域并到 `keep`，可能超 T → 过守门 → 可能触发 `decide_hub` 裂变。由守门既有机制兜，不在 merge 内特殊处理。

### D8：守门入口 public 化（唯一 core 改动）

split / merge 改图后必须过守门（保证"任意节点活跃视图 ≤ T"），但 `WritePipeline._run_compaction`（阶段⑥守门）是私有方法、MCS 瘦门面无 public 守门入口。**否决调私有**（`self._mcs.write_pipeline._run_compaction`）：agent 层不应跨进 core 私有。故 core 加两层 public 薄转发：

- `WritePipeline.run_compaction(changed_nodes: list[Node]) -> None`：转发 `self._run_compaction(changed_nodes)`。
- `MCS.run_compaction(changed_nodes: list[Node]) -> None`：转发 `self.write_pipeline.run_compaction(changed_nodes)`。

MemoryStore 调 `self._mcs.run_compaction(changed)`。core 仅加这两个 public 方法、不改既有逻辑——也为未来其他图手术（read-repair 写回等）留出守门钩子。

## 三个实现风险的落实

### 风险 1：原子事务 → `snapshot` / `restore`（已解决）

store 已有回滚（见 D5）。执行序列：

```
snap = store.snapshot()
try:
    执行方案（建 / 改 / 删 node+edge）
    守门（merge 增扇出可能触发裂变）
    成功 → 继续（不主动 restore）
except:
    store.restore(snap)   # 回到操作前
    raise（经 _dispatch 隔离为 [error]）
```

### 风险 2：merge 增扇出触发裂变 → 由守门机制兜

split 减扇出，守门几乎必过。merge 增扇出——split / merge 改图后调 `self._mcs.run_compaction(changed)`（changed = 产物 / keep 节点），若 `keep` 邻域超 T，由阶段⑥的 `FanoutReducerPlugin` 裂变收敛（既有机制，非本 change 新增）。design 不在 merge 流程内特殊衔接裂变——守门是 core 写路径的统一闸，split / merge 经 public 入口（D8）复用它。

### 风险 3：漏边降级 → 透明兜底

split 专用 prompt 拿到完整边集，写死约束"必须为每条原边指定归属"。`parse()` 只做结构校验（`into` 非空），**不做原边全覆盖校验**（parse 无原边集上下文）。全覆盖校验在 `_do_split` 执行侧做：比对原边集与 `edges` 覆盖集，漏指的边**透明挂到 `parent`**（无 parent 则首个非 fact 产物），并在返回文本列出"这 N 条边未收到归属、暂挂 X"。机制层只防物理丢失，语义归属仍归 LLM（下一轮可修）。

## 边安全迁移规则

`delete_node` 连带删该节点的关联边——故删旧节点前必须先把该迁的边迁走。

**split**（原节点删除，产物为 `into[]`）：

| 原边类型 | 加载入口 | 迁移去向 |
|---|---|---|
| `关联`（概念 / 事实间） | `get_relations` | 按 LLM `edges[]` 归属改 `source` / `target` 指向产物 |
| `互斥`（事实 ↔ 事实） | `get_relations` | **N/A**：split 仅拆概念节点（`_do_split` 前置校验 `node_class==概念`），互斥恒 fact↔事实，概念节点 `get_relations` 取不到互斥边——此路不可达，无需特判 |
| 事件背书（事件 → 原节点） | `get_related_events` | **机制层自动迁 `target` 到 `parent`**（事件背书大类天然归大类）；不交 LLM（事件层不进核心视图） |

**merge**（`absorb[]` 删除，并入 `keep`）：

| `absorb` 的边 | 迁移 |
|---|---|
| `关联`（任一端是 absorb） | 改端点指向 `keep`；`add_edge` 去重，已存在的不重 |
| `互斥`（absorb ↔ 其他事实） | 迁移到 `keep` ↔ 该事实；**keep 与 absorb 间的互斥边 → 触发安全闸、整个 merge 拒绝** |
| 事件背书（事件 → absorb） | 迁移 `target` 到 `keep` |
| `absorb.name` / `aliases` | 并入 `keep.aliases`（异名收口） |

## `split` / `merge` prompt 骨架

两 prompt 同 `generalize` / `adjudicate` 骨架（`SYSTEM_PROMPT` / `USER_TEMPLATE` / `parse`），注册进 `DEFAULT_PROMPTS`。

### `purpose="split"`（`mcs/prompts/split.py`）

**SYSTEM_PROMPT 要点**：判定节点是否耦合了多个语义中心；两类——类别-特化（`relation=is_a`）/ 多实体误并（`relation=none`）；**必须为每条原边指定归属**；跨两产物关系的边 → 产 `role=fact` 节点承接；未耦合时返回 `action=noop`。

**输入**（`free_args`）：`material`（节点 content + 全部原边含对端 name，由工具自建、**不截断**——T 约束查询窗口非 LLM 单次 context，全部原边远在 context 内、保全覆盖校验）+ `focus`。

**输出结构**（`parse` 校验）：

```json
{
  "action": "split | noop",
  "into": [{"name": "...", "content": "...", "role": "parent|child|sibling|fact"}],
  "relation": "is_a | none",
  "edges": [{"counterpart": "原边对端 name", "to": "into 中某 name"}]
}
```

`parse` 校验：`action=split` 时 `into` 非空（结构校验）。**原边全覆盖校验在 `_do_split` 执行侧做**（parse 无原边集上下文）：漏指的边透明挂 `parent`（无 parent 则首个非 fact 产物），返回文本列出"暂挂"提示——不抛 `LLMParseError`（LLM 偶发漏指但仍解析通过时，降级优于拒绝执行）。

### `purpose="merge"`（`mcs/prompts/merge.py`）

**SYSTEM_PROMPT 要点**：判定节点是否本就同一个（异名 / 同义 / 重复建）；产出 `keep` / `absorb` / `merged_content` / `aliases_to_add`；**互斥对禁合**（返回 `noop` 并说明）；非同义时 `noop`。不复用 `judge_relations`——其 merge 是写入期对齐（对每个新概念判 merge/create/no_op），口径与 agent 手动合并不同。

**输入**（`free_args`）：`material`（各节点 content + 对端，工具自建、T 有界）+ `focus`。

**输出结构**：

```json
{
  "action": "merge | noop",
  "keep": "节点 id",
  "absorb": ["节点 id"],
  "merged_content": "合并后 content（可空，空则用 keep 的）",
  "aliases_to_add": ["..."]
}
```

`parse` 校验：`action=merge` 时 `keep` 与 `absorb` 均在传入 id 集合内、且 `keep` 不在 `absorb` 中。

## 被否决方案

- **core 自动触发 split**：core 写入 / 读取都向前看，**无"回审已有节点"的钩子**；要加需动管线、且信号弱易误触发。放 agent 层由 LLM 主动判断更自然。
- **方案 (i) 主 LLM 直给拆分方案**：反 MCS 模式 + 主 LLM 看不全边（见 D2）。
- **给概念加 `specialization_of` 软字段**（不真拆、只标注）：content 仍耦合、边仍混、查询污染还在——治标不治本。
- **新增 `is_a` 边类型**：本 change 不动 core schema；split 产物间关系按"谓词落事实 content"本职表达（D6），不引入新边类型。

## 不变量与边界

- split / merge 是 agent **显式写操作**（同 `learn`），走写路径、过守门——**不在聚类 fanout 铁律适用范围**（铁律管自动裂变不波及关系边；显式写操作的边重分合法）。
- 仍守"召回 MUST NOT 写图"：split / merge `readonly=False`，自动排除出 `/recall` 只读白名单。
- core 图模型、两条铁律、Store 接口均不动。
