## Context

当前 `_traverse` 方法实现逐节点扩展的 BFS 遍历：

```python
# 当前流程（伪代码）
while queue:
    node, depth = queue.pop(0)
    neighbors = store.get_neighbors(node.id)
    selected_ids = llm.call("select_nodes", nodes_in=[node, *neighbors], ...)
    for neighbor in neighbors:
        if neighbor.id in selected_ids and not visited:
            accumulated.append(neighbor)
            queue.append((neighbor, depth+1))
```

每次处理一个节点 → 加载邻居 → LLM 筛选 → 扩展。问题：
- **LLM 调用频繁**：每个扩展节点一次调用，延迟累积
- **小上下文浪费**：若某节点邻居很少（如 3 个），调用只占很小上下文，剩余容量浪费

MCS 核心不变量保证「任意节点 + 全部一跳邻居 ≤ T」，因此单次调用天然不超预算。但这也意味着单节点调用的上下文往往远小于 T，存在合并空间。

## Goals / Non-Goals

**Goals:**
- 在 token 预算允许的前提下，将多个节点及其邻居合并后一次 LLM 调用
- 减少遍历过程中的 LLM 调用次数，降低延迟和成本
- 保持 BFS 深度语义正确（选中节点的扩展深度应基于其所属中心节点）

**Non-Goals:**
- 不改变 select_nodes 的核心语义（仍是「从候选中选出与查询相关的节点」）
- 不改变遍历的终止条件（token 预算、max_rounds、max_accumulated_nodes）
- 不引入新的 LLM purpose（复用现有的 select_nodes）

## Decisions

### Decision 1: 批量打包策略 —「预算驱动贪心合并」

**方案**：从 queue 取出多个节点，贪心合并直到接近 token 预算 T。

```python
# 新流程
while queue:
    # 1. 贪心打包：取出节点直到预算接近 T
    batch_centers = []
    batch_neighbors = []
    batch_tokens = 0
    while queue and batch_tokens < T * 0.8:  # 留 20% 余量
        node, depth = queue.pop(0)
        neighbors = store.get_neighbors(node.id)
        node_tokens = estimate(node)
        neighbor_tokens = sum(estimate(n) for n in neighbors)
        if batch_tokens + node_tokens + neighbor_tokens > T:
            break  # 预算不足，停止打包
        batch_centers.append((node, depth))
        batch_neighbors.extend(neighbors)
        batch_tokens += node_tokens + neighbor_tokens

    # 2. 一次 LLM 调用筛选全部候选
    selected_ids = llm.call("select_nodes",
        nodes_in=[*batch_centers_nodes, *batch_neighbors], ...)

    # 3. 正确归类选中节点到各自中心
    for center, depth in batch_centers:
        center_neighbors = [n for n in batch_neighbors if n.is_neighbor_of(center)]
        for neighbor in center_neighbors:
            if neighbor.id in selected_ids and not visited:
                accumulated.append(neighbor)
                queue.append((neighbor, depth + 1))
```

**为什么选此方案**：
- 简单贪心，无需复杂调度
- 自然适配现有 token 预算框架
- 留 20% 余量避免估算误差导致超预算

**替代方案**：
- A) 固定批次大小（如每次处理 5 个节点）：不够灵活，可能超预算或浪费容量
- B) 预先计算全部 queue 的邻居再打包：可能加载过多邻居数据，浪费存储查询

### Decision 2: 提示词模板调整 —「显式区分中心与候选」

**方案**：在 `nodes_in` 渲染时，用结构化标记区分「中心节点」与「邻居候选」。

当前渲染格式：
```
- node_A (id=xxx)
  content...
- neighbor_1 (id=yyy)
  content...
- neighbor_2 (id=zzz)
  content...
```

批量场景需区分：
```
【中心节点】
- node_A (id=xxx, depth=2)
  content...
- node_B (id=aaa, depth=2)
  content...

【候选邻居】
- neighbor_1 (id=yyy, parent=xxx)
  content...
- neighbor_2 (id=zzz, parent=xxx)
  content...
- neighbor_3 (id=bbb, parent=aaa)
  content...
```

