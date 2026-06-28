## ADDED Requirements

### Requirement: 基于当天碎片生成日记
系统 SHALL 读取当天 MD 碎片（Slice 1 `FragmentStore.read(date)`），经一次 LLM 概括生成一篇连贯的日记 Markdown。概括 SHALL **忠实**——双向约束：① SHALL NOT 杜撰碎片未提及的事；② SHALL NOT 因"不重要"而遗漏任一碎片的关键信息——**软保证**（prompt 约束、无自动化断言 LLM 输出覆盖度；fake LLM 测不出真实遗漏，测试仅验证 prompt 含此约束）。日记 SHALL NOT 进图（不 ingest、不建 source 节点）。

#### Scenario: 正常生成
- **WHEN** 当天碎片有多条，触发生成
- **THEN** 产出一篇连贯叙述的日记 MD，内容忠实碎片、不含杜撰，且未发生任何 ingest / 建图操作

#### Scenario: 不遗漏关键信息
- **WHEN** 当天碎片含若干各自独立的事项
- **THEN** 日记 MUST 覆盖每条碎片的关键信息，MUST NOT 因 LLM 判"不重要"而整条略过（与杜撰对称的另一面：既不加、也不漏）

#### Scenario: 当天无碎片
- **WHEN** 当天碎片文件不存在或为空
- **THEN** 不生成日记，返回"当天无碎片"

### Requirement: 超窗碎片分段概括再合并

当天碎片字符数超阈值（默认 4000，无 token 估算能力用字符代理）时，日记生成 SHALL 按行分块
分段概括（每块 ≤ 阈值、不拆行）、再合并成一篇连贯日记；否则一次概括。分段为产物侧纯摘要分段
（不入图、不与整合语义分段重复）。

#### Scenario: 超窗触发分段合并
- **WHEN** 当天碎片总长超阈值
- **THEN** 按行分块分段概括，再合并成一篇（多次 LLM 调用）
- **AND** 最终日记 MUST 覆盖各段关键信息、连贯成篇

#### Scenario: 未超窗一次概括
- **WHEN** 当天碎片总长 ≤ 阈值
- **THEN** 一次 LLM 概括（不分段）

### Requirement: 日记存独立目录
日记 SHALL 存储为 `YYYY-MM-DD.md`，在独立目录（默认 `~/.mcs_memory/diaries/`），与碎片目录分开。目录不存在 SHALL 自动创建。

#### Scenario: 首次生成建目录
- **WHEN** 日记目录不存在，首次生成
- **THEN** 自动创建目录并写入日记文件

### Requirement: 日记可重生成
系统 SHALL 允许对同一日期重复生成日记，每次重新概括并覆盖当天日记文件，无单日锁定、无 force 概念。

#### Scenario: 改碎片后重生成
- **WHEN** 用户改了当天碎片后再次触发生成
- **THEN** 重新概括并覆盖当天日记，反映最新碎片

### Requirement: 生成日记 API
系统 SHALL 提供 `POST /diary`（挂 mcs_agent app）触发生成 / 重生成指定日期（默认当天）的日记。生成需 LLM；当注入的 agent 无 `llm` 时（如裸 fake agent）该端点 SHALL 返回 503，不影响捕获等其他路由。

#### Scenario: 生成当天
- **WHEN** `POST /diary`，body `{"date": "2026-06-27"}` 或 `{}`
- **THEN** 生成该日（或当天）日记，返回 `{"ok": true, "date": "2026-06-27"}`；当天无碎片则返回 `{"ok": false, "reason": "no_fragments"}`

#### Scenario: 无 llm 优雅降级
- **WHEN** app 以无 `llm` 的 fake agent 构建，调 `POST /diary`
- **THEN** 返回 503，MUST NOT 抛未捕获异常，且不影响 `/note` 等捕获路由

### Requirement: 读取日记 API
系统 SHALL 提供 `GET /diary/{date}` 读取指定日期日记，`GET /diaries` 列出已生成日记（按日期倒排）。

#### Scenario: 读取已生成
- **WHEN** `GET /diary/2026-06-27`，该日已生成
- **THEN** 返回 `{"date": "2026-06-27", "content": "..."}`

#### Scenario: 读取未生成
- **WHEN** `GET /diary/2026-06-25`，该日未生成
- **THEN** 返回 HTTP 404

#### Scenario: 列表
- **WHEN** `GET /diaries`
- **THEN** 返回 `{"diaries": ["2026-06-27.md", ...]}`（按日期倒排）
