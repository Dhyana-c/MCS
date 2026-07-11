## Context

日记场景暴露核心图被污染：
- **概念带单次时间**（按摩 content="计划今晚进行"）—— `extract_concepts` prompt 只要求"精简自包含"（write-pipeline 行 177），未禁时间词。
- **事件性命题被抽成概念**（"未去按摩的情况"）—— prompt 未区分稳定实体 vs 单次事件。
- **同名概念 content 拼接**（按摩两条直接拼）—— write-pipeline 行 138 规定 merge 时 content「非子串换行追加」，机械拼接。**根因已确认**：`_dispatch_merge`（`write_pipeline.py:565-567`）`node.content = f"{existing}\n{incoming}"` 逐字落实 spec——**是 spec 规定的追加行为，非 bug**；本变更是 spec 行为变更（追加 → 语义合并）。

「概念/事实是稳定核心图、事件带时间」本是宪法双层（unified-graph-schema 行 60）的自然推论，但抽取 prompt + merge 逻辑都没守。

## Goals / Non-Goals

**Goals:**
- 概念/事实 content 无单次时间（稳定、可复用、跨多次不冲突）。
- merge 同名节点 content 不机械拼接（合成一个稳定定义）。
- 时间归属作为图模型不变量（mcs-core 通用，非 mem 产品特化）。

**Non-Goals:**
- 不归纳偏好/模式（"喜欢按摩"不抽；靠概念/事实 degree 涌现，归纳管线 Phase 2）。
- 不改事件层（事件带时间、整 ingest 记录，已正确）。
- 不改载重 / 守门 / 查询。
- 不在 mem 层覆写 prompt（时间归属是 mcs-core 通用不变量，覆写是债）。

## Decisions

### D1. 三类节点时间归属（不变量，按节点类型分）

- **概念 content 零时间**：纯名词定义 / 身份，**不含任何时间**（无论相对「今天」还是绝对「1976 年」）。"苹果公司"是概念（定义），"创立于 1976"是**事实命题**（谓词落其 content），不进概念 content。
- **事实 content 禁相对/单次时间、允许固定历史时间**：命题（谓词落 content）禁「今天/昨天/这次/未完成/计划中/将进行」等事件性时间；允许「1976 年/3 月 15 日」等**固定历史时间**作命题固有属性。
- **事件带 timestamp**：单次发生时间在 `event_meta.timestamp`。

**why**：核心图（概念/事实）跨时间稳定复用——概念带**任何**时间都让节点不可复用（明天的按摩和今天的冲突）；事实带相对/单次时间同理（"今天去按摩"明天看就错）。事件层本就是带时间的发生。这是宪法双层（核心稳定 / 事件带时间）的精确化，所有用 mcs 的都该守。

**与「时序走字段不走边」的关系**（unified-graph-schema 行 102）：那条规定 `timestamp` 走 extension 不走边、转述时间不污染用户时间轴（"三年前的故事"作核心事实带叙述时间属性）。D1 是其对称面——核心图 **content 侧**也守时间归属：相对/单次时间归事件层，固定历史时间可作事实命题属性。两者共同落实双层模型。

### D2. extract_concepts prompt 守时间归属

修改 `mcs/prompts/extract_concepts.py` SYSTEM_PROMPT：
- 概念/事实 content 禁相对/单次时间词。
- 带时间的发生 → 去时间化作事实（"今天去按摩" → 事实"用户去按摩"，时间归事件层）。
- 不抽事件性命题（"X 的情况"、某次因果"X 导致 Y"）作概念/事实 —— 归事件层。
- 不抽偏好/模式（"喜欢按摩"）—— 单条日记抽不出，靠 degree 涌现。

**why**：当前 prompt 未约束时间/事件性，是污染主因。

### D3. merge content 从「追加」改「语义合并」（方案 b：保留压缩段）

修改 write-pipeline `merge 时 concept content 追加到目标节点`（行 138）**并协调** `merge-content-compaction`（行 11）：
- **当前**：非子串 content 换行追加（拼接），超阈值（默认 500）才 `gen_summary` 压缩。
- **改为**：merge 时新旧 content 由 LLM **语义合并**成一个稳定定义（去重 + 择优 + 守时间归属），不机械拼接。合并 purpose 模板 MUST 携带 `node_class` 按节点类型分流时间归属——概念零时间；事实禁相对/单次时间、**保留**固定历史时间（否则同名事实合并会把「1976 年」这类命题固有属性抹掉，违反 D1）。
- **保留压缩段**（merge-content-compaction）：语义合并结果仍可能超阈值（高频 merge 多次），保留 500 阈值压缩作膨胀兜底；压缩触发前提从「追加后」改为「合并后」。

**why**：追加导致按摩两条 content 拼。即使 D1 让新 content 无时间，多条通用描述机械追加仍冗余，应合并成单一稳定定义。语义合并在 merge 时一次 LLM 调用，保证 content 始终干净；压缩段保留作高频 merge 的膨胀兜底（方案 b）。

**alternatives**：
- 方案 a（D3 缩范围只做 prompt，merge 不动）—— 不解决拼接，按摩 content 仍会拼。
- 方案 c（语义合并替代压缩段）—— 高频 merge 仍可能膨胀，无兜底。
- 保留首条、丢弃新 content —— 丢信息（新 content 可能补充）。
- 追加 + 压缩（现状）—— 拼接观感差、压缩滞后、压缩前 content 已损坏。

**归属**：merge 基础行为（追加 → 语义合并）RENAME + MODIFY write-pipeline；压缩段前提（追加后 → 合并后）MODIFY merge-content-compaction。两个 capability 协调变更，**不能只动一个**（否则 spec 体系自相矛盾：write-pipeline 说语义合并、merge-content-compaction 说追加后压缩）。

