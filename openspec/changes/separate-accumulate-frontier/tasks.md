# separate-accumulate-frontier 实现任务

## 1. select_facts prompt 与解析（双角色）

- [x] 1.1 `mcs/prompts/select_facts.py`：读侧 `SYSTEM_PROMPT` / `USER_TEMPLATE` 改为输出双角色 `{"result": [...], "frontier": [...]}`；明确 `结果` 口径偏宽（对回答有贡献即标，仅明显纯跳板单标 `探索`）、保留"候选≥5 至少 top-3 标结果"下限
- [x] 1.2 `mcs/prompts/select_facts.py`：`parse` 返回结构化结果（`result_idx`, `frontier_idx`）；旧 flat-array 归一为"两者"（result==frontier）；非法格式仍抛 `LLMParseError`
- [x] 1.3 写侧 `WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE` 保持不变（仅靠 1.2 兼容归一）

## 2. _traverse 角色路由（query_engine.py）

- [x] 2.1 `_call_select`：适配 `parse` 新返回类型（结构化结果 / None）
- [x] 2.2 `_consume`：按角色分流——`结果`→accumulated（`used_tokens += estimate_node`）；`探索`→frontier（不计 token）；选中者均入 visited；事实边端点归属随边角色
- [x] 2.3 批量分支与逐节点回退分支均按 2.2 路由（保持 `batch-neighbor-traverse` 回退语义）
- [x] 2.4 `next_frontier` 仅由 `探索`/两者 构成；`_traverse` 返回值仍只含 accumulated（frontier 弃）
- [x] 2.5 `_node_view`：无 children 且无 facts 时，**未裁决**（不在 visited）的中心返回 `([node], [])`、**已 visited** 的叶子仍返回 `(None, None)`（修法 A' scoped——只救种子等未裁决无视图中心，不空转 re-eval 已裁决叶子）；确认 `render_facts([node], [])` 渲染非空。**注**：`_node_view` 改为读 `_traverse` 的 `visited` 闭包，**仅无视图分支查 visited**；有视图分支照常返回视图、不查 visited（否则 `探索` 节点恒在 visited 将永不展开，`探索` 角色失效）

## 3. frontier 安全阀

- [x] 3.1 `QueryEngine.__init__`：新增 `max_frontier_nodes: int = 500`
- [x] 3.2 `_traverse`：构建 `next_frontier` 时检查——单轮 `next_frontier` 规模达 `max_frontier_nodes` 即停止继续入队（当前轮 `结果` 照常进 accumulated，非整体终止；区别于 `max_accumulated_nodes` 的整体终止）

## 4. 种子语义（修正 drift：只进 frontier）

- [x] 4.1 `query_engine.py:312-321`：种子初始化改为**只进 `frontier`**（去重），移除 `accumulated.append(seed)` / `visited.add(seed)` / `used_tokens += estimate_node(seed)`；`used_tokens` 起步 0
- [x] 4.2 确认首轮 `_node_view(seed)` 把种子放 `view_nodes[0]`，LLM 双粒度评估后按 §2 路由（标 `结果` → accumulated+visited；标 `探索` → next_frontier+visited）

## 5. 测试

- [x] 5.1 `tests/`：更新现有断言 `select_facts.parse` 返回 list[int] 的单测 → 新结构化返回
- [x] 5.2 新增 `select_facts.parse` 单测：对象双数组 / flat-array 兼容（归一为两者）/ 非法格式抛错
- [x] 5.3 新增 `_consume` 角色路由单测：`结果`入 accumulated 吃 T、`探索`入 frontier 不吃 T、两者入双方、事实边端点随角色、visited 防重
- [x] 5.4 新增 frontier 安全阀单测：超 `max_frontier_nodes` 停止入队
- [x] 5.5 回归：`query_nodes`（写侧 `select_facts_write`）行为逐字等价（flat-array 归一为两者）
- [x] 5.6 回归：`accumulated ≤ T` 不变量仍守（`结果` 增量计 token）
- [x] 5.7 运行全量测试确认无回归
- [x] 5.8 种子语义测试（对应 §4）：① 种子首轮标 `结果` 能进 accumulated（验证种子不进初始 `visited`——否则被 `_consume` `if not in visited` 跳过，确定性约束）；② 首轮 LLM 全标 `探索`（无 `结果`）→ accumulated 为空 → 返回空 Subgraph 不崩；③ 常规 query 仍能召回（展开驱动）；④ 孤立/叶子种子（无视图，`_node_view` 原返回 `None`）仍能被 LLM 评估、标 `结果` 进 accumulated（验证 A'，关掉静默丢弃回归）

## 6. 文档与规范

- [ ] 6.1 `openspec/specs/query-pipeline/spec.md`：合并本 change 的 MODIFIED / ADDED requirement（**归档时** `openspec archive` 执行）
- [ ] 6.2 `openspec/specs/token-budget-traverse/spec.md`：合并本 change 的 MODIFIED / ADDED requirement（**归档时** `openspec archive` 执行）
- [ ] 6.3 归档时确认 `CLAUDE.md` 查询流程描述 / `docs/graph-model-design.md` 与"探索 vs 结果双角色"一致（代码文档统一）
