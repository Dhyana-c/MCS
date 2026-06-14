## MODIFIED Requirements

### Requirement: purpose 枚举固定且与流程位置对应

`purpose` SHALL 为固定命名集合之一。Phase 1 MUST 至少支持：`extract_concepts`、`judge_relations`、`decide_directions`、`decide_hub`、`navigate_hub`、`arbitrate`、`synthesize`、`gen_aliases`、`gen_summary`、`select_facts`。

#### Scenario: purpose 含 select_facts

- **WHEN** 检查 LLMInterface 与文档
- **THEN** `select_facts` MUST 被定义为独立 purpose；其渲染 MUST 将候选节点与事实边统一编号平铺为事实条目

#### Scenario: 未注册 purpose 报错

- **WHEN** 传入未注册 `purpose`
- **THEN** 框架 MUST 抛明确错误，不静默回退

---

## ADDED Requirements

### Requirement: select_facts 渲染为统一编号的事实条目

`ContextRenderer` SHALL 提供 `render_facts(nodes, edges) -> str`，将节点与事实边按**单一连续编号**（①②③… 跨节点与事实边单调递增、节点在前事实边在后）平铺：节点为 `① name (id=xxx)\n  content`，事实边为 `② 主 —label→ 宾`。框架 MUST 维护「编号 → 节点 / 事实边」映射，供 parser 回查。事实边渲染 MUST 与 token 估算共用同一函数（铁律一）。`select_facts` prompt MUST 指导 LLM 返回选中的事实编号列表。

#### Scenario: 事实边条目格式

- **WHEN** 渲染事实边 `(小明, fact, "喜欢", 苹果)`
- **THEN** 输出 MUST 为 `② 小明 —喜欢→ 苹果` 格式（带编号）

#### Scenario: 渲染与估算同口径

- **WHEN** 估算事实边 token
- **THEN** MUST 调用渲染事实边的同一函数再计 token，MUST NOT 用近似公式

#### Scenario: parser 返回编号列表

- **WHEN** LLM 返回 `[1, 3, 4]`
- **THEN** parser MUST 返回 `list[int]`，框架据编号映射回节点 / 事实边

---

### Requirement: judge_relations 输出事实边 label

`judge_relations` prompt MUST 指导 LLM 为**每条有向关系**输出一个粗粒度 label。Decision 的 `edges_to`（到已有节点）与 `edges_to_names`（到同批新概念）MUST 均为 `list[dict]`，每项含 `target_id`（或 `target_name`）与 `label`。**一条关系 = 一个方向 + 一个 label**：写入时只存一份事实边、两端可达，MUST NOT 自动生成反向 label 副本。

#### Scenario: edges_to / edges_to_names 含 label

- **WHEN** `judge_relations` 返回 create 决策
- **THEN** `edges_to` MUST 为 `[{"target_id": "...", "label": "喜欢"}, ...]`；`edges_to_names` MUST 为 `[{"target_name": "...", "label": "..."}, ...]`

#### Scenario: 一条关系一个方向一个 label

- **WHEN** judge_relations 判定 A 对 B 有关系"喜欢"
- **THEN** MUST 输出一条 `A→B label="喜欢"`（存一份、两端可达）；MUST NOT 自动生成 `B→A` 反向 label 副本

#### Scenario: 反向若是不同关系则为独立事实

- **WHEN** A、B 间还存在方向相反、语义不同的关系（如 B 对 A 是"营养来源"）
- **THEN** 那是**另一条独立事实** `B→A label="营养来源"`（同样存一份）；二者 MAY 并存——同一对节点允许多条方向 / 语义不同的事实边
