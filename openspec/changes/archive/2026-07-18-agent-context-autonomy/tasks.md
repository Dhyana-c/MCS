# Implementation Tasks

> 分两阶段、各带 A/B 阶段门（design「验收 A/B」）：阶段 A 减脂（D2+D5，无模型配合要求）
> 先行验证；阶段 B 自治（D3+D4+D6）在 A 达标后进行。任一阶段 reached 显著下降即停。

## 1. 阶段 A：存根折叠 + 预算可见（减脂层）

- [x] 1.1 `mcs_agent/loop.py`：`MemoryAgent` 增 `context_budget: int | None = None`（默认 None = 现状零变化）；每轮组装 messages 时估算总量（估算口径 == 发送口径——同一渲染文本计 token）。→ 自治逻辑落 `mcs_agent/context.py`（`SessionContext`），loop 只接线。
- [x] 1.2 存根折叠：距当前 ≥ N 轮（可配，默认 2）且未 pin 的 tool 消息 → 单行存根（工具名 + 参数摘要 + 触达节点 id，**窗口级去重**——首见 id 全文列出、已见 id 计数省略；折叠不丢窗口内尚未出现的 id）；折叠幂等（每轮重算）；assistant/user 消息不折叠。存根需要 loop 能拿到工具结果的节点 id——经 `ToolCallTrace` 或工具返回文本的 `[id:...]` 解析（选定其一并说明）。→ **已选定：解析返回文本 `[id:...]`**（`ToolCallTrace.result_summary` 截断 200 字符拿不到全量 id）；另落地**无收益不折**守卫（存根不比全文短则保全文——总量不降的重组无效）。
- [x] 1.3 同参标注：检测新工具调用与窗口内存根同工具同参 → 结果头部标注「与存根 #k 同参」；MUST NOT 拦截或返回缓存（纯框架信号，无模型配合要求）。
- [x] 1.4 预算可见：system prompt 追加动态段「会话预算 X/Y，剩余轮次 Z」+ 收尾指令一句。
- [x] 1.5 `mcs_agent/trace.py`：折叠事件入 `ChatTrace`（哪条消息、折叠前后 token）。→ `ContextEvent` + `ChatTrace.context_events`。
- [x] 1.6 单测（注入式 fake LLM 多轮）：折叠触发/幂等/不折叠 assistant/窗口级 id 去重且首见不丢/同参标注不拦截/默认关闭零变化/预算段注入。→ `tests/test_agent_context.py`。
- [x] 1.7 **阶段门 A/B**（bench 脚本，黄金笼 + multihop 各 30-50 题，开 vs 关 `context_budget`）：token/题、超轮次失败、reached。token 降幅 <30% 或 reached 下降 → 调 N 参数复测，仍不达标暂停阶段 B 并报告。→ **按用户指定跑 multihop 200 题**（超出 30-50 规模；黄金笼口径未跑、留待需要时补测）：token **-33%** ✅、reached **+5.0pt** ✅；超轮次 forced 率 0.56 超标 ✗ → 触发 2.8 收尾轮 + 2.9 USED 契约补强后无答案 forced 降至 9%。报告 `bench/multihop_rag/reports/agent_context_autonomy_20260718.md`。

## 2. 阶段 B：pin 语义 + 确定性兜底 + 显式终止（自治层）

- [x] 2.1 pin 标记解析：回复文本尾部 `PIN: #k` / `UNPIN: #k` 约定（框架解析、维护 pin 集；不新增工具、不占轮次）；pin 总量防御上限（默认预算 70%）。
- [x] 2.2 FINISH 显式终止：`FINISH` + `USED: #k` 标记解析（与 pin 同族）——解析到即结束循环、剥离标记返回答案；终止类型（finish/implicit/forced）与支撑引用入 trace；无标记且无工具调用的回复宽松接受（记 implicit）。
- [x] 2.3 确定性兜底链：折叠全部 → 逐出最旧未 pin 存根 → 拒绝注入新结果并回「预算耗尽请换出或收尾」tool 消息；MUST NOT 静默截断/死锁。→ 逐出实现为墓碑 `[已逐出 #k]`（openai tool_call 配对约束）；[预算耗尽] 消息受保护不折不逐（否则极端超预算时模型看不到指引）——design D3 已同步。
- [x] 2.4 系统提示词补管理约定段（何时 pin / 何时不 pin / 何时 FINISH 收束 / 预算耗尽怎么办）。→ `CONTEXT_MANAGEMENT_PROMPT`（仅预算开启时注入）。
- [x] 2.5 trace 补 pin/unpin/逐出/拒绝注入/终止类型事件。
- [x] 2.6 单测：pin 不被折叠 / unpin 后可折叠 / pin 上限触发换出 / 兜底链全路径 / 拒绝注入后模型可继续收尾 / FINISH 剥离与终止类型 / implicit 宽松接受。
- [x] 2.8 收尾轮 + 最后一轮指令（200 题 A/B 中期 forced 率 0.64 后补强，design D5/D6 已同步）：剩 1 轮预算段改收尾指令；轮次耗尽未作答追加有界 +1 收尾调用（忽略工具调用、交付记 `finalized`）；单测 4 项。
- [x] 2.9 USED 交付契约（bench 层）：`--used-contract` 注入「top-10 按相关性降序」契约段；`used_refs` 落盘；混合评分 `ranked_used`（USED 文档排前 + 词法兜底补位），与纯词法口径同跑双算。
- [x] 2.7 **阶段门 A/B**：同 1.7 口径 + **盲目重复率**（同参重发且 pin 集自上次以来无变化——有意重看不计入）+ implicit 终止占比。→ 盲目重复率 4.6-4.7%（pin 采纳≈0 时口径退化、仅参考）、implicit 0.04；USED 契约臂三臂全面最优（reached 0.975 / hit@10 0.855 / token -12%）。pin 语义对 deepseek-chat 采纳失败——机制保留、不作收益预期。

## 3. 文档（保证代码与文档统一）

- [x] 3.1 `CLAUDE.md` 宪法「上下文预算」节：补 agent 路径表述——单一硬 `context_budget` + 模型自治工作集（pin/存根/可逆取回）；框架查询路径四区模型保留不变。
- [x] 3.2 `docs/memory-agent.md`：新参数、pin / FINISH 约定、存根示例（含窗口级去重与同参标注）、A/B 结果。→ 专节「会话上下文自治」+ A/B 结果段已回填（2026-07-18）。

## 4. 验收

- [x] 4.1 `openspec validate agent-context-autonomy --strict` 通过。
- [x] 4.2 `.venv\Scripts\python.exe -m pytest -q` 全绿（存量测试零改动——默认关闭）。→ 1184 passed（新增 15 项 context 单测）。
- [x] 4.3 两阶段 A/B 报告落 `bench/*/reports/`（token/题、超轮次、reached、盲目重复率、implicit 终止占比）。→ `agent_context_autonomy_20260718.md`（三臂总报告）+ `agent_context_autonomy_ab.md` / `agent_context_used_ab.md`（自动对照）。
