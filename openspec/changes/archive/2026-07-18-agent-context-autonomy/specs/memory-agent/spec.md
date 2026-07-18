## ADDED Requirements

### Requirement: agent 会话上下文自治（单一硬 T + 模型自治工作集）

`MemoryAgent` SHALL 支持会话级上下文预算（`context_budget`，默认关闭保存量行为）。开启时：

- **框架硬闸**：每轮组装 messages 前 SHALL 由框架估算总量（估算口径 == 实际发送口径，会话层铁律一），保证 ≤ `context_budget`；MUST NOT 依赖 LLM 自估 token。
- **存根折叠**：距当前 ≥ N 轮且未 pin 的工具结果消息 SHALL 替换为单行存根（工具名 + 参数摘要 + 触达节点 id）；id **窗口级去重**——窗口内首次触达的 id MUST 全文列出，已在早前存根出现的 id 以计数省略；折叠 MUST NOT 丢弃窗口内尚未出现的 id（id 是可逆取回的句柄——被折叠内容可按 id 经 search/associate 取回）。assistant / user 消息 MUST NOT 折叠。
- **重复调用不拦截**：与窗口内存根同工具同参的再次调用 MUST NOT 被拒绝或返回缓存（相关性判断是积累集依赖的——积累/pin 集变化后重看同一节点可得不同判断；且会话中 learn 会改图）；框架 SHALL 在新结果头部标注同参存根编号——"以前看过"作为信号提示，重看与否由模型自决。
- **pin 语义**：模型 MAY 在回复中以固定标记声明 pin / unpin 工具结果；pin 项不被折叠 / 自动逐出。管理决策 MUST 折叠进既有回复，MUST NOT 占用独立轮次；pin 总量 SHALL 有防御性上限（防囤积）。
- **显式终止**：系统提示词 SHALL 约定终止标记（与 pin 同族，如 `FINISH` + `USED: #k`）——模型判断无需再遍历时以该标记收束，终止回复 SHALL 携带最终答案与支撑证据引用（存根编号 / 节点 id）；框架 SHALL 解析并剥离标记后返回答案，将终止类型（`finish` / `implicit` / `finalized` / `forced`）与支撑引用记入 `ChatTrace`。无标记且无工具调用的回复 SHALL 仍被接受为最终答复（记 `implicit`，不为格式合规浪费轮次）。
- **收尾轮**：剩余 1 轮时预算段 SHALL 替换为「最后一轮请直接作答」指令；轮次耗尽仍未作答时框架 SHALL 追加**一次**收尾调用（有界 +1，注入「立即交付」硬指令、忽略其中的工具调用）——有内容则剥离标记交付（记 `finalized`）、无内容则保持 forced 兜底文本。MUST NOT 超过一次收尾调用。
- **确定性兜底**：超预算时框架 SHALL 依序：折叠可折叠项 → 逐出最旧未 pin 存根 → 仍超则拒绝注入新工具结果并以 tool 消息告知模型（请换出或收尾）。MUST NOT 静默截断消息中段、MUST NOT 死锁。
- **预算可见**：每轮 SHALL 向 system prompt 注入已用 / 剩余预算与剩余轮次（终止信号——模型据此收尾）。
- **可观测**：每次折叠 / 逐出 / pin 变更 SHALL 记入 `ChatTrace`。

id 台账（visited 节点）SHALL 留在窗口外由框架维护，窗口内仅以存根行体现。

#### Scenario: 硬闸与估算口径一致

- **WHEN** 开启 `context_budget`，多轮工具调用使 messages 总量即将超预算
- **THEN** 框架 MUST 在发送前折叠 / 逐出至 ≤ 预算（估算与实际发送同口径）
- **AND** MUST NOT 要求 LLM 自行估算 token

#### Scenario: 存根折叠保留 id 句柄（窗口级去重）

- **WHEN** 一条 3 轮前的未 pin search 结果（含 12 个节点，其中 3 个已在早前存根出现）被折叠
- **THEN** 其消息 MUST 替换为单行存根：9 个窗口内首见 id 全文列出，3 个已见 id 以计数省略
- **AND** 模型后续 MAY 按 id 经 associate 取回细节（遗忘可逆）

#### Scenario: 重复调用不拦截、标注已见

- **WHEN** 模型对已折叠为存根 #2 的 search 以相同参数再次调用
- **THEN** 框架 MUST 正常执行工具并注入全文结果
- **AND** 结果头部 MUST 标注与存根 #2 同参
- **AND** MUST NOT 返回缓存或拒绝调用

#### Scenario: 收尾轮降级交付

- **WHEN** 开启预算、模型连续 max_turns 轮均返回工具调用
- **THEN** 框架 MUST 追加一次收尾调用（视图含「立即交付」指令）
- **AND** 收尾回复有内容 → 剥离标记后作为最终答复，trace 记 `finalized` 与 USED 引用
- **AND** 收尾回复仍无内容 → 返回 forced 兜底文本，MUST NOT 再次调用

#### Scenario: FINISH 显式收束

- **WHEN** 模型判断探索充分，回复含 FINISH 标记、最终答案与 `USED: #2 #5`
- **THEN** 框架 MUST 结束循环、剥离标记后返回答案
- **AND** `ChatTrace` MUST 记录终止类型 `finish` 与支撑引用
- **AND** 无标记且无工具调用的回复仍 MUST 被接受为最终答复（记 `implicit`）

#### Scenario: pin 项不被折叠

- **WHEN** 模型对某工具结果声明 pin，随后数轮探索其他方向
- **THEN** 该结果 MUST 保持全文在上下文中
- **AND** 未 pin 的同期结果 MAY 被折叠

#### Scenario: 兜底不死锁

- **WHEN** pin 总量已达预算而模型仍发起新工具调用
- **THEN** 框架 MUST 拒绝注入新结果并以 tool 消息告知（请换出 pin 或收尾）
- **AND** MUST NOT 静默截断、MUST NOT 无限循环

#### Scenario: 默认关闭零行为变化

- **WHEN** `context_budget` 未设置（存量调用）
- **THEN** MemoryAgent 行为 MUST 与现状完全一致（不折叠、不注入预算段）

## MODIFIED Requirements

### Requirement: MemoryAgent ReAct loop

`MemoryAgent` SHALL 实现 ReAct 循环：每轮将 messages（system + 历史 + 工具结果）发给 LLM，LLM 返回工具调用或最终答复；工具结果以 tool 消息回灌；最多 `max_turns` 轮防失控。**开启 `context_budget` 时，每轮组装 MUST 经会话上下文自治机制**（硬闸 / 折叠 / 预算注入——见「agent 会话上下文自治」requirement）；未开启时行为不变。system prompt SHALL 注入图级摘要（受 `summary_budget` 约束）；开启预算时 SHALL 追加动态预算段。

#### Scenario: 多轮工具调用回灌

- **WHEN** LLM 返回工具调用
- **THEN** 执行工具、以 tool 消息回灌结果、进入下一轮
- **AND** 达到 `max_turns` 未收尾时返回兜底答复（不无限循环）

#### Scenario: 开启预算时组装经自治机制

- **WHEN** `context_budget` 开启且历史含可折叠工具结果
- **THEN** 本轮发送的 messages MUST 为折叠后形态（含存根与预算段）
- **AND** 总量 MUST ≤ `context_budget`
