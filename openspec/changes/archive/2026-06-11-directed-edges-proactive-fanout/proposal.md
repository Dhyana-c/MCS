## Why

全量建图实测（141 篇即中断）显示 `__seed_root__` 退化为**扁平直挂 ~800 个子节点**（766 裸概念 + 59 hub），逼近 token 上限 T 而不收敛——这正是宪法点名的"扁平直挂"反例的翻版，只是这次险险压在 T 以下、骗过了守门闸。根因有四，且彼此咬合：① 守门用降摘要渲染，~800 个 stub 才到 T，**裂变跳闸太晚**；② 节点超 T 后被迫**分批**（≤50）、decide_hub 平均仅覆盖 48%，每轮只削够回落 T 以下即停；③ `_validate_reorg` 的 before（仅一批）与 after（全邻域）**口径不对等**，优化护栏 118/118 全判失败却不回滚，形同虚设；④ `_reorganize` 用 `delete_edge` 重连时会把**双向语义边退化成单向**——一旦"全局裂变"开启将全面发作。

这些问题的共同根子是**双向/单向两套边类型 + 被动滞后的守门 + 分批**。本次从模型层面统一：取消双向边、改为主动整窗单次裂变。

## What Changes

- **BREAKING** 取消双向边：全图只有单向边；原 `judge_relations` 的一条 `bidirectional` 语义边，改为落**两条对向单向边**（`a→b` 与 `b→a`）。存储 schema 简化为 `(source_id, target_id)`，去掉 `direction` 列与双向边的端点归一化。
- **BREAKING** 边原语合一：`get_neighbors` 即有向出邻居（与 `get_out_neighbors` 合一）；`add_edge` 去掉 `direction` 分支与 `bidirectional` 默认语义。
- 导航语义改变：`hub_fallback` 自顶向下导航与查询扩展**沿全部单向出边**走——**语义边因此也参与导航**（有意为之，提升可达性）。层级"骨架"不再靠边类型区分，改用节点 `role`（hub/concept）识别。
- 守门改为**主动、不分批、全局**：在任一节点一跳邻域**即将超 T 的那一刻**触发裂变，始终保持 ≤ T；因 `T≈W/2`，触发时"中心 + 全部一跳子节点"恰好塞进完整上下文窗口，**一次整窗喂给 LLM、单次处理全部**。删除分批（`_select_batch` 贪婪取批）与折半重试。适用于**任意**超预算节点，不限 `__seed_root__`。
- 裂变动作（单次整窗生成）：LLM 一次性产出"一批 hub + 每个 hub 关联哪些已有节点 + 哪些已有节点合并同义"。hub 可为**新合成**或**提拔已有子节点**；**三种重组策略全保留**（合并同义 / 找关键概念 / 概括成新概念）。对每条有效 `(hub H, 成员 M)`：删 `C→M`、建 `C→H`、建 `H→M`。幻觉 id（被关联节点不存在）忽略；未被关联的子节点留在 C 下不丢；一个已有节点可关联多个 hub（多父/重叠）。
- 修复优化护栏：`_validate_reorg` 的 before/after **同口径**（都按中心节点全邻域估算），让"总量降才接受、否则回滚"真正生效。

## Capabilities

### New Capabilities
<!-- 本次为对既有行为的重构，不引入全新 capability -->
（无）

### Modified Capabilities
- `seed-graph-hierarchy`: 边方向模型从"层级边有向 + 语义边双向 + 成员上行边"改为"**全单向**"——语义关系以**两条对向单向边**（`a→b`+`b→a`）表达、层级边为纯下行 `父→子`（**取消成员上行边**）；自顶向下导航从"**仅沿 out 边**"改为"沿全部单向出边（**语义边参与导航**）"；"方向感知原语（out 邻居 vs 全邻居）"收敛为**单一有向邻接**；层级骨架识别由边方向改为节点 `role`；递归 bounding **取消分批**机制（保留 catch-all hub 防退化）。`judge_relations` 落库随之从 1 条双向边改为 2 条对向单向边（边模型的实现结果，非写管线需求变更）。
- `store-interface`: 边存储抽象从 `add_edge(..., direction="bidirectional")` 改为单向 `add_edge(source, target)`；持久化 schema 为 `(source_id, target_id)`；`get_neighbors` 定义为有向出邻居（与 `get_out_neighbors` 合一）。
- `subgraph-bounding`: 守门触发从"邻域逼近/超过容量才归纳（被动、超量时分批）"改为"**即将超即主动整窗单次裂变、永不分批、全局任意节点**"；强化"喂给 decide_hub 的必为全部一跳子节点"；重组接受判据（before/after token 总量）改为**中心节点全邻域同口径**。

## Impact

- **代码**：
  - `mcs/plugins/maintenance/fanout_reducer.py`：重写（删分批/折半重试、删 bidi 退化路径、改主动触发、修 `_validate_reorg` 口径、role 驱动骨架）。
  - `mcs/stores/sqlite_store.py`、`mcs/stores/in_memory.py`：schema、`_edge_key`、`add_edge`/`delete_edge`/`get_neighbors`/`get_out_neighbors`、`save_full`/`load`。
  - `mcs/core/write_pipeline.py`：`judge_relations` 落两条单向边；守门触发。
  - `mcs/core/query_engine.py`、`mcs/plugins/entry/hub_fallback.py`：导航/扩展沿单向边。
  - `mcs/core/context_renderer.py`：如渲染涉及方向需同步。
- **文档**：CLAUDE.md 宪法（边方向、铁律口径、总体流程的 `judge_relations` 落两条边）；本次涉及的 spec deltas。
- **数据/评测**：`bench/multihop_rag/outputs/v4flash_full/*.db` 作废，改后**重建**；多跳评测须验证"语义边参与导航"对召回的影响（不可拍脑袋）。
- **待讨论（非阻塞，留 design）**：纯 token"即将超 T"触发下，若节点为 stub 且 LLM 单次欠挑，中心仍可能较宽；"token 降即接受"允许增量收敛。是否需补充**更低目标水位**或**扇出数硬上限**作为协同判据。
