## Context

③b `extract_work_events`（仅 `work_id` 非空时启用）从作品文本抽"带时间的叙述发生"，`narr_timestamp` 现行规则："保留原文形态（如'200 年'、'建安五年'、'2039'、'三日后'）——不换算、不猜测"。该规则防的是**无依据的幻觉换算**（作品纪年 → 公历没有换算依据）。

LoCoMo 冒烟实证的缺口：对话语料**锚点就在文本里**（每行 `[1:56 pm on 8 May, 2023]`），"yesterday" 对着锚点解析是确定性文本内推理，不是猜测——但现行规则一刀切禁止，导致相对时间原样落图、不可排序、temporal 题系统性失分（细节见 proposal / LoCoMo bench 冒烟记录）。

## Goals / Non-Goals

**Goals:**
- prompt 规则精确化：锚点在场 + 相对表述 + **日精度可确定** → `narr_timestamp` 解析为 ISO 日期
- 防幻觉底线不动：确定不了具体某天 → 保留原文；无锚点 / 作品纪年 → 零行为变化
- 测试钉死三个方向：解析生效、保守回退、纪年不受影响

**Non-Goals:**
- 不做年/月精度解析（见 D2 混尺问题——归 Phase 2 纪年归一化）
- 不改 `timestamp_sort_value` / `narrative_timeline` / parse / 管线代码
- 不处理 LongMemEval 的 temporal 路线（无 work_id、③b 不触发，独立决策）

## Decisions

### D1: MAY 而非 MUST；"确定到具体某天"为解析门槛

**选择**：锚点解析是 MAY——LLM 能确定到具体某天（yesterday / two days ago / 前天 这类纯日期算术）才写 ISO；拿不准（"last Saturday" 需知锚点星期几，LLM 易错；"last week" 本身无具体日）→ 保留原文形态。

**理由**：宁缺毋滥与现行抽取规则同一精神。错误的绝对日期比不可排序的原文**更害**——原文形态 agent 还能从 content 自行推理（timeline 返回事件时 narr_timestamp 原样可见），错日期则静默污染时间轴。

### D2: 只做日精度，不做精度阶梯（"2023-05" / "2022"）

**选择**：解析产物只允许完整 ISO 日期（`YYYY-MM-DD`）。

**理由（实测）**：`timestamp_sort_value` 是两把尺子——`"2023-05-07"` → epoch 秒（1683388800.0），`"2023-05"` / `"2022"` → 数字年（2023.0 / 2022.0）。同 universe 内混用两把尺子，数字年恒 << epoch 秒，升序时年精度事件全部错误地排在日精度事件之前。年/月精度解析必须与排序器归一化同做（Phase 2 纪年归一化的正统范围），本 change 不越界。

**代价**："last year" → "2022" 这类年精度题仍不可排。可接受：此类事件 timeline 仍返回（垫底不缺席），agent 从 narr_timestamp 原文 + content 可自行推理；且避免了混尺错序这个更隐蔽的坑。

### D3: 纯 prompt 规则，不动代码

**选择**：改动仅 `SYSTEM_PROMPT` 一条规则（含正例 `锚点 8 May, 2023 + "yesterday" → "2023-05-07"`）。`parse()` 本就对 `narr_timestamp` 原样透传（str 强转），ISO 字符串天然兼容；`timestamp_sort_value` 本就认 ISO。

**备选（否）**：ingest 后处理规则解析相对时间——需要 NLP 日期库 + 锚点定位逻辑，重复 LLM 已有的能力，且"相对表述识别"本就是语义判断（铁律二精神：语义归 LLM）。

## Risks / Trade-offs

- **[LLM 日期算术出错]** yesterday −1 天算错（月界/年界）→ 错误绝对日期落图。缓解：prompt 给正例、门槛限"纯日期算术可确定"；LoCoMo 试点 `timestamp_samples` 抽查实际形态可观测
- **[解析率不可控]** MAY 语义下 LLM 可能保守到几乎不解析 → sortable_ratio 提升有限。由冒烟/试点实测定夺，不达预期再收紧措辞（如给更多正例）
- **[中文锚点形态]** LoCoMo 锚点是英文（"8 May, 2023"）；中文语料锚点（"2023年5月8日"）同规则适用，prompt 例子不限定语言

## Open Questions

（无——范围收敛为单条 prompt 规则；年/月精度与排序归一化明确移交 Phase 2 纪年归一化。）
