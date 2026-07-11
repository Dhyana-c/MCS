## ADDED Requirements

### Requirement: 概念 content 零时间，事实禁单次时间，事件带 timestamp

系统 SHALL 守「核心图节点 content 按类型分时间归属」的不变量（宪法双层「核心稳定 / 事件带时间」+ 「时序走字段不走边」的对称精确化）：
- **概念节点 `content` 零时间**：MUST NOT 含任何时间（无论相对「今天/昨天/这次/未完成/计划中/将进行」还是固定「1976 年」）。概念是纯名词定义 / 身份；带时间的属性（如"创立于 1976"）归事实命题。
- **事实节点 `content` 禁相对/单次时间、允许固定历史时间**：MUST NOT 含「今天/这次/未完成/计划中/将进行」等事件性时间；MAY 含「1976 年/3 月 15 日」等固定历史时间作命题固有属性。带时间的发生 MUST 归事件层，其去时间化版本 MAY 作事实（谓词落 content，相对/单次时间不进 content）。
- **事件节点带 `timestamp`**（单次发生时间，在 `event_meta.timestamp`）。

所有用 mcs 的场景都该守，不只是日记。

#### Scenario: 概念 content 零时间

- **WHEN** 抽取一个概念（如"按摩"、"苹果公司"）
- **THEN** 其 `content` MUST NOT 含任何时间词（既不含「今天/这次/未完成」等相对/单次时间，也不含「1976 年」等固定历史时间）
- **AND** "创立于 1976" 这类带时间属性 MUST 作为事实命题抽取，MUST NOT 进概念 content

#### Scenario: 事实 content 禁单次时间、允许固定历史时间

- **WHEN** 抽取一个事实（命题，如"苹果创立于 1976"）
- **THEN** 其 `content` MAY 含「1976 年」等固定历史时间作命题属性
- **AND** MUST NOT 含「今天/这次/未完成/计划中」等相对/单次时间

#### Scenario: 带时间发生归事件层、去时间化版本作事实

- **WHEN** 输入含带时间的发生（如"今天去了按摩"）
- **THEN** 该发生 MUST 归事件层（事件节点 + timestamp）
- **AND** 其去时间化版本 MAY 作事实（如「用户去按摩」），相对/单次时间 MUST NOT 进事实 content

## MODIFIED Requirements

### Requirement: 图质量最终收敛（去重 / 合并）

重复的同名 / 同义概念 SHALL 由读写共同触发收敛：创建时对齐、之后被写 / 读触及时（read-repair）、聚类时合并。同名 SHALL 可由字面匹配当场识别，但 MUST NOT 仅凭同名盲并（同名未必同义，需消歧）。事实去重 SHALL 按"同主 · 同宾 · 同说法"对齐；后台维护扫描（dedup）MAY 合并同名字面事实（背书 / 互斥边重挂；互为互斥的两事实 MUST NOT 合并以避免自互斥 / 矛盾塌缩）。聚类裂变（见守门 requirement）对事实 MUST 仍只重组不合并——后台去重与聚类是不同操作。完全未被触及 / 聚类的长尾残留 SHALL 由可选的后台维护扫描兜底。

**content 合并守则**（落实时间归属不变量 + 不机械拼接）：同名 / 同义节点合并时，content MUST 经公共 `merge_content` helper 处理——MUST NOT 机械换行追加。helper 按子串关系零成本处理（target ⊇ incoming 跳过、incoming ⊇ target 替换）；非子串的 content 差异按路径分流：write path（`_dispatch_merge`）MUST 调 LLM 语义合并成一个稳定定义（守时间归属）；read-repair（读路径）与后台 dedup MUST NOT 调 LLM 合并 content，非子串 content 不碰（被并方 / dup 节点保留、后续 write path 收敛）——dedup 仅在子串关系时合并删 dup。

#### Scenario: 读时也可收敛（read-repair）

- **WHEN** 查询的工作集里出现两个同名 / 同义概念节点
- **THEN** MAY 当场合并（合并产生的节点 MUST 过守门）
- **AND** content 合并 MUST 经 `merge_content` helper：子串关系零成本处理；非子串 content MUST NOT 追加、MUST NOT 调 LLM（读路径零 LLM）
- **AND** 被并方节点 MUST 保留（非子串 content 不丢，后续 write / dedup 收敛）
- **AND** 需消歧 / 合并后超 T 的，MUST 挂起交写 / 维护，MUST NOT 在读路径同步跑 `decide_hub`

#### Scenario: 后台 dedup 子串才合（无 LLM）

- **WHEN** dedup 维护扫描同名节点
- **THEN** content MUST 经 `merge_content` helper（**不传 merge_llm**）：子串关系才合并删 dup（target ⊇ dup 跳过、dup ⊇ target 替换），MUST NOT 机械追加
- **AND** 非子串 content 差异 MUST 保留两个节点不合（不丢信息，彻底合并靠 write path）
- **AND** 互为互斥的同名节点 MUST NOT 合并（避免自互斥 / 矛盾塌缩）
