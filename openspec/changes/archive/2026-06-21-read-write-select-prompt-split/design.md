# Design — 读写事实筛选 prompt 解耦

## 背景与约束

事实 BFS 遍历是读写共用资产：写管线阶段② "关联节点定位" 复用查询引擎（见 `lightweight-query` 规范），通过 `query_nodes()` 进入与读侧 `query()` **同一个** `_traverse()`。两者唯一的语义分歧在于"如何从候选事实条目中选"：

- **读（查询）**：召回导向。漏掉一个 gold 文档即损失 hit/recall；噪声由后续 `doc_rerank` / 裁剪收敛。→ **宽召回**最优（已实验证实 +0.145 hit@10）。
- **写（建图）**：精度导向。阶段② 的产物喂给 `extract_concepts` / `judge_relations` 做"已有节点对齐"；拉进弱相关节点会抬高错并 / 错判互斥率、污染图结构。→ **窄召回**最优。

宪法相关约束：写侧"带已有节点对齐"是合并同义、判互斥的依据（总流程 ③）；建图正确性属核心代码，宁可少对齐也不要错对齐（铁律精神）。

## 决策 1：用参数透传 `select_purpose`，不复制 `_traverse`

**选定**：`_traverse(seeds, query, ctx, select_purpose="select_facts")`，闭包 `_call_select` 使用之；`query_nodes` 传 `"select_facts_write"`。

理由：
- `_traverse` 逻辑庞大（四工作区、贪心分批、read-repair、批量回退）。复制一份给写侧会立刻产生两份需同步维护的核心遍历代码——违背最小改动、且极易腐化。
- 读写差异**只在 prompt purpose 这一个点**，参数化是表达该差异的最小手段。
- 默认值 `"select_facts"` 保证读路径（`query()` 不传参）逐字不变。

**否决的替代**：
- *配置开关*（`MCSConfig` 里加 flag）——把"读 vs 写"这种结构性分流放进运行时配置，语义错位，且会让 `_traverse` 依赖 config，耦合更深。
- *在 LLM 层按调用方切换*——`LLMInterface` 无从知道调用来自读还是写，且会破坏 purpose 即契约的清晰性。

## 决策 2：窄召回 prompt 作为同模块第二组常量，而非新文件

**选定**：`select_facts.py` 内并列 `WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE`，`__init__.py` 注册 `select_facts_write` bundle，复用 `select_facts.parse`。

理由：
- 已有先例：`select_nodes.py` 一个模块同时支撑 `select_nodes` 与 `select_nodes_batch` 两个 bundle（`__init__.py:77-86`）。
- 两种召回口径并排同文件，diff 一眼可对照"宽 vs 窄"的措辞差异，维护成本最低。
- 输出格式（编号 JSON 数组）完全相同，`parse` 必须复用——分文件反而要么重复 `parse` 要么交叉 import。

**否决**：单独 `select_facts_write.py`——会和 `select_facts.py` 交叉 import `parse`，或重复实现 `parse`，无收益。

## 决策 3：写侧窄召回口径（改写版，非历史逐字复刻）

写侧 `WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE` 采用**窄召回**口径（选最相关、优先具体信息、可返回空），方向与 `broad-recall-select-facts` 之前的窄召回 `select_facts` 一致，但**不是对历史措辞的逐字复刻**，而是按"写侧已有节点对齐"场景重新组织的改写版。

与历史窄召回 `select_facts`（即建当前 `graph.db` 所用的版本）的差异及取舍：

| 维度 | 历史窄召回（建 graph.db） | 本变更 `WRITE_*` | 取舍 |
|------|------|------|------|
| 场景定位 | 无（通用筛选） | 明确"供已有节点对齐使用" | 写侧任务更明确，有助于 LLM 聚焦对齐 |
| "返回编号列表即可"说明句 | 有 | 删 | 输出格式已由 template 约束，避免冗余 |
| "已经选过的内容不要重复纳入" | 有 | 删 | ⚠️ 见下文说明 |
| "无足够相关可不选" | template 侧有 | system+template 双侧强调 | 强化窄召回"高精度、敢返回空" |

**关于删除"已经选过的内容不要重复纳入"**：该提示在读路径（material 含 `accumulated_summary`）有去重价值；写侧 `query_nodes` 默认 `max_rounds=1`、且阶段② 对齐关注"图中已有节点"而非多跳累积，去重压力小，故删去以简化 prompt。若未来写侧出现重复纳入问题，应作为独立调参项补回、并在写侧指标上验证。

**可复现性说明**：因 `WRITE_*` 为改写版，未来 re-ingest 建图口径与当前 `graph.db` **在窄召回这一口径级别一致、但非逐字相同**。对已建图无影响；若需与某历史 `graph.db` 逐字对齐，须单独比对 prompt 文本。proposal 的 Impact / 风险已据此弱化"回到建图口径"措辞。

**否决的替代**：逐字复刻历史窄召回 prompt——会让"供已有节点对齐使用"这一写侧专属上下文无处安放，且把当时未经"写侧对齐"视角审视的措辞原样带回，不如按写侧场景重新组织。

## 影响面与正确性

- **读路径**：`query() → _traverse()`（默认 purpose）→ 与现状逐字一致。
- **写路径**：`query_nodes() → _traverse(select_purpose="select_facts_write")` → 阶段② 关联定位用窄召回。
- **守门 / 不变量**：本变更只改"选哪些候选"的 prompt，不触碰 token 估算、渲染、裁剪、聚类裂变——铁律一/二、活跃视图不变量均不受影响。
- **用户覆盖**：`select_facts` 与 `select_facts_write` 是两个独立 purpose，`prompt_overrides` 可分别覆盖，互不影响。

## 验证策略

- prompt 分流：mock `LLMInterface.call` 捕获 `purpose`，断言 `query()` 出现 `select_facts`、`query_nodes()` 出现 `select_facts_write`。
- 注册表：断言 `DEFAULT_PROMPTS["select_facts_write"]` 存在且 `parse is select_facts.parse`。
- 覆盖正交：覆盖其一不影响其二。
- 回归：读写既有测试全绿。
- （实现后）若 re-ingest 重建图：在**建图质量 / 写侧**指标（而非读侧 hit@k）上对比窄 vs 宽，确认窄召回精度优势。
