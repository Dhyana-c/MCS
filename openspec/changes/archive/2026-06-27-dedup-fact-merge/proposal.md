## Why

`unified-graph-schema` 原规范「事实 MUST NOT 走合并去重」与 `DedupMaintenance` 后台维护扫描的实现冲突：dedup 扫描按 name 分组核心节点（含事实）并合并同名重复。规范把「聚类裂变」与「后台去重」两类操作一刀切禁止合并事实，但二者语义不同：

- **聚类裂变**（fanout_reducer）：对超 T 的语义邻域重组——合并事实会抹掉事实身份、断事件背书 / 互斥，**必须禁止**。
- **后台去重**（dedup_maintenance）：合并同名字面重复（Phase1 仅字面识别，同义判定留 Phase 2）——对同名事实（多为同一命题的重复抽取）合并是合理的去重，背书 / 互斥边可重挂保留。

规范应区分这两类操作：放开后台去重对同名字面事实的合并，同时保留聚类裂变的禁令不变。

## What Changes

- **规范放宽（仅 dedup 上下文）**：`unified-graph-schema`「图质量最终收敛」requirement 由「事实 MUST NOT 走合并去重」改为「事实去重按'同主·同宾·同说法'对齐；后台维护扫描 MAY 合并同名字面事实（背书 / 互斥边重挂）；互为互斥的两事实 MUST NOT 合并（避免自互斥 / 矛盾塌缩）」。
- **聚类裂变禁令不变**：守门 requirement 中「聚类对事实 MUST 只重组不合并」逐字保留——聚类与去重是不同操作。
- **dedup 安全闸（代码已落地）**：`DedupMaintenance` 合并前用 `get_edges_between` 判定 dup↔target 是否互为互斥，是则跳过（避免自互斥 / 矛盾塌缩）。
- **文档同步**：`docs/graph-model-design.md` §5.1 收敛表「事实不走合并」bullet 改为区分聚类 / 去重；§7 加「后台去重合并事实的边界」代价。

## Capabilities

### Modified Capabilities

- `unified-graph-schema`：
  - 「图质量最终收敛（去重 / 合并）」requirement：事实去重条款由 MUST NOT 改为「后台去重 MAY 合并同名字面事实 + 互斥对跳过」；聚类裂变条款（守门 requirement）不变。

## Impact

- **代码**：`mcs/plugins/maintenance/dedup_maintenance.py` 已实现同名事实合并 + 互斥安全闸（本 change 同期随 review 修复 D3 一并落地）；聚类路径 `fanout_reducer.py` 不动。
- **测试**：`tests/test_dedup_maintenance.py` 断言同名事实**被合并** + 互斥边重挂 + **互为互斥的两事实跳过合并**；`tests/test_fanout_reducer.py` 聚类不合并事实用例不受影响（聚类路径未改）。
- **文档**：`docs/graph-model-design.md` §5.1 / §7、`openspec/specs/unified-graph-schema/spec.md` 同步。
- **不变量**：核心有界性（活跃视图 ≤ T）不受影响——dedup 合并同样过守门（合并后超 T 则挂起跳过），聚类裂变禁令完整保留。
