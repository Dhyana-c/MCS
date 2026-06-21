## Why

查询管线阶段 ③ 事实 BFS 的事实筛选 prompt（`purpose=select_facts`）原为**窄召回**口径——"选出与查询**最相关**的条目、优先直接回答查询的事实、无相关可返回空"。

MultiHop-RAG 这类多跳检索任务里，**漏掉一个 gold 文档即直接损失 hit / recall**，窄召回的保守策略导致系统性漏召；而多召回进来的噪声可由查询管线后续的 `doc_rerank` / 裁剪收敛。因此读侧筛选应**宽召回、宁多勿漏**。

在 200 条 MultiHop-RAG 上的对照实验（两次 run 共用同一份 `graph.db`，仅改读侧 `select_facts` prompt）：

| 指标 | 窄召回（原） | 宽召回（本变更） | Δ |
|------|:---:|:---:|:---:|
| overall hit@10 | 0.55 | 0.695 | **+0.145** |
| comparison | 0.367 | 0.671 | **+0.304** |

收益**仅在读侧（查询）验证**——宽召回只作用于查询路径。

> **诚实声明（重要）**：彼时 `QueryEngine._traverse()` 读写共用、且硬编码 `purpose="select_facts"`，因此这次宽召回改动**同时作用于写管线阶段 ② 的关联节点定位**（`write_pipeline` → `query_nodes` → `_traverse`），而该路径**未在写侧（建图质量）指标上验证**。宽召回对写侧"已有节点对齐"是潜在污染（拉入弱相关节点、抬高错并 / 错判互斥率）。**写侧污染的隔离由 [`read-write-select-prompt-split`](../read-write-select-prompt-split/proposal.md) 解决**（读写筛选 prompt 解耦、写侧恢复窄召回）。本 change 只负责"读侧采用宽召回"这一决定及其读侧验证收益。

## What Changes

### 1. 读侧 select_facts prompt 改为宽召回

- `mcs/prompts/select_facts.py` 的 `SYSTEM_PROMPT` / `USER_TEMPLATE` 从窄召回改为宽召回：召回口径要宽、宁可多召回交由后续裁剪、不要因"没有哪一条直接回答了查询"就漏选或返回空；候选不少于 5 条时至少返回 3 条最相关的。
- `parse` 不变（仍解析编号 JSON 数组）。

### 2. spec 记录宽召回口径

- `query-pipeline` 新增 Requirement：`select_facts` 采用宽召回口径（宁多勿漏、候选充足时下限返回）；默认 prompt bundle MUST 体现此口径。

## Capabilities

### Modified Capabilities
- `query-pipeline`：阶段 ③ 事实筛选的 `select_facts` 召回口径由（隐含的）窄召回显式化为**宽召回**。

## Impact

### 代码变更
- `mcs/prompts/select_facts.py`：`SYSTEM_PROMPT` / `USER_TEMPLATE` 改写为宽召回；模块 docstring 同步。

### 行为变更
- **读侧（查询）**：事实筛选从窄召回变为宽召回——已由 MultiHop-RAG 评测验证 +0.145 hit@10。
- **写侧（建图）**：⚠️ 因 `_traverse` 读写共用，宽召回同样作用于写管线阶段 ② 关联定位（彼时硬编码、未在写侧验证）。对**已建好的图无影响**（写路径只在 ingest / re-ingest 触发）；但未来 re-ingest 会以宽召回建图——此污染由 `read-write-select-prompt-split` 隔离。

### 测试
- 宽召回属 prompt 调参，由 MultiHop-RAG 评测验证收益，不新增专门单测（现有 `query` 测试仍绿）。

### 依赖
- 无硬前置。
- 与 `read-write-select-prompt-split` 互补：本 change 引入读侧宽召回，后者把读写筛选 prompt 解耦、使写侧不受宽召回污染。建议后者在本 change 之后归档（叙述上后者以"读侧已宽召回"为立论前提）。

### 风险
- **低（读侧）**：仅改读侧 prompt，评测已验证 +0.145 收益。
- **中（写侧，已知）**：宽召回经共用 `_traverse` 溢出到写侧、未验证——由 `read-write-select-prompt-split` 收口。
