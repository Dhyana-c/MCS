## Why

`_traverse` 将所有种子预置入 `accumulated`，违背"LLM 筛选后才加入"的语义；用 `max_picked` 节点计数而非 token 预算控制终止，与 MCS 核心不变量不一致；种子超预算的处理硬编码在 `_bound_seed_graph`，缺少多路召回的插件链预留。

## What Changes

### 种子选择器插件化
- 新增 `PluginType.SEED_SELECTOR` 枚举值
- 新增 `SeedSelectorPluginInterface`，定义 `select(seeds, query, budget, ctx) -> list[Node]`
- 种子定位阶段改为：EntryPlugin 链 → TrimPlugin → SeedSelectorPlugin 链
- SeedSelectorPlugin 负责 LLM 语义筛选、排序和预算截断
- 提供 `LLMSeedSelectorPlugin` 默认实现

### **BREAKING** 遍历逻辑重构
- `_traverse` 改为 token 预算驱动，删除 `max_picked` 参数
- `accumulated` 初始为空，种子经 LLM 筛选后才加入
- 每轮 BFS：当前层候选 → LLM 筛选 → 选中者加入 `accumulated` → 检查预算 → 获取子节点 → visited 过滤 → 下一轮
- 终止条件：无新候选 或 `accumulated` token 超预算
- 保留 `max_rounds` 作为安全阀，新增 `max_accumulated_nodes` 硬上限防估算偏差
- 单轮候选超预算时分批调用 LLM

### visited 语义精确化
- 仅将**被 LLM 选中的**节点加入 `visited`
- 未选中的候选不加 `visited`，允许后续轮次重新发现

## Capabilities

### New Capabilities
- `seed-selector-plugin`: 种子选择器插件接口，负责 LLM 语义筛选、排序和预算截断
- `token-budget-traverse`: token 预算驱动的遍历逻辑，替代 max_picked 计数

### Modified Capabilities
- `plugin-protocol`: 新增 `SEED_SELECTOR` 插件类型
- `query-pipeline`: 阶段 ② 增加 SeedSelectorPlugin 链；阶段 ③ 改为 token 预算驱动

## Impact

### 代码变更
- `mcs/core/plugin.py`: 新增 `PluginType.SEED_SELECTOR`
- `mcs/interfaces/seed_selector_plugin.py`: 新增 `SeedSelectorPluginInterface`
- `mcs/core/query_engine.py`: 重构 `_traverse`、修改 `_locate_seeds`；删除 `max_picked` 参数
- `mcs/plugins/phase1/llm_seed_selector.py`: 新增默认 `LLMSeedSelectorPlugin`

### API 变更
- **Breaking**: `QueryEngine.__init__` 删除 `max_picked` 参数

### 依赖
- 前置变更：`preprocess-plugin-type`（确保插件类型体系已就绪）
