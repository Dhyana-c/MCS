# Design — dedup-fact-merge

## 决策：区分「聚类裂变」与「后台去重」

原规范「事实 MUST NOT 走合并去重」把两类操作混为一谈。二者本质不同：

| 操作 | 触发 | 合并对象 | 合并事实的后果 |
|------|------|----------|----------------|
| **聚类裂变**（fanout_reducer / decide_hub） | 节点邻域超 T | 语义邻域内的节点 | 抹掉事实身份、断事件背书 / 互斥——**禁止** |
| **后台去重**（dedup_maintenance） | 外部调度扫描 | 同名字面重复节点 | 多为同一命题的重复抽取，合并合理；背书 / 互斥边可重挂 |

放开后台去重合并同名字面事实，保留聚类裂变禁令。

## 安全闸：互斥对不合并

合并 dup→target 前，`DedupMaintenance._has_mutex_between(store, target_id, dup_id)` 判定两节点是否互为互斥（任一方向 `互斥` 边）。是则跳过——避免：

- **自互斥塌缩**：合并后 dup→target 的互斥边变成 target→target 自环（add_edge 自环返回空串），矛盾语义丢失。
- **矛盾塌缩**：两条相互矛盾的事实被合成一条，矛盾信息消失。

非互斥的同名事实（多为重复抽取）正常合并，背书 / 互斥边（对其它节点）经 `get_relations` + `get_related_events` 重挂到 target，add_edge 按 (source,target,type) 去重保「一条只存一份」。

## 已知代价

- **同名异义误并**：Phase1 仅字面同名识别，同名但异义的非互斥事实仍可能被合并（如两条同名但说法不同、未标记互斥的事实）。同义判定留 Phase 2（embedding / LLM）。
- 这是「同名未必同义」既定风险的延伸，与概念去重同源；dedup 为可选后台扫描（`should_run` 默认 False），由外部调度控制触发，非写入热路径。

## 不影响的不变量

- **聚类裂变对事实仍只重组不合并**（fanout_reducer `_reorganize_multi` 按 node_class 拆分：concept 走 merge、fact 走 reorganize）——本 change 不动聚类路径。
- **核心有界性**：dedup 合并同样过守门（合并后 target token 超 T 则挂起跳过该对）。
