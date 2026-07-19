# query-pipeline Spec Delta — retire-framework-query-pipeline

> **整体退役**：`query-pipeline` capability 定义的核心即"读流程 5 段固定管线"（`QueryEngine.query()`）。本 change 删除该编排后，capability **全部 18 条 requirement REMOVED**。存活的图导航 / 遍历原语（locate_seeds / `_traverse` / ENTRY·TRIM 链 / frontier-accumulated 解耦 / 瘦身 QueryContext）**迁移到 `lightweight-query`**（见该 capability 的 ADDED delta）——`seed-selector-plugin` 已是 REMOVED 状态、不可收纳。
>
> 归档时 `openspec/specs/query-pipeline/` 整目录从 main spec 移除。

## REMOVED Requirements

以下 18 条 requirement 随 `QueryEngine.query()` / `MCS.query()` 5 阶段编排的删除而整体退役（查询职责转移至记忆 agent 的 `search` / `associate` / `reason` 分步游走）：

### Requirement: 读流程为 5 段固定管线
### Requirement: 阶段 ① 使用独立的 PreprocessPlugin 类型
### Requirement: query 默认返回 Subgraph
### Requirement: 多轮驻留节点跳过种子定位
### Requirement: 入口为字面 foothold + 反查 + 多种
### Requirement: 短边优先选事实
### Requirement: entity-anchored 检索，否定由 LLM 现推
### Requirement: 入口插件链累积合并并按优先级排序
### Requirement: 顶点导航兜底作为最低优先级入口插件
### Requirement: 种子裁剪使用 TrimPlugin 链
### Requirement: 语义理解 Loop 为 BFS 且维护 visited 集合
### Requirement: 语义理解 Loop 的安全阀
### Requirement: 语义理解 Loop 使用 select_facts 筛选候选
### Requirement: 仲裁单一职责且每条管线至多一个
### Requirement: 后置处理链开放可串联
### Requirement: QueryContext 含四个状态字段
### Requirement: select_facts 采用宽召回口径
### Requirement: frontier 与 accumulated 解耦

> 其中 #5/#8/#9/#10/#11/#12/#13/#18 共 8 条描述的原语**存活**，正文以 ADDED 形式落到 `lightweight-query` delta（Purpose 拓宽为"QueryEngine 图导航+遍历原语"）。#16 QueryContext 瘦身后亦 ADDED 到 lightweight-query（`result_set`/`intermediate` 字段随 query() 去，保留 `system_prompt`/`user_input`/`universe`/`metadata` 供 locate_seeds 与 ENTRY/TRIM 接口使用）。
