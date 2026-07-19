## Phase 1: 锚点解析规则

### T1: prompt 规则
- [x] `mcs/prompts/extract_work_events.py` SYSTEM_PROMPT 增加锚点解析例外：
  - 锚点在场 + 相对表述 + 日精度可确定 → `narr_timestamp` = ISO 日期（正例：锚点 8 May, 2023 + "yesterday" → "2023-05-07"）
  - 确定不了具体某天 → 保留原文形态（宁缺毋滥）
  - 无锚点 / 作品纪年 → 原规则原文保留，零行为变化

### T2: 测试（`tests/test_work_event_anchor_resolution.py`）
- [x] prompt 防回归：SYSTEM_PROMPT 含锚点解析规则（ISO 正例）且仍含"保留原文形态 / 不换算"底线
- [x] parse 兼容：LLM 返 ISO `narr_timestamp` → `WorkEventDraft.narr_timestamp == "2023-05-07"` 原样透传
- [x] 端到端可排序：mock LLM 返 ISO draft → ingest（带 work_id）→ 事件 `event_meta.timestamp` 为 ISO 且 `timestamp_sort_value` 非 -inf；`narrative_timeline` 按日期升序
- [x] 行为不变：mock 返原文形态（"last week" / "建安五年"）→ 原样落图、排序垫底（与现行为一致）

### T3: 验证
- [x] 全量回归 `pytest -q`（1315 passed）
- [x] LoCoMo 冒烟重跑（conv-26 前 2 会话 force 重建）：`sortable_ratio` 0.0→0.286、`timestamp_samples` 出现 "2023-05-07" / "2023-05-20"（连 last Saturday 周几算术都对）、agent 答出 2023-05-07、judge_correct false→**true**——端到端翻正

## 依赖关系

```
T1 → T2 → T3
```

下游：`conversational-memory-bench` tasks T0 引用本 change；本 change 归档后 LoCoMo temporal 类可跑"修复后"口径。
