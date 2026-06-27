# Tasks — dedup-fact-merge

- [x] 1. 规范放宽：`openspec/specs/unified-graph-schema/spec.md`「图质量最终收敛」requirement 事实去重条款（MUST NOT → MAY 合并同名字面 + 互斥对跳过）；聚类裂变条款不动。
- [x] 2. 文档同步：`docs/graph-model-design.md` §5.1 收敛表「事实去重」bullet 区分聚类 / 去重；§7 加「后台去重合并事实的边界」代价。
- [x] 3. 代码（随 review 修复 D3 一并落地）：`dedup_maintenance.py` 构造器接线（`__init__(config)` + `initialize` 读 `context.token_budget`）+ 合并前互斥安全闸 `_has_mutex_between`。
- [x] 4. 测试：`tests/test_dedup_maintenance.py` 新增「同名事实合并」「互斥对跳过合并」用例；`tests/test_fanout_reducer.py` 聚类不合并事实用例保持绿（聚类路径未改）。
