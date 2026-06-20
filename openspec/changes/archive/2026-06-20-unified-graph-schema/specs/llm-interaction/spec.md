# llm-interaction（delta）

> 渲染与 judge 改写到单一模型：关系边渲染为 `主 — 宾`（**无 label**，关联 / 互斥）；`judge_relations` 产出"建命题节点 + 连关联边"意图、不产 label。两条 `attribute_node` 模式专属要求移除（其内容即统一模型的渲染口径，已并入）。

## MODIFIED Requirements

### Requirement: select_facts 渲染为统一编号的事实条目

`ContextRenderer` SHALL 提供 `render_facts(nodes, edges) -> str`，将节点（概念 / 命题）与关系边（`关联` / `互斥`）按**单一连续编号**（①②③… 跨节点与边单调递增、节点在前边在后）平铺：节点为 `① name (id=xxx)\n  content`，关系边为 `② 主 — 宾`（**无 label**）。框架 MUST 维护「编号 → 节点 / 边」映射供 parser 回查。关系边渲染 MUST 与 token 估算共用同一函数（铁律一）。`select_facts` prompt MUST 指导 LLM 返回选中编号列表。

#### Scenario: 关系边条目无 label

- **WHEN** 渲染关联边连 `小明` 与命题节点
- **THEN** 输出 MUST 为 `小明 — <命题>` 形式，MUST NOT 含 label

#### Scenario: 估算复用渲染函数

- **WHEN** 估算关系边 token
- **THEN** MUST 调用渲染关系边的同一函数再计 token，MUST NOT 用近似公式

#### Scenario: parser 回查编号

- **WHEN** LLM 返回选中编号
- **THEN** parser MUST 返回 `list[int]`，框架据编号映射回节点 / 边

### Requirement: judge_relations 产命题节点 + 关联边（不产 label）

`judge_relations` prompt MUST 指导 LLM 把关系判定为**建 / 复用命题（事实）节点 + 连 `关联` 边**（谓词落命题节点 `content`），MUST NOT 产出关系 `label`、MUST NOT 按 `relation_model` 分模式。互斥 MUST 表示为两个事实节点间的 `互斥` 边。Decision 的 `edges_to` / `edges_to_names` MUST NOT 含 `label` 字段。

#### Scenario: 关系判定不产 label

- **WHEN** `judge_relations` 判定两节点有关系
- **THEN** 决策 MUST 表达"建 / 并命题节点 + 连关联边"意图，`edges_to` / `edges_to_names` MUST NOT 含 `label`

#### Scenario: 不同方向 / 语义的关系各建命题

- **WHEN** A 与 B 之间有多种关系
- **THEN** 每种关系 MUST 各建一个命题节点（各自 content），MUST NOT 用多 label 边表达

## REMOVED Requirements

### Requirement: attribute_node 模式 judge_relations 不产 label

**原因**：单一模型，judge_relations 统一不产 label（见上 MODIFIED），无模式分支。

### Requirement: attribute_node 模式 assoc 边渲染无 label

**原因**：关系边统一渲染为 `主 — 宾`（无 label）已并入「select_facts 渲染」；无模式分支。
