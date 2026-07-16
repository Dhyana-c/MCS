# Implementation Tasks

> 前置阅读：`bench/multihop_rag/reports/agent_build_20260715.md`（取证）与
> `bench/multihop_rag/scripts/exp_time_rule_ab.py`（TREATMENT prompt = 实现底稿，A/B 已验证）。

## 1. prompt 精确化（核心）

- [x] 1.1 `mcs/prompts/extract_concepts.py`：SYSTEM/USER 时间归属段按 design D1 重写——"事件性命题禁令"收窄为相对/单次/未完成时间；带固定历史时间的已完成世界发生 MUST 可抽为历史事实命题（时间留 content）；清单/汇总内容 MUST 逐条抽取、禁聚合概括。以 `exp_time_rule_ab.py` TREATMENT prompt 为底稿。
- [x] 1.2 复核 `judge_relations` prompt 无与新边界冲突的表述（预期零改动，确认即可）。

## 2. 规范 / 宪法同步

- [x] 2.1 主 spec `openspec/specs/unified-graph-schema/spec.md`：按本 change delta 精确化「概念 content 零时间…」requirement（归档时同步）。
- [x] 2.2 `CLAUDE.md` 宪法：时间归属相关表述同步（"事件性命题"边界精确化，一两句）。
- [x] 2.3 `docs/graph-model-design.md`：§7 已知边界更新（"文档语料时序覆盖丢失"标记为已修，注明判据）。

## 3. 测试（含边界）

- [x] 3.1 历史事实命题可抽：mock 抽取行为断言（prompt 文本含新边界表述；解析路径不变）。
- [x] 3.2 个人记忆语料不回归：既有时间归属测试全绿（相对时间仍禁、概念零时间仍禁）。
- [x] 3.3 真实 LLM 探针（可选、带 API key 时）：裁员片段抽取含逐条公司事实；普通短文档抽取量不暴涨。
- [x] 3.4 回归锚：`exp_time_rule_ab.py` control 组重跑（改后 prompt）裁员清单文档节点数 ≥ 200（对照 treatment 357 / 旧 control 67）。

## 4. 验证与验收

- [x] 4.1 `openspec validate real-narrative-events --strict` 通过。
- [x] 4.2 `.venv\Scripts\python.exe -m pytest -q` 全绿。
- [ ] 4.3 （后续验证项，不阻塞归档）multihop agent 图全量重建 + 200 case 对照——量化检索收益（预期收复 20 丢失题的大部分）。
