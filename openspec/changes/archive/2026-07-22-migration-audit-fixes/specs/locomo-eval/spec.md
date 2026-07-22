# locomo-eval Delta

> migration-audit-fixes：D2 `bench/locomo/__main__.py` 仍传已删的 `track` 形参（`run_eval` 退役检索轨后
> 删了 `track`）致评测入口直接 `TypeError`；同步「检索轨」requirement 仍写 `mcs.query()` 的退役漂移
> ——检索改由 agent 触达节点 + `bench.plugins.doc_rerank` 离线映射。

## MODIFIED Requirements

### Requirement: 检索轨 session 级 Recall@k

检索轨 SHALL 仅对移植到 `evidence` 的题运行：**记忆 agent 触达节点**（`CapturingMemory.touched_nodes()`，含 search 种子 + associate 邻居）经 `bench.plugins.doc_rerank` 离线重排后，按 `source_tracking.sources` 的 `chunk_id`（`"session_N"`）映射为召回 session 序列（去重保序）；gold = evidence `dia_id` 的 `D{N}` 前缀集合。主指标为 any-evidence hit（gold 与 top-k 交非空），副指标 all-evidence hit；k = 5, 10, 20。

> 框架 `mcs.query(question)` 检索轨已随 retire-framework-query-pipeline 退役删除；检索 Recall@k 改由 agent
> 触达节点 + `doc_rerank` 离线映射计算。`run_eval` 签名已无 `track` 形参（`bench/locomo/__main__.py`
> MUST NOT 传 `track=`）。

#### Scenario: dia_id 映射 session

- **WHEN** 某题 `evidence == ["D1:3", "D2:8"]`
- **THEN** gold session 集合 MUST 为 `{1, 2}`

#### Scenario: 命中判定

- **WHEN** k=5 且召回 session 序列前 5 为 `[3, 1, 7, 4, 9]`，gold 为 `{1, 2}`
- **THEN** any-evidence hit MUST 为真，all-evidence hit MUST 为假

#### Scenario: 入口不传已退役的 track 形参

- **WHEN** 执行 `python -m bench.locomo eval`（经 `__main__.py` 调 `run_eval`）
- **THEN** `__main__.py` MUST NOT 向 `run_eval` 传 `track=` 形参（`run_eval` 已无该参数，传则 `TypeError`）
- **AND** argparse MUST NOT 定义 `--track` 选项（检索轨已退役，QA 轨为唯一主轨）
