## 1. 方向感知的图原语（graph.py）

- [x] 1.1 `add_edge(direction="out")` 在邻接结构中如实表达方向（不再退化为双向）
- [x] 1.2 新增"取 out 邻居"原语：返回该节点为 `source` 且 `direction="out"` 的边目标；`bidirectional` 边两端互为邻居不变
- [x] 1.3 `get_neighbors` 保持"全部邻居"语义（语义遍历用）；补单测覆盖 out vs all 两种视图
- [x] 1.4 `save_full`/`load` round-trip 方向保真（out / bidirectional 各自不变）+ 单测

## 2. 层级边有向化（fanout_reducer._reorganize / _maintain_seed_root）

- [x] 2.1 `_reorganize` 改为有向拓扑：下行 `parent→child`（out）、`parent→hub`（out）；成员到原父改为有向上行 `member→old_parent`（out），不再删除该连接
- [x] 2.2 校验目标拓扑：对 `a—b,a—c` + 提 `d` ⇒ `a→d,d→b,d→c,b→a,c→a`（单测）
- [x] 2.3 `_maintain_seed_root` 把新概念挂根用有向下行 `root→concept`（out）
- [x] 2.4 确认有向层级产物进入 `changed_nodes` 并经 `save_full` 落库；语义边仍 `bidirectional`

## 3. 方向感知导航（hub_fallback._navigate / query_engine）

- [x] 3.1 `_navigate` 取候选改用 out 邻居（仅沿下行边下钻），不经语义/上行边回退
- [x] 3.2 保留"每层整圈候选入 visited"（已修），并加针对有向层级的下钻单测
- [x] 3.3 验证从持久根下钻不再把祖先/旁系重新纳入候选（无环）

## 4. 抗退化 bounding（fanout_reducer）

- [x] 4.1 单次 `decide_hub` 的社区规模设上限并分批（避免把整语料当一个社区）
- [x] 4.2 对过宽的合成 hub 做启发式校验 → 拒绝/重试或改分批（阈值可配）
- [x] 4.3 合成 hub 去重：新合成 hub 与既有 hub 名称/摘要近似时合并
- [ ] 4.4 （可选）按 `source_tracking` 来源/粗主题预分组后再 bounding
- [x] 4.5 撞 `max_reorg` 上限时告警日志（可观测）

## 5. 测试与实跑核验

- [x] 5.1 全量 pytest 回归（默认 `seed_graph_bounding=False` 行为不变）
- [ ] 5.2 小子集（20–50 篇）实跑：层级有向、导航不成环、无 catch-all 万能 hub、方向落库保真
- [ ] 5.3 与旧（双向星型）数据对比，确认 BREAKING 影响范围并在文档标注需重建

## 6. 文档

- [x] 6.1 更新 README / 相关说明：层级边有向语义、语义边仍双向、旧图需重建
- [ ] 6.2 归档/弃用基于旧逻辑构建的评测库（如 multihop_chat_200_v2）说明
