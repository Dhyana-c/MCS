## MODIFIED Requirements

### Requirement: 基于当天碎片生成日记
系统 SHALL 读取当天的**全部碎片**（`FragmentStore.read_all(date)`——`pending`/`confirming`/`confirmed` 各态全量，按 `time` 排序），拼成 `HH:MM 内容` 文本，经一次 LLM 概括生成一篇连贯的日记 Markdown。概括 SHALL **忠实**——双向约束：① SHALL NOT 杜撰碎片未提及的事（**包括天气**）；② SHALL NOT 因"不重要"而遗漏任一碎片的关键信息。日期 / 星期 / 天气 SHALL 用给定 date（MUST NOT 杜撰）。日记 SHALL NOT 进图（不 ingest、不建 source 节点）。

#### Scenario: 正常生成
- **WHEN** 当天有多条碎片（含 pending / confirming / confirmed 各态），触发生成
- **THEN** 产出一篇连贯叙述的日记 MD，内容忠实碎片、不含杜撰（含日期 / 星期 / 天气均用给定 date），且未发生任何 ingest / 建图操作

#### Scenario: 不遗漏关键信息
- **WHEN** 当天碎片含若干各自独立的事项
- **THEN** 日记 MUST 覆盖每条碎片的关键信息，MUST NOT 因 LLM 判"不重要"而整条略过

#### Scenario: 当天无碎片
- **WHEN** 当天无任何碎片
- **THEN** 不生成日记，返回"当天无碎片"
