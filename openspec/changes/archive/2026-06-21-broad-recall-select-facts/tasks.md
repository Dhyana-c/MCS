## 1. 读侧 select_facts prompt 改宽召回

- [x] 1.1 `mcs/prompts/select_facts.py` 的 `SYSTEM_PROMPT` 改为宽召回（召回口径要宽、宁多勿漏、勿因"无直接回答"漏选或返空）
- [x] 1.2 `USER_TEMPLATE` 改为宽召回（返回**可能相关**编号列表、宽召回宁多勿漏）
- [x] 1.3 候选 ≥5 条时至少返回 3 条最相关
- [x] 1.4 模块 docstring 同步（读侧宽召回口径）

## 2. spec 记录宽召回口径

- [x] 2.1 `openspec/changes/broad-recall-select-facts/specs/query-pipeline/spec.md` 新增 Requirement「select_facts 采用宽召回口径」+ scenarios（ADDED）
- [x] 2.2 `openspec validate broad-recall-select-facts --strict` 通过

## 3. 验证

- [x] 3.1 MultiHop-RAG 200 条对照：overall hit@10 +0.145、comparison +0.304（已验证）
- [x] 3.2 现有 `query` 测试全绿（宽召回 prompt 文案不破坏既有测试）
