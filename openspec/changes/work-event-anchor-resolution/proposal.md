## Why

LoCoMo bench 的 deepseek 冒烟**端到端实证**了 ③b 作品叙事事件抽取的一个缺口：对话语料每行自带显式时间锚点（`[1:56 pm on 8 May, 2023] Sarah: I went to a LGBTQ support group yesterday...`），但 `extract_work_events` prompt 规定 `narr_timestamp`"保留原文形态、不换算、不猜测"——"yesterday" 被原样抽出：

- `timestamp_sort_value("yesterday")` = -inf，不可排序（冒烟 `sortable_ratio=0.0`，样本 `["yesterday", "last year", "last Saturday", ...]`）；
- agent 经 timeline **找到了目标事件**，却只能答 "yesterday"，gold 是 "7 May 2023"，judge 判错；
- LoCoMo temporal 类 308 题（16%）实测 71% 依赖这种相对时间解析——不修基本全军覆没。

失败不在检索、不在抽取覆盖，恰在**相对时间从未对着锚点解析成绝对日期**——信息在 ingest 那一刻就没落进图。

"不换算"规则本身是对的（防"建安五年"式无依据幻觉换算），但**锚点在场的文本内推理不是猜测**：锚点 2023-05-08 + "yesterday" → 2023-05-07 是确定性日期算术。本 change 把这条规则精确化为两种情形，等于把宪法预留的"Phase 2 纪年归一化"里"锚点在场、日精度可确定"这个最小子集提前落地。

## What Changes

- `mcs/prompts/extract_work_events.py` SYSTEM_PROMPT 增加**锚点解析例外**规则：
  - 文本自带显式时间锚点、且发生时间是相对锚点的表述（yesterday / two days ago / 前天）、且能**确定到具体某天** → `narr_timestamp` 写 **ISO 日期**（`"2023-05-07"`）；
  - 确定不了具体某天（"last week" / "last year"）→ **保留原文形态**（宁缺毋滥，不编造日期）；
  - 无锚点 / 作品纪年（"建安五年"）→ 行为**完全不变**。
- 新增测试 `tests/test_work_event_anchor_resolution.py`：prompt 规则防回归 + ISO 形态端到端可排序 + 原文形态行为不变。
- 不改 parse、不改排序器、不改任何管线代码——纯 prompt 规则 + 测试。

## Capabilities

### Modified Capabilities
- `unified-graph-schema`: 「per-universe 事件层与作品叙事事件」新增锚点解析 requirement（作品叙事事件的 `narr_timestamp` 在锚点在场且日精度可确定时 MAY 解析为 ISO 日期）

## Impact

- 受益方：`bench/locomo`（temporal 类的答案来源；conversational-memory-bench tasks T0 声明的依赖即本 change）；任何"文本自带时间锚点"的叙事语料（聊天记录、日志体作品）
- 不受影响：无锚点作品纪年抽取（三国类）零行为变化；LongMemEval（无 work_id、③b 不触发——其 temporal 路线是另一个独立决策）
- **为什么只做"日精度确定"子集**：排序器对 `"2023-05-07"` 走 epoch 秒尺、对 `"2023-05"` / `"2022"` 走数字年尺（实测 1683388800.0 vs 2023.0）——同 universe 混用两把尺子排序错乱。年/月精度的解析必须与排序归一化（Phase 2 纪年归一化）一起做，本 change 不越界
- 验证：LoCoMo 冒烟重跑（同 2 会话 force 重建），预期 `sortable_ratio` 转正、"When did Sarah go to the LGBTQ support group?" 答出 7 May 2023
