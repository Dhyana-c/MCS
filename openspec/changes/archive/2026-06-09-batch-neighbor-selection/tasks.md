## 1. 提示词模板适配

- [x] 1.1 更新 `mcs/prompts/select_nodes.py` 的 `USER_TEMPLATE`，区分「中心节点」与「候选邻居」两段，并在 free_args 中支持 `centers` 和 `neighbors` 占位符
- [x] 1.2 更新 `SYSTEM_PROMPT`，明确告知 LLM「只从候选邻居中选取，不要选中中心节点」
- [x] 1.3 验证新模板在单中心节点场景（退化为旧模式）下仍能正常工作

## 2. _traverse 批量扩展核心逻辑

- [x] 2.1 在 `_traverse` 中实现贪心打包逻辑：从 queue 取节点，累加估算 token（中心 + 邻居），直到 `batch_tokens >= T * 0.8` 或 queue 为空
- [x] 2.2 实现邻居-中心映射：加载每个中心节点的邻居时，维护 `neighbor_id -> (center_id, center_depth)` 字典
- [x] 2.3 实现批量 LLM 调用：将所有中心节点和邻居合并为 `nodes_in`，传入 `centers` 和 `neighbors` 渲染结果到 free_args
- [x] 2.4 实现选中节点归类：根据 `neighbor_to_center` 映射，将 LLM 选中的邻居正确归类到所属中心，计算 `depth = center_depth + 1`

## 3. 回退与安全机制

- [x] 3.1 实现批量调用失败时的回退逻辑：捕获 `LLMParseError`，拆分为逐节点调用
- [x] 3.2 确保 `max_rounds`、`max_accumulated_nodes`、token 预算等终止条件在批量模式下仍正确工作
- [x] 3.3 确保去重逻辑（visited 集合）在批量模式下正确：同一邻居被多个中心共享时只处理一次

## 4. LLM 调用适配

- [x] 4.1 在 `_traverse` 中构造批量 free_args：包含 `centers`（中心节点渲染文本）和 `neighbors`（候选邻居渲染文本），以及 `query` 和 `accumulated_summary`
- [x] 4.2 确认 `_render_nodes` / `ContextRenderer` 对批量 nodes_in 的渲染结果符合新模板格式要求

## 5. 测试

- [x] 5.1 添加单元测试：贪心打包逻辑（单节点、多节点、超预算截断）
- [x] 5.2 添加单元测试：邻居-中心映射与深度计算
- [x] 5.3 添加单元测试：回退到逐节点处理的场景
- [x] 5.4 添加单元测试：visited 去重在批量模式下的正确性
- [x] 5.5 运行全量测试确保无回归

## 6. 规范归档

- [x] 6.1 更新 `openspec/specs/query-pipeline/spec.md` 中阶段 ③ 的遍历策略描述
- [x] 6.2 更新 `openspec/specs/token-budget-traverse/spec.md` 中批量扩展相关 requirement
- [x] 6.3 创建 `openspec/specs/batch-neighbor-traverse/spec.md` 新规范