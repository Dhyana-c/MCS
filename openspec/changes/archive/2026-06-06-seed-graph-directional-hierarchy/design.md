## Context

已实现的持久分层种子图：`fanout_reducer`（`maintain_root=True` / `seed_graph_bounding`）维护持久虚拟根 `__seed_root__`，把新概念挂到根下并递归 `decide_hub` 归纳；查询只读，`hub_fallback` 从根 BFS 下钻定位兜底种子；`save_full` 全量重建以反映边删除。

当前一切边走 `GraphStore.add_edge(direction="bidirectional")`（含层级边），`get_neighbors` 返回无向邻居。200 篇整篇实跑暴露两类问题（见 proposal）：层级边无方向/无类型导致导航缠绕成环；`decide_hub` 在主题分散社区上退化成 catch-all 万能 hub。

约束：`GraphStore` 是内存图 + sqlite 持久化（`edges(source_id,target_id,direction)` 已有 `direction` 列，`load` 已读回方向，但当前无人产出 `out` 边）；语义边（judge）必须保持双向以保检索召回；改动需保留既有测试契约（默认 `seed_graph_bounding=False` 时行为不变）。

## Goals / Non-Goals

**Goals:**
- 层级边有向化：父→子（下行）+ 成员→原父（上行回指），与语义边可区分。
- 方向感知的图原语与自顶向下导航（仅沿 out 边下钻）。
- 抗退化的递归 bounding，避免 catch-all 万能 hub。
- 语义边（judge）保持双向不变。

**Non-Goals:**
- 不改 `judge_relations` 的语义边方向或写入管线其它阶段。
- 不引入向量/embedding 检索（主题预分组若用相似度，作为可选项而非必需依赖）。
- 不追求一次性"完美层级"；以"可导航、可区分、可收敛、抗退化"为底线。

## Decisions

### D1：层级边用有向 `out`，语义边仍双向（混合方向模型）
`_reorganize` 改为产出有向边：`add_edge(parent, child, direction="out")`（下行），并把成员到原父的连接改为有向上行 `add_edge(member, old_parent, direction="out")`，而不是删除。语义边继续 `bidirectional`。
- **理由**：层级需要可区分的下钻方向以防成环；语义需双向以保召回。`edges` 表已有 `direction` 列，成本低。
- **备选**：(a) 给边加 `type` 字段区分 hierarchy/semantic——更显式但要改 schema/序列化；(b) 用单独的"层级覆盖"结构（如 `node.extensions["seed_parent"]`）而非图边——彻底分离但导航/持久化要另写。先选最小改动的"方向区分"，`type` 字段留作后续。

### D2：`GraphStore` 增加方向感知取邻居
新增"取 out 邻居"原语（该节点为 `source` 且 `direction="out"` 的边目标；`bidirectional` 边两端互为邻居不变）。`get_neighbors` 保持"全部邻居"语义（语义遍历仍用它）；导航改用 out 邻居。
- **理由**：导航要"只往下"，语义遍历要"全连通"，两者需要不同视图。
- **备选**：在导航处临时过滤 `get_all_edges`——O(E) 太慢；应在邻接层支持。

### D3：导航与 `_navigate` 沿 out 边 + 整圈 visited
`hub_fallback._navigate` 改用 out 邻居取候选；保持"每层整圈候选都入 visited"（已修）。`a→d, d→b, d→c` 下钻自然只到子层，上行边 `b→a` 不会把祖先重新拉回候选。
- **理由**：方向 + 整圈 visited 双保险，根除缠绕成环。

### D4：抗退化 bounding —— 规模限制 + 拒绝过宽 hub（+ 去重）
- **规模限制/分批**：`_select_batch` 已按 token 预算选批；进一步对"单个社区一次喂给 `decide_hub` 的规模"设上限并分批，避免把"整个语料"当一个社区。
- **拒绝过宽合成 hub**：对 `decide_hub` 返回的合成 hub 做启发式校验（如摘要覆盖领域过多/过长、或一次性想收纳的成员比例过高）→ 拒绝并改用分批/不归纳。
- **合成 hub 去重**：新合成 hub 与既有 hub 名称/摘要近似时合并，避免堆积近义万能 hub。
- **可选预分组**：按 `source_tracking` 来源或粗主题先分桶，再在桶内 bounding，从源头减少"主题分散社区"。
- **理由**：catch-all 的根因是"把全主题社区一次性交给 LLM 聚类"；从规模、校验、去重、预分组四个角度抑制。
- **备选**：纯靠 prompt 约束 `decide_hub` 不造万能 hub——不可靠（实测已反复违反）；需结构性约束兜底。

## Risks / Trade-offs

- **[BREAKING：拓扑/方向变化]** 旧双向星型图与新有向逻辑不一致 → 缓解：新能力 opt-in 同一开关下生效；既有 v2 数据需重建才对齐（文档/迁移说明）。
- **[有向边遍历回归风险]** 语义遍历若误用 out 邻居会掉召回 → 缓解：明确"语义遍历用全邻居、导航用 out 邻居"，加测试覆盖两条路径。
- **[抗退化启发式误杀]** 过严的"拒绝过宽 hub"可能拒掉合理大 hub → 缓解：阈值可配 + 拒绝时优雅降级为分批而非完全不归纳。
- **[预分组依赖来源/主题质量]** 来源分桶在跨源同主题时可能割裂 → 缓解：预分组为可选增强，不作为正确性前提。
- **[持久化方向保真]** `save_full`/`load` 若漏处理方向会静默丢失层级方向 → 缓解：round-trip 测试断言方向一致。

## Migration Plan

1. 先加 `GraphStore` 方向原语 + `_reorganize` 有向化（带测试），保证默认关时行为不变。
2. 导航切到 out 邻居（带测试）。
3. 抗退化 bounding（规模/拒绝/去重，逐项带测试）。
4. 用小子集（如 20–50 篇）实跑核验：层级有向、导航不成环、无 catch-all、方向落库保真。
5. 通过后重建评测图（旧 v2 等不兼容数据弃用或归档）。
- **回滚**：开关关闭即回退到现有（双向星型 + 现有 bounding）路径。

## Open Questions

- 是否引入显式边 `type`（hierarchy/semantic）而非仅靠 `direction` 区分？（D1 备选 a）
- 抗退化优先做哪一项：规模限制/拒绝/去重/预分组？建议先"规模限制 + 拒绝过宽"（性价比最高），去重/预分组随后。
- `max_seeds` / `max_depth` / 社区规模上限 / 过宽阈值的默认值需结合实跑标定。
