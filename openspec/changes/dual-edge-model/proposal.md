## Why

`dual-edge-model` 初版只解决"给边加 label"，但实测把我们推到更根本的重构：

- **富 content 退化**：把关系叙述塞进节点 content，每节点 token 24→81（×3.4），BFS 每轮候选 ~260→~187，候选召回 0.438→0.188 腰斩。→ **content 不该承载关系语义**。
- **embedding 不稳**：实测向量检索在精确匹配 / 稀有词 / 实体 / 极性上常不如字面（grep），不能作主力检索。
- **定位回归**：MCS 是**给 agent 的仿人有界记忆引擎**。"事实 / 概念过多"的答案不是"存全 + 检索"，而是**归纳 + 遗忘**。窗口约束不是要绕开的限制，是**触发归纳 / 遗忘的容量压力**。

因此本变更把"双边模型"扩写为**有界记忆 + 事实模型**：关系以带 label 的**事实边**承载、可两端反查；节点视野按**活跃双向视图**有界（非存储有界）；溢出靠**降权 / 遗忘**而非索引；入口靠**字面 foothold + 反查 + 多种子**。

## What Changes

- **边模型**：全图两类边——
  - **层级边** `父→子`：单向、无 label、结构骨架，驱动导航下钻与 gist hub（`role="hub"` 识别）。
  - **事实边** `主 —谓→ 宾`：带 label 的命题，承载关系语义与极性。**一条事实只存一份，但两端邻接都能索引到它**（支持反查）。每条事实带 **priority/activation** 分。
- **content 精简**：节点 content = 裸定义 + 短叶子属性（≈ lean 基线，**非** 200 字符）；关系一律上事实边；属性一旦有对外关系即**升格为概念**。
- **BREAKING · 核心不变量修订**：从"节点 + 全部一跳子节点 ≤ T"改为「**任意节点的活跃双向视图 ≤ T**」——渲染时取 top-priority 的 {出事实 + 入事实（反查）+ 层级邻居}，截断到 ≤ T。**"有界"指活跃 / 渲染视图，不指存储。**
  - 出边侧（节点自有事实 / 子节点）：可 fanout 聚成 gist hub。
  - 入边侧（指向该节点的前驱）：**不聚类**（会坏归属语义），仅按 priority 截断。
  - 估算邻域 token **必须计入事实 token 且与渲染同口径**（铁律一）。
- **遗忘 = 降权（Phase 2）**：遗忘是 activation 衰减（最近性 + 频率 + 重要性），**非删除**；数据留存、沉到活跃窗口之下，可被多种子扩散激活重新捞起。Phase 1 只预留 priority 字段与排序，不实现衰减策略，且**不建任何溢出索引**（与未来遗忘架构对立）。
- **查询**：入口 = **jieba 切词 + 字面匹配概念名 / 别名**（主力，embedding 仅纯换说法兜底，root 仅孤儿 / 最后退路）；**反查 + 多种子**让入口只需"一个 foothold"；遍历 = **事实 BFS**，每节点活跃双向视图 ≤ T（priority 截断），**按层级分批**（每层 ≤ T，富余合并）、**短边选事实**；检索 **entity-anchored**（找实体作任一端的事实），**不按谓词过滤**；否定 / 极性由 **LLM 在检索回的正面 label 事实上现推**，不存"否定事实"。
- **写入**：`judge_relations` 输出带 label 的事实边；**root 关联可选**——概念仅在与任何其他概念**零关联**时才挂 root（孤儿之家），有关联者经关联可达。

- **DROP**（相对初版）：边"降级不删除"、跨集 `select_facts` 浮现、`estimate_edge` 近似公式、`neighbor / relationship` 旧命名。

## Capabilities

### New Capabilities
- `dual-edge-model`：层级边 + 事实边双模型；事实边两端可达 / 反查、存一份两头索引、带 priority。

### Modified Capabilities
- `subgraph-bounding`：核心不变量 → 活跃双向视图 ≤ T；有界指活跃视图非存储；out 聚 hub / in 优先级截断；估算计入事实 token。
- `query-pipeline`：jieba 入口 + 反查 + 多种子；事实 BFS + 分层分批 + 短边选事实；entity-anchored；否定靠 LLM。
- `store-interface`：事实边两端索引 + 反查方法 + priority 字段 + 按 activation 排序。
- `write-pipeline`：content 精简；judge_relations 出 label；root 关联可选（只挂孤儿）。
- `llm-interaction`：judge_relations 出 label；select_facts 渲染事实条目。

## Impact

- **核心模型** (`mcs/core/graph.py`)：`Edge` 增 `label`、`kind`（hierarchy | fact）、`priority`；`Subgraph` 复用既有定义。
- **存储层** (`mcs/stores/*`)：事实边两端邻接索引、反查、priority 持久化与排序；schema 变更需 rebuild。
- **Token 预算** (`mcs/core/token_budget.py`)：邻域估算计入事实 token，render-consistent；新增 fact 渲染估算（共用渲染函数，非近似公式）。
- **查询引擎** (`mcs/core/query_engine.py`)：事实 BFS、双向活跃视图、分层分批、短边选事实、entity-anchored。
- **写入管线** (`mcs/core/write_pipeline.py`)：精简 content、label 事实边、root 可选挂孤儿。
- **hub / fanout** (`mcs/plugins/maintenance/fanout_reducer.py`)：只整理活跃集；out 聚 hub、in 不聚；估算含事实 token。
- **入口** (`mcs/plugins/entry/*`)：jieba foothold 入口、反查、多种子。
- **Prompt** (`mcs/prompts/*`)：judge_relations 出 label、extract_concepts 控长、select_facts 渲染。
- **宪法** (`CLAUDE.md`)：核心不变量修订为**提议**（见 design D7），评审通过后再改。
- **评测** (`bench/`)：适配新 schema，rebuild DB。
