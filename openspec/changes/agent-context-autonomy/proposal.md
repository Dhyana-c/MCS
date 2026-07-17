## Why

agent 路径（`MemoryAgent` ReAct loop）目前**完全不管理自己的会话上下文**：每个工具结果（渲染子图，单次可达 T）永久留在 messages 并随每轮全量重发——multihop 200 题实测 **127K token/题**（黄金笼 114K/题），其中大部分是零贡献的死探索；黄金笼有题目死于"达到最大轮次"（上下文膨胀吃掉轮次预算），且 agent 对自己的预算是盲的（max_turns 是唯一的墙）。

讽刺的是，MCS 框架侧早有这套纪律（四区模型：积累区/活跃区进 LLM、visited/frontier 只存 id）——agent 接管查询后把纪律丢了。而四区的**硬分配比例**（token_budget 给积累区封顶）本是"不会思考的 BFS 循环"需要的静态分配；agent 范式下，"什么此刻重要"的判断正是 LLM 的本职。方向（与 framework-to-agent-handoff 一致）：**框架只保证一条硬 T，T 之内的取舍全部交给模型自决策**。图的存在使该模式比通用 agent 安全一个量级——被逐出的内容按 id 廉价可逆取回。

## What Changes

- **单一硬 T（会话层铁律一）**：`MemoryAgent` 每轮组装 messages 时由框架估算（估算 == 实际发送口径）并保证总量 ≤ 会话预算；超限触发确定性兜底（逐出最旧未 pin 工具结果 → 存根）。**硬闸在框架、MUST NOT 交给 LLM 自估**。
- **存根折叠（减脂层，先行）**：非最近轮次的未 pin 工具结果自动替换为一行存根（工具名 + 参数摘要 + 触达节点 id 列表，id **窗口级去重**——已见 id 计数省略）——id 句柄保留，模型需要时按 id 经 `associate`/`search` 取回（图 = 可逆遗忘的外置存储）。
- **预算可见**：每轮向 system prompt 注入「已用/剩余会话预算、剩余轮次」，模型据此决定收尾或继续（终止信号补位——token_budget 硬比例在 agent 路径不再作停止判据）。
- **pin 语义（自治层）**：模型在回复中以结构化字段标记保留的工具结果（"已确认相关"= 软积累区）；pin 项不被折叠/逐出（除非总量超 T 时模型显式换出）。管理决策 MUST 折叠进既有回复（不占独立轮次）。
- **显式终止 + 重复调用信号**：模型以 FINISH 标记声明"无需再遍历"，终止回复携带最终答案 + 支撑证据引用（`USED:` 存根编号/节点 id）；框架解析收束（trace 区分 finish/implicit/forced，无标记回复宽松接受）。同参重复调用 MUST NOT 拦截或缓存——正常执行、仅标注"与存根 #k 同参"：去重做成**信号**不做成机制（积累集变化后重看同一节点可得新判断；learn 改图后缓存亦不正确）。
- **id 台账留窗口外**：visited 节点 id 由框架维护、窗口内只体现为存根行——MUST NOT 把台账全文塞进窗口。
- **可观测**：每次折叠/逐出/pin 决策记入 `ChatTrace`（调试遗忘错误）。
- **范围边界**：只动 `mcs_agent`（loop/trace）；**框架 BFS 查询管线的四区模型与 token_budget 原样保留**（写管线阶段② 依赖）；两条路径并存互为对照。
- **验收 A/B**（黄金笼/multihop 各 30-50 题）：token/题 显著下降（预期 ≥50%）、超轮次失败不增、reached 不降。

## Capabilities

### New Capabilities

（无）——会话上下文管理是 `memory-agent` capability 的行为演进，不新增 capability。

### Modified Capabilities

- `memory-agent`：**修改**「MemoryAgent ReAct loop」requirement（新增会话预算硬闸、存根折叠、预算可见注入）；**新增**「agent 会话上下文自治」requirement（pin 语义、确定性逐出兜底、重复调用不拦截、FINISH 显式终止、id 台账窗口外、管理决策不占轮次、trace 可观测）。

## Impact

- **代码**：`mcs_agent/loop.py`（消息组装/折叠/预算注入/兜底逐出）、`mcs_agent/trace.py`（折叠/pin 决策记录）、系统提示词（pin 字段约定 + 预算段）；`mcs_agent/memory.py` 预期零改动（原语不变）。
- **配置**：`MemoryAgent` 新增会话预算参数（默认关闭或宽松值——存量调用零行为变化，评测显式开启）。
- **测试**：折叠/逐出/pin/预算注入/同参标注/FINISH 终止单测（注入式 fake LLM 驱动多轮）；A/B 评测脚本（bench 层）。
- **宪法/文档**：`CLAUDE.md`「上下文预算」节补 agent 路径表述（单一硬 T + 模型自治工作集；框架四区仅框架查询路径）；`docs/memory-agent.md` 同步。
- **风险**：①逐出震荡（evict→re-fetch 来回倒）——取回按 id 直达成本低 + trace 观测，A/B 监控**盲目重复率**（同参重发且 pin 集自上次以来无变化；积累集变化后的有意重看是 agent 优势、不计入震荡）；②pin 判断失误丢关键上下文——保守默认（最近 N 轮不折叠）+ 可逆取回；③管理指令增加 prompt 复杂度——A/B 验证 reached 不降是硬门槛。
