## MODIFIED Requirements

### Requirement: judge_relations 输出事实边 label

本要求定义 **`property_graph` 模式**（默认）的 `judge_relations` 行为；`attribute_node` 模式见下方「attribute_node 模式 judge_relations 不产 label」。`property_graph` 模式下，`judge_relations` prompt MUST 指导 LLM 为**每条有向关系**输出一个粗粒度 label。Decision 的 `edges_to`（到已有节点）与 `edges_to_names`（到同批新概念）MUST 均为 `list[dict]`，每项含 `target_id`（或 `target_name`）与 `label`。**一条关系 = 一个方向 + 一个 label**：写入时只存一份事实边、两端可达，MUST NOT 自动生成反向 label 副本。

#### Scenario: edges_to / edges_to_names 含 label

- **WHEN** （`property_graph` 模式）`judge_relations` 返回 create 决策
- **THEN** `edges_to` MUST 为 `[{"target_id": "...", "label": "喜欢"}, ...]`；`edges_to_names` MUST 为 `[{"target_name": "...", "label": "..."}, ...]`

#### Scenario: 一条关系一个方向一个 label

- **WHEN** （`property_graph` 模式）judge_relations 判定 A 对 B 有关系"喜欢"
- **THEN** MUST 输出一条 `A→B label="喜欢"`（存一份、两端可达）；MUST NOT 自动生成 `B→A` 反向 label 副本

#### Scenario: 反向若是不同关系则为独立事实

- **WHEN** （`property_graph` 模式）A、B 间还存在方向相反、语义不同的关系（如 B 对 A 是"营养来源"）
- **THEN** 那是**另一条独立事实** `B→A label="营养来源"`（同样存一份）；二者 MAY 并存——同一对节点允许多条方向 / 语义不同的事实边

## ADDED Requirements

### Requirement: attribute_node 模式 judge_relations 不产 label

`attribute_node` 模式下，`judge_relations` SHALL 走专属 prompt（经 `prompt_overrides` 按模式注入或按模式选 purpose）：MUST NOT 输出关系 label；MUST 输出"为关系建 / 并属性节点 + 连无类型边"的决策意图（属性节点 name/content + 端点 id/name）。其 parser MUST 解析为对应决策类型，端点解析沿用 id / 同批 name 双轨。

#### Scenario: attribute_node prompt 不含 label

- **WHEN** `attribute_node` 模式调用 `judge_relations`
- **THEN** 返回决策 MUST NOT 含关系 label 字段；MUST 表达属性节点与其端点

#### Scenario: 端点 id / 名称双轨解析

- **WHEN** 关系端点为已存在节点或同批新概念
- **THEN** parser MUST 分别按 id 与按名解析（沿用 `edges_to` / `edges_to_names` 的双轨），但 MUST NOT 携带 label

---

### Requirement: attribute_node 模式 assoc 边渲染无 label

`ContextRenderer` SHALL 提供 `render_assoc_edge(edge) -> str`，将无类型关联边渲染为 `主 — 宾`（**无 label**）。`attribute_node` 模式的 `render_facts` MUST 用它平铺关联边条目；token 估算 MUST 复用 `render_assoc_edge` 同一函数（铁律一），MUST NOT 用近似公式。属性节点 MUST 按普通节点渲染（name+content）。

#### Scenario: 关联边条目格式

- **WHEN** 渲染关联边 `(小明, 小明的爱好)`
- **THEN** 输出 MUST 为 `小明 — 小明的爱好` 形式（带编号，无 label）

#### Scenario: 关联边渲染与估算同口径

- **WHEN** 估算关联边 token
- **THEN** MUST 调用 `render_assoc_edge` 同一函数再计 token，MUST NOT 用近似公式
