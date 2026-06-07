## Context

### 当前问题
1. `_traverse` 将所有种子预置入 `accumulated`，违背"LLM 筛选后才加入"语义
2. 用 `max_picked` 节点计数而非 token 预算控制终止，与 MCS 核心不变量不一致
3. 种子超预算处理硬编码在 `_bound_seed_graph`，缺少插件化扩展
4. `visited` 语义模糊：未选中种子加入 `visited` 后无法被后续轮次重新发现

### 相关规范
- `CLAUDE.md`：token 预算是核心不变量
- `openspec/specs/query-pipeline/spec.md`：阶段 ③ 语义理解 Loop

### 约束
- 保持 `max_rounds` 作为 BFS 深度限制
- LLM 调用需考虑单次输入规模
- 需要安全阀防止 token 估算偏差

## Goals / Non-Goals

**Goals:**
- 引入 `SeedSelectorPluginInterface` 支持种子筛选策略插件化
- 重构 `_traverse` 为 token 预算驱动
- 精确化 `visited` 语义：仅选中者加入
- 提供安全阀防止估算偏差

**Non-Goals:**
- 不修改 `QueryContext` 字段定义
- 不修改 EntryPlugin、TrimPlugin 接口
- 不修改写入管线

## Decisions

### D1: SeedSelectorPluginInterface 用于种子筛选

**决定**：新增 `SeedSelectorPluginInterface`，负责种子筛选、排序和预算截断。

**理由**：
- 扩展性：支持多路召回策略（语义相似度、图结构中心性、自定义优先级）
- 单一职责：EntryPlugin 定位，TrimPlugin 硬截断，SeedSelector 语义筛选

**接口设计**：
```python
class SeedSelectorPluginInterface(Plugin):
    def get_type(self) -> PluginType:
        return PluginType.SEED_SELECTOR

    @abstractmethod
    def select(self, seeds: list[Node], query: str, budget: int, ctx) -> list[Node]:
        """返回预算内的种子子集，按相关性排序。"""
        pass
```

**执行顺序**：EntryPlugin 链 → TrimPlugin → SeedSelectorPlugin 链

### D2: _traverse 改为 token 预算驱动

**决定**：删除 `max_picked` 参数，用 `token_budget.T` 控制终止。

**理由**：
- 符合 MCS 核心不变量
- 与用户需求一致

**新遍历流程**：
```
1. 初始化：accumulated = [], visited = [], frontier = seeds
2. LLM 筛选 frontier：selected = llm.select(frontier, query, accumulated)
3. 若 selected 为空 → 终止
4. 将 selected 加入 accumulated 和 visited
5. 若 accumulated token > budget → 终止
6. 获取 selected 的子节点 → 过滤 visited → 作为新 frontier
7. 回到步骤 2
```

### D3: visited 语义精确化

**决定**：仅将**被 LLM 选中的**节点加入 `visited`，未选中者不加。

**理由**：
- 未选中节点可能在后续轮次因上下文变化而变得相关
- `visited` 语义从"已考虑"改为"已采纳"

**替代方案**：
- 所有候选都加 `visited` → 未选中者永远无法召回，过于激进

### D4: 安全阀机制

**决定**：保留 `max_rounds`，新增 `max_accumulated_nodes` 硬上限。

**理由**：
- `max_rounds`：防止 BFS 无限深入
- `max_accumulated_nodes`：防止 token 估算偏差导致 `accumulated` 无限增长

**默认值**：
- `max_rounds`：5（保持现有）
- `max_accumulated_nodes`：1000（远超正常需求，仅作兜底）

### D5: 单轮候选超预算时分批调用 LLM

**决定**：如果单轮 `frontier` token 超预算，分批调用 LLM。

**理由**：
- 避免单次 LLM 输入超预算
- 保持筛选语义

**实现**：
```python
def _select_with_batching(self, candidates, query, accumulated, budget):
    if estimate(candidates) <= budget:
        return self.llm.select(candidates, query, accumulated)

    # 分批：按优先级排序后分批
    batches = split_by_budget(candidates, budget)
    selected = []
    for batch in batches:
        batch_selected = self.llm.select(batch, query, accumulated + selected)
        selected.extend(batch_selected)
        if estimate(accumulated + selected) > budget:
            break
    return selected
```

### D6: SeedSelector 和 _traverse 复用同一 LLM purpose

**决定**：SeedSelector 和 `_traverse` 内部的 LLM 筛选使用同一个 purpose：`select_nodes`。

**理由**：
- 语义一致：都是"从候选中选择与查询相关的节点"
- prompt 复用：避免两套 prompt 设计

**LLM 调用签名**：
```python
llm.call(
    purpose="select_nodes",
    nodes_in=candidates,
    free_args={
        "query": query,
        "accumulated_summary": summarize(accumulated),
    },
)
```

## Risks / Trade-offs

### R1: visited 语义变更可能影响召回
**风险**：未选中节点不加 `visited`，可能导致同一节点被多次考虑（如果它出现在多个父节点的子节点中）。

**缓解**：
- 这是预期行为：上下文变化后可能重新评估
- 如果节点确实不相关，LLM 会持续不选中
- 性能影响可控：`max_rounds` 限制了遍历深度

### R2: 分批 LLM 调用增加延迟
**风险**：单轮候选过多时，分批调用会增加 LLM 调用次数。

**缓解**：
- 正常情况下候选数量有限（受 `max_rounds` 和图结构约束）
- 分批是兜底策略，不常见
- 可配置是否分批或直接截断

### R3: max_accumulated_nodes 阈值选择
**风险**：阈值过高无保护作用，过低影响正常查询。

**缓解**：
- 默认 1000 是保守值（正常查询 `accumulated` 通常 < 100）
- 可配置，用户可根据场景调整

## Migration Plan

### 阶段 1: 新增 SeedSelector 类型
1. 在 `PluginType` 中新增 `SEED_SELECTOR`
2. 创建 `SeedSelectorPluginInterface`
3. 实现 `LLMSeedSelectorPlugin` 默认实现

### 阶段 2: 重构 _traverse
1. 删除 `max_picked` 参数
2. 实现 token 预算驱动逻辑
3. 实现 visited 语义精确化
4. 实现分批 LLM 调用
5. 新增 `max_accumulated_nodes` 参数

### 阶段 3: 修改 _locate_seeds
1. 增加 SeedSelectorPlugin 链调用
2. 注册默认 `LLMSeedSelectorPlugin`

### 阶段 4: 测试与验证
1. 更新测试用例
2. 验证 token 预算约束
3. 验证 visited 语义

### 回滚策略
- 保留 `max_picked` 作为可选参数（deprecated），向后兼容
- SeedSelectorPlugin 链为空时跳过，不影响现有行为
