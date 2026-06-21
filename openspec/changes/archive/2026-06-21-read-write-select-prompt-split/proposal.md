## Why

查询引擎的事实 BFS 遍历 `QueryEngine._traverse()` 被**读、写两条管线共用**。在 [`broad-recall-select-facts`](../broad-recall-select-facts/proposal.md) 之前，两侧都硬编码 `purpose="select_facts"`：

| 路径 | 入口 | 调用链 | purpose |
|------|------|--------|:-----------:|
| **读** | `query()` | `_traverse → _call_select` | `select_facts` |
| **写** | `query_nodes()`（写管线阶段② 关联节点定位，`write_pipeline.py:159`）| **同一个** `_traverse → _call_select` | `select_facts` |

`broad-recall-select-facts` 已把读侧 `select_facts` 改为**宽召回**（宁多勿漏，读侧 overall hit@10 +0.145、comparison +0.304；实验叙述见该 change）。但因 `_traverse` 读写共用，该宽召回 prompt **同时溢出到写管线阶段② 的关联节点定位**：

- 写侧阶段② 的目的是**精确定位图中已有的相关节点**，供 `extract_concepts` / `judge_relations` 做"带已有节点对齐"（合并同义、判互斥）。
- 宽召回会把大量**弱相关节点**拉进对齐上下文 → 抬高对齐误判率（错并、错判互斥）、放大输入成本、并让建图结果对噪声敏感。
- 一旦未来 re-ingest 重建图，建图行为会被这个**未在写侧验证**的 prompt 带歪，且方向不可控。

**核心矛盾**：读侧要宽（多召回、靠后续裁剪/重排收敛），写侧要窄（高精度对齐、保护图结构）。同一个 purpose 无法同时满足。

**本变更**：把读、写两侧的事实筛选 prompt 解耦——读侧继续宽召回 `select_facts`（口径由 `broad-recall-select-facts` 定义，**本变更不改读侧 prompt**），写侧切换为独立的窄召回 `select_facts_write`，使读侧优化不再污染建图。

## What Changes

### 1. 遍历方法参数化筛选 purpose

- `QueryEngine._traverse()` 新增参数 `select_purpose: str = "select_facts"`（默认值保持读侧零行为变化）。
- 内部闭包 `_call_select` 以 `select_purpose` 作为 `llm.call` 的 `purpose`，替代当前硬编码的 `"select_facts"`。
- `query()`（读路径）不传该参数，沿用默认 `"select_facts"`。
- `query_nodes()`（写路径）调 `self._traverse(..., select_purpose="select_facts_write")`。

### 2. 新增 `select_facts_write` 窄召回 prompt

- 在 `mcs/prompts/select_facts.py` 内并列新增窄召回常量 `WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE`（窄召回口径：选最相关、优先具体信息、可返回空），复用同一个 `parse`。该口径为窄召回**改写版**而非对历史某版 prompt 的逐字复刻，措辞取舍见 design「决策 3」。
- 在 `mcs/prompts/__init__.py` 的 `DEFAULT_PROMPTS` 注册第二个 bundle `select_facts_write`（system=WRITE_SYSTEM_PROMPT、template=WRITE_USER_TEMPLATE、parse=select_facts.parse）。
- 与现有 `select_nodes` / `select_nodes_batch` 同模块多 bundle 的先例一致——两种召回口径并排放在一个文件，便于对照维护。

读侧的 `SYSTEM_PROMPT` / `USER_TEMPLATE`（宽召回）**保持不变**。

### 3. 用户覆盖正交

两个 purpose 各自可被 `MCSConfig.prompt_overrides` / `LLMInterface.register_prompt` 独立覆盖，互不影响。

## Capabilities

### Modified Capabilities
- `query-pipeline`: 阶段③ 事实 BFS 的筛选 purpose 由"硬编码 `select_facts`"改为"`_traverse` 的 `select_purpose` 参数（默认 `select_facts`）"；读路径行为不变。
- `lightweight-query`: 写管线阶段② 复用的 `query_nodes` 以 `select_facts_write`（窄召回）执行遍历，与读侧宽召回 `select_facts` 解耦。

## Impact

### 代码变更
- `mcs/core/query_engine.py`: `_traverse` 增加 `select_purpose` 参数；`_call_select` 用该参数；`query_nodes` 传 `"select_facts_write"`。读侧 `query()` 不改。
- `mcs/prompts/select_facts.py`: 新增 `WRITE_SYSTEM_PROMPT` / `WRITE_USER_TEMPLATE`（窄召回口径）。
- `mcs/prompts/__init__.py`: `DEFAULT_PROMPTS` 注册 `select_facts_write` bundle。

### API 变更
- `_traverse` 是内部方法，新增参数有默认值，**非 breaking**。
- `query()` / `query_nodes()` 公共签名不变。
- 新增一个默认 purpose `select_facts_write`，纯增量，不影响既有覆盖。

### 行为变更
- **读侧**：完全不变。本变更不改读侧 `select_facts` prompt（其宽召回口径由 `broad-recall-select-facts` 定义）；`query()` 仅因 `_traverse` 参数化获得默认值，行为逐字一致。
- **写侧**：阶段② 关联定位从（被读侧宽召回溢出污染的）共用 `select_facts` 切换为独立的窄召回 `select_facts_write`（选最相关、优先具体信息、可返回空）。对**已建好的图无影响**（写路径只在 ingest / re-ingest 触发）；未来 re-ingest 时建图回到高精度对齐口径。注：`select_facts_write` 为窄召回**改写版**（详见 design「决策 3」），非对历史 prompt 的逐字复刻，故"回到建图口径"为口径级别近似、非逐字复现。

### 测试
- 单测验证：`query()` 走 `select_facts`、`query_nodes()` 走 `select_facts_write`（mock LLM 捕获 `purpose`）。
- 单测验证：`DEFAULT_PROMPTS` 含 `select_facts_write`、其 `parse` 与 `select_facts` 行为一致。
- 单测验证：两 purpose 可被 `prompt_overrides` 独立覆盖、互不串味。
- 回归：现有 `query` / `query_nodes` / write_pipeline 测试全绿（读侧行为不变）。

### 依赖
- 无硬前置；动机上以"读侧 `select_facts` 已宽召回"为立论前提（见 [`broad-recall-select-facts`](../broad-recall-select-facts/proposal.md)），但读写拆分本身独立成立（即使读侧仍窄召回，解耦也有意义）。
- 与进行中的 `model-aware-token-estimation` 无冲突（各改各的）。

### 风险
- **低**。读侧零改动；写侧切到独立的窄召回 `select_facts_write`，使建图不再受读侧宽召回溢出污染。
- `select_facts_write` 为窄召回改写版（非历史逐字复刻，见 design「决策 3」）；若需写侧建图口径与某历史 `graph.db` 逐字一致，应单独比对 prompt 文本。
- 唯一需留意点：若将来希望写侧也享受某种"宽"策略，应单独为 `select_facts_write` 设计并在**写侧（建图质量）指标**上验证，不得直接复用读侧宽召回结论。
