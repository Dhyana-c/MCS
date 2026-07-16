## Why

时间归属规则（`b03cda2`，随 core-graph-time-attribution 落进 `extract_concepts` prompt 与 unified-graph-schema spec）在**文档语料**（新闻等）上暴露系统性覆盖缺口：规则要求"带时间的发生归事件层、MUST NOT 抽事件性命题"，但**现实 universe 没有叙述发生的抽取路径**——事件层只有摄入行为事件（规则产生、每次 ingest 一条）。于是新闻里的时序性内容（裁员 / 判决 / 赛果 / 交易）整体失去落点，模型的合规行为 = 概括 + 丢弃。

**证据链**（详见 `bench/multihop_rag/reports/agent_build_20260715.md` 与 A/B `scripts/exp_time_rule_ab.py`）：

- 全量取证：71KB 裁员清单文档，规则前建的图抽出 222 节点、规则后只有 4 个门面节点；raw 输出显示模型把整个清单卷成一个聚合概念（relation_hints 里写着"包含 Google、Amazon、Microsoft 等公司裁员"——看见了但按规则不展开）。三方对照中 20 题检索丢失的 gold 全是时序密集文档。
- A/B（20 丢失题的 38 篇 gold 文档，唯一变量 = 抽取 prompt）：**抽取层证实**——松绑后节点 +26%/篇、裁员清单 67→357（+433%），增益 top5 全是时序密集文档；**检索层在 38 篇子集上测不出差距**（两组均 ~19/20，小语料种子必中，原失败是"薄覆盖 × 全量 16K 节点稀释"的组合），检索收益的定量证明需全量重建（成本高，不阻塞本 change——抽取覆盖本身就是图质量目标）。
- 附带发现（如实记录）：当初 4 节点塌缩是"规则 × 长清单 × 阶段② 富上下文"的叠加（同 prompt 在空图子集上抽 67），规则是主因但非唯一因子。

这是 `work-narrative-events` 缺口的镜像：wne 给了**作品** universe 叙述发生的落点（LLM 抽取 + 作品纪年），而**现实世界的叙述发生**（新闻报道的真实发生）仍无处安放。

## What Changes

- **精确化"事件性命题"边界（核心，evidence-backed）**：时间归属规则中被禁止的"事件性命题"收窄为**相对 / 单次 / 未完成时间的发生**（"今天去按摩""这次会议"——归用户事件层或去时间化）；**带固定历史时间的、已完成的世界发生**（"2023 年 1 月 Google 裁员 12000 人"）是合法的**历史事实命题**，MUST 可抽取（时间作命题属性留在事实 content——与既有"事实 MAY 含固定历史时间"条款一致，消除两条规则间的表述冲突）。清单 / 汇总型内容 MUST 逐条抽取、MUST NOT 卷成聚合概念。`exp_time_rule_ab.py` 的 TREATMENT prompt 为实现雏形（A/B 已验证行为）。
- **现实叙述事件（评估后决定采纳与否，见 design D2）**：是否给现实 universe 增加 LLM 抽取的叙述事件（与摄入行为事件以 `event_meta.kind` 区分，避免污染 recall 的"用户亲历"语义）——倾向 **Phase 2 / 按需**：历史事实命题已满足检索与图质量目标；现实叙述时间线的需求出现时再走独立 change（复用 wne 的 `WorkEventDraft` 机制）。
- **不改**：作品 universe 路径（wne）不动；摄入行为事件仍规则产生、不经 LLM；概念 content 零时间不动。
- **验证**：既有时间归属测试调整措辞断言 + 新增"带固定历史时间的世界发生可抽为事实"用例；bench 侧以 38 篇子集抽取覆盖为回归锚（裁员清单节点数下限）。

## Capabilities

### New Capabilities

（无）——本 change 是既有时间归属规则的**边界精确化**，落在 `unified-graph-schema` 的既有 requirement 上，不引入新 capability。

### Modified Capabilities

- `unified-graph-schema`：**修改**「概念 content 零时间，事实禁单次时间，事件带 timestamp」requirement——事实侧措辞从"带时间的发生 MUST 归事件层"精确化为"**相对 / 单次 / 未完成时间的发生** MUST 归事件层（或去时间化）；**带固定历史时间的已完成世界发生** MAY 作为历史事实命题抽取（时间留 content）；清单 / 汇总内容 MUST 逐条抽取"。

## Impact

- **代码**：`mcs/prompts/extract_concepts.py`（SYSTEM/USER 时间归属段措辞，参照 TREATMENT prompt）；无管线结构改动（若 design D2 采纳现实叙述事件则另加 `write_pipeline` 分支——倾向不采纳、留 Phase 2）。
- **规范 / 宪法**：`openspec/specs/unified-graph-schema/spec.md` 对应 requirement 精确化；`CLAUDE.md` 宪法「产生方式」段的"事件性命题"表述同步。
- **测试**：`tests/` 中时间归属相关断言（extract prompt 行为用例）+ 新增历史事实命题用例；A/B 脚本保留作回归工具。
- **评测**：multihop agent 图可选全量重建（~11h/¥40+，量化检索收益；不阻塞归档，作为后续验证项）。
- **风险**：①边界仍有灰区（"上周谈判破裂"——相对时间但世界发生）：规则以时间形态（固定 vs 相对）为准绳、灰区宁抽为去时间化事实；②枚举指令可能使普通叙事文档过抽——A/B 显示整体 +26% 在可接受范围，守门/dedup 兜底；③与 golden_cage（中文小说、work_id 路径）无交叉影响（作品路径不动）。