**提示词模板更新**：
```python
USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "中心节点（待扩展）:\n{centers}\n\n"
    "候选邻居:\n{neighbors}\n\n"
    "已选节点摘要:\n{accumulated_summary}\n\n"
    "请返回与查询最相关的邻居节点 id 列表 JSON, 例如 [\"id_a\", \"id_b\"]; "
    "注意：中心节点仅作为扩展起点，不要选中它们。"
    "若没有相关邻居则返回 []。按相关性降序排列。只返回 JSON。"
)
```

**关键点**：
- 明确告知 LLM「中心节点不要选中」，只选邻居
- 避免 LLM 返回中心节点 ID 导致归类混淆

### Decision 3: 邻居-中心映射 —「扩展元数据」

**方案**：在加载邻居时，记录 `parent_id` 元数据，便于后续归类。

```python
@dataclass
class NeighborInfo:
    node: Node
    parent_id: str  # 所属中心节点 ID
```

或者更简单：在批量处理时，用字典维护映射：
```python
neighbor_to_center: dict[str, str] = {}  # neighbor_id -> center_id
for center, depth in batch_centers:
    for neighbor in store.get_neighbors(center.id):
        neighbor_to_center[neighbor.id] = center.id
```

**为什么**：归类选中节点时，需要知道它属于哪个中心，以计算正确的扩展深度。

### Decision 4: 批量调用失败时的回退策略

**风险**：若批量调用解析失败或返回异常，如何回退？

**方案**：保持现有的逐节点处理作为 fallback。
- 若批量调用失败，拆分成单节点调用逐个处理
- 这样即使批量模式有问题，也能保证基本功能

```python
try:
    selected_ids = llm.call("select_nodes", nodes_in=batch_nodes, ...)
except LLMParseError:
    # 回退到逐节点处理
    for center, depth in batch_centers:
        single_selected = llm.call("select_nodes",
            nodes_in=[center, *center_neighbors], ...)
        ...
```

## Risks / Trade-offs

### Risk 1: 批量上下文可能让 LLM 筛选质量下降

**风险**：当候选节点过多（如 50+ 邻居），LLM 可能难以准确判断相关性。

**缓解**：
- 限制单批次邻居总数上限（如 max 30 邻居），即使 token 允许
- 留 20% 预算余量避免估算误差
- 若质量下降明显，可调整贪心打包阈值

### Risk 2: 批量处理可能改变 BFS 深度语义

**风险**：多个中心节点不同深度，批量处理后选中节点的深度如何确定？

**缓解**：
- 通过 `neighbor_to_center` 映射，选中节点的深度 = 所属中心深度 + 1
- 这是正确语义：邻居节点离中心的距离是 1 hop

### Risk 3: 邻居加载可能成为瓶颈

**风险**：批量打包需加载多个节点的邻居，存储查询次数增加。

**缓解**：
- 邻居加载是必需的（扩展必需），只是从「逐个加载」变为「批量加载」
- 可考虑存储层优化（批量邻居查询 API），但非本变更范围

## Migration Plan

**Phase 1: 提示词模板调整（不改变代码逻辑）**
- 更新 `select_nodes.py` 的 USER_TEMPLATE，支持多中心场景
- 验证新模板在单节点场景仍然工作

**Phase 2: _traverse 批量打包实现**
- 重构 `_traverse`，添加贪心打包逻辑
- 添加 `neighbor_to_center` 映射
- 保持 fallback 到逐节点处理

**Phase 3: 测试验证**
- 单元测试：批量打包、深度计算、fallback
- 集成测试：与现有遍历结果对比（应无功能差异）

**无回滚需求**：变更不涉及数据迁移，代码回滚即可恢复。

## Open Questions

1. **邻居总数上限**：单批次邻居候选是否需要上限（如 30）？还是纯 token 预算驱动？
   - 当前倾向：纯 token 预算驱动，后续按实测质量调整

2. **提示词兼容性**：是否需要区分「单节点模板」和「批量模板」？
   - 当前倾向：统一模板，用渲染格式区分（中心 vs 邻居）