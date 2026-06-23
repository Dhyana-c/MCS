# focused-candidate-selection 任务

> 当前为 **proposal / 设计阶段**：先定方案，再实现。代码任务待方案选定后展开。

## 0. 决策（先做）

- [ ] 0.1 选定首发方案：**方案 A（事后充分性裁剪，deepseek 优先）** 还是直接上方案 B / 叠加
- [ ] 0.2 定开放问题（design.md §5）：步数预算单位、充分性判据粒度、裁剪兜底阈值、模型分流
- [ ] 0.3 确认验收口径：复用 `bench/multihop_rag/scripts/agent_full_run.py` 同口径对照框架基线

## 1. 方案 A：事后充分性裁剪（若选 A）

- [ ] 1.1 新增 `mcs/prompts/select_sufficient.py`：SYSTEM/USER（输出"足以回答查询的最小聚焦子集"节点 id）+ `parse` + 非法/空兜底归一
- [ ] 1.2 `mcs/core/query_engine.py`：遍历收尾后调用充分性裁剪，只把聚焦子集交后续 doc_rerank；保留 accumulated 全集
- [ ] 1.3 兜底：聚焦子集为空 / < 阈值 → 回退 accumulated 全集（杜绝剪过头丢召回）
- [ ] 1.4 落点为可开关插件（`TRIM` / `POSTPROCESS`），支持 on/off 对照
- [ ] 1.5 测试：裁剪正常 / 空返回回退 / 超剪回退 / `accumulated ≤ T` 仍守 / 召回不降

## 2. 方案 B：有界可回访 LLM 引导遍历（若选 B / Phase 2）

- [ ] 2.1 `_traverse`：`max_steps` 步数预算取代 `max_rounds` + frontier 耗尽
- [ ] 2.2 去掉 `visited` 永久禁访；实现**回访门**（accumulated 自上次裁决后变化才准回访）+ 单节点回访次数上限
- [ ] 2.3 `select_facts` 角色语义扩展：忽略不重要点 / 标记可回访
- [ ] 2.4 进度保证测试：构造热 hub，证明不空烧步数预算
- [ ] 2.5 测试：`accumulated ≤ T` 不变量仍守；终止确定性；回访收敛

## 3. 评测与文档

- [ ] 3.1 同口径对照框架基线：reached/recall@∞ 不降 + gold 名次下降 + hit@10/recall@10 上升
- [ ] 3.2 deepseek 实测剪枝/回访行为（不早停丢召回）；必要时 GLM 对照
- [ ] 3.3 specs 合并（归档时 `openspec archive`）；`docs/graph-model-design.md` 查询流程同步
- [ ] 3.4 CLAUDE.md 查询流程描述补"聚焦候选集"（若改动影响总体流程）

## 备注

- 本 change 由 agent-vs-框架对照实验驱动，证据 / 跑批脚本见 `bench/multihop_rag/`（`scripts/agent_full_run.py`、`reports/agent_vs_framework.md`）。
- 延续 `separate-accumulate-frontier` 的"探索口径 ≠ 输出口径"解耦；本 change 治"accumulated → 最终候选集"段的聚焦度。