### D4. 不归纳偏好（Phase 2）

单条日记只贡献「无时间概念 + 去时间化事实」+ 事件。偏好/模式靠概念/事实被多事件背书 degree 涌现，不建归纳管线。

**why**：归纳时机难定（每次/定期/阈值都硬伤），且 degree 涌现已回答大部分「懂用户」查询。归纳留 Phase 2。

### D5. 三条字面合并路径统一（read-repair + dedup 纳入）

查清：拼 content 的路径有 **3 条**（不只 write path 的 `_dispatch_merge`），且都用同款「换行追加」逻辑（DRY 违反）：
- `_dispatch_merge`（`write_pipeline.py:565-568`，write path ⑤ merge 决策 + 同名去重）
- `_try_read_repair`（`query_engine.py:386-392`，**query 读路径**当场同名合并）
- `dedup_maintenance`（`dedup_maintenance.py:119-141`，后台扫描，**删 dup 节点**）

第 4 条 `MemoryStore.merge_concepts`（agent 手动合并工具，`merge.py`）已用 LLM `merged_content`，本就正确，不改。

**抽公共 helper `merge_content(target, incoming, merge_llm=None) -> str`**（放 `mcs/core/`）：
- 子串关系（target ⊇ incoming → 跳过；incoming ⊇ target → 替换）→ 零成本，所有路径共用。
- 非子串 + `merge_llm` 传入 → LLM 语义合并成一个稳定定义（守时间归属）。
- 非子串 + `merge_llm=None` → 返回 target（不碰；调用方决定挂起 / 保留 dup）。

**三路径按 LLM 可用性分流**：

| 路径 | merge_llm | 非子串行为 | 理由 |
|---|---|---|---|
| `_dispatch_merge`（write） | ✅ 传 | LLM 语义合并 | write path 本就 LLM |
| `dedup_maintenance`（后台） | ❌ 不传 | 子串才合删 dup；非子串保留 dup 不合 | **死代码兜底**（当前未接入运行），无 LLM 注入路径；非子串不合则不丢（保留 dup） |
| `_try_read_repair`（query） | ❌ 不传 | 不碰（被并方节点保留） | **读路径零 LLM**；被并方不删，信息不丢 |

**read-repair 非子串不碰 + 被并方保留**：query 路径撞同名，子串才合（零成本）；非子串 content 差异不追加（避免拼）、不调 LLM（读路径底线），被并方节点保留——后续 write path / dedup 触及时由 LLM 合并收敛。

**dedup 子串才合（不升级 LLM）**：dedup 是"可选兜底"且**当前未接入运行**（`should_run` 默认 False，无调用方）。给它接 LLM 需 PluginContext 加 llm 字段 + builder 注入 + MaintenanceInterface 签名——工程量中等且改死代码，不值。改为：dedup 用 helper **不传 merge_llm**，**子串关系才合并删 dup**（target ⊇ dup 跳过、dup ⊇ target 替换后删 dup），**非子串则保留两个节点不合**（不收敛、不丢、不拼）。彻底合并靠 write path（每次 ingest 同名对齐 LLM 合并）。dedup 真接入运行且要彻底合并时，再给它加 LLM（另立变更）。docstring + unified-graph-schema spec 同步。

**why**：3 处同款拼接只改 write path 会留两条尾巴（按摩查询撞同名、后台扫描仍拼）。抽 helper 统一，行为按 LLM 可用性分流——读路径零成本底线不破、删节点路径不丢信息。

**alternatives**：
- 只改 write path（选项 A）—— 留 read-repair + dedup 两条尾巴。
- read-repair 也加 LLM —— 破读路径零 LLM 底线，拖慢查询。
- dedup 升级 LLM（选项 X）—— 需 PluginContext 加 llm 注入（工程中）+ 改死代码，不值（选项 Y 子串才合已够）。
- dedup 保持字面追加 —— 删 dup 仍拼接。

**与 #4（agent merge 工具）关系**：`MemoryStore.merge_concepts` 已用 LLM `merged_content`（`merge.py`），正确不改；helper 的 LLM 合并与 merge.py 的 content 合并措辞对齐（同一「语义合并成一个稳定定义」语义）。

## Risks / Trade-offs

- **[merge-content-compaction 协调]** D3 改 merge 基础行为（追加 → 语义合并），`merge-content-compaction` 压缩前提（「追加后超阈值」）失效 → MUST 同步 MODIFIED 该 capability（前提改「合并后超阈值」），否则 spec 体系自相矛盾。已纳入 D3 归属。
- **[read-repair 范围]**（已由 D5 解决）最初 D3 只覆盖 write path；后查清 read-repair（`_try_read_repair`）与后台 `dedup_maintenance` 用同款换行追加，已纳入本变更范围（D5 三路径统一：读路径 / 后台零 LLM、子串才合非子串保留）。
- **[LLM 合并成本]** D3 merge 时多一次 LLM 调用 → 仅 merge（同名二次抽取）时触发，非每次 ingest；可接受。
- **[prompt 概念/事实时间边界]** D1 概念零时间、事实允许固定历史时间，LLM 判断「某时间词该进概念、事实还是事件」有边界 → prompt 明确举例（"苹果公司"=概念零时间；"苹果创立于 1976"=事实带历史时间；"今天去按摩"=事件层 + 去时间化事实"用户去按摩"），测试覆盖。
- **[已损坏数据]** 当前 db 按摩等 content 已拼接/带时间 → 改 prompt 只管以后，损坏数据单独清（重抽 or 抹 content 重建）。
