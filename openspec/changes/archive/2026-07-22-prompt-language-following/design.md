## Context

MCS 的全部 prompt（`mcs/prompts/*.py`）均为中文。对中文语料（如 `golden_cage`）这自洽，但对英文语料会产生系统性语言漂移，破坏英文 benchmark 的召回。本次探索阶段已用真实 deepseek + 临时 sqlite 做了端到端实测，得到两类铁证：

1. **抽取层漂移（条件性）**：英文 ingest 一段含 `Apple`/`Tesla`/`Google`/`Twitter`/`Amazon`/`Microsoft`/`Nvidia`/`Netflix`/`Airbnb` 等知名实体的文本（`token_budget=450`），落图 35 个节点中 12 个（34%）被翻译成中文概念节点（`Apple→苹果公司`、`Tesla→特斯拉`…）。机理：LLM 对「训练知识里有中文名的知名实体」会主动翻译；对没有中文名的实体（`Sergey Brin`、`FTX`、`Meta`）才保持英文。单 prompt 探测 `Caroline`/`Bankman-Fried` 这类非知名实体时未漂移——说明漂移是**条件性**的，由「实体是否有中文锚」决定。
2. **生成层漂移（无条件）**：`decide_hub` 对纯英文节点群概括出的 `theme` 全为中文（CJK 计数验证：`望远镜类型`/`支架与跟踪系统`/`天文相机传感器`）。生成类 prompt 是「凭空产出新文本」，语言跟随 prompt 本身（中文）。

回答侧的 `LANGUAGE_FOLLOW_PROMPT`（`mcs_agent/loop.py:35`）已存在并要求「用用户消息的语言回答」，但它只能影响最终回复，**救不回召回阶段就丢失的信息**——英文 query `"Apple"` 做不了 keyword 匹配到图里的 `苹果公司`。这是英文 benchmark（`multihop_rag` / `locomo` / `longmemeval`）召回受损、疑似 `multihop_rag −21pt` 根因的机理基础。

约束：本次为**纯软方案**——不动 LLM 调用签名、数据流、`IngestInput`、存储 schema。

## Goals / Non-Goals

**Goals:**

- 写入侧抽取 + 生成类 prompt 显式指示 LLM 用输入/节点原文语言、不翻译（含知名实体）。
- `node_class` 在 prompt 协议层英文化为 `concept`/`fact`，parse 映射回中文常量、向后兼容中文值；**存储取值不变**。
- 回答侧 `LANGUAGE_FOLLOW_PROMPT` 由被动转述增强为主动语言对齐。
- 英文 ingest 产出英文节点（知名实体不翻译）；中文语料行为不变。

**Non-Goals:**

- 不引入 `IngestInput.language` 字段或语言检测（纯软；若实测不够再另起 change）。
- 不改 tokenizer（`ChineseTokenizer`/jieba 对英文切词次优）——单独 change。
- 不迁移存量污染数据；英文 bench 需重建图。
- 不改 `node_class` 存储取值、不改图模型（`概念`/`事实`/`事件`/`source` 四分类语义不变）。

## Decisions

### Decision 1: 纯软方案（prompt 指令），不引入 language 字段

**选择**：给各 prompt 加「MUST 用输入/节点原文语言、不翻译，即使实体在通用知识里有其他语言名称」指令。

**理由**：实测显示 LLM **能**遵守语言跟随——`Caroline`/`Bankman-Fried` 这类无中文锚的实体保持英文。漂移只发生在「有中文锚的知名实体」（LLM 主动翻译）和「生成类 prompt」（跟随 prompt 语言）。这两种都是**指令缺失**而非**能力缺失**，加明确指令即可纠正。硬方案（`IngestInput.language` + 注入 prompt）要动数据流 + 加语言检测，而 `IngestInput` 已有 `work_id` 等 universe 轴，再加 language 轴过度工程；且 ingest 输入常是混合语言，单值 language 字段难以表达。

**Alternatives**：
- *纯硬方案*（language 字段）：更可控但成本高、混合语言难表达，否决。
- *混合*（软为主 + 可选字段）：留逃生口，但增加复杂度；本次先纯软，若 bench 验证不够再升级（见 Open Questions）。

### Decision 2: node_class 枚举英文化（concept/fact），存储不变

**选择**：prompt 字面值 `node_class="概念"|"事实"` → `"concept"|"fact"`；`extract_concepts.parse` / `judge_relations.parse` 加映射 `concept→CLASS_CONCEPT`、`fact→CLASS_FACT`，并仍接受中文值（向后兼容）。

**理由**：prompt 里满眼中文枚举值会强化「这是中文任务」语境、加剧翻译诱导；英文枚举让 prompt 更语言中立，与语言跟随指令同向。**关键**：`node_class` 存储取值来自 `mcs/entities/graph.py` 的 `CLASS_CONCEPT="概念"`/`CLASS_FACT="事实"` 常量，parse 把 LLM 输出映射到这些常量——所以存储层 `node.node_class` 仍是中文，**存量数据与既有读路径零改动**，只是 prompt↔LLM 之间的协议字面值变了。这是非 BREAKING 的。

**Alternatives**：
- *不改枚举*（保留中文 `概念`/`事实`）：协议字段不污染 content（实测 parse 正常），但放弃了「降低中文诱导」的同向收益，否决。
- *存储也英文化*：BREAKING、要迁移全部存量节点，否决。

### Decision 3: 机理边界决定指令覆盖面

**选择**：指令覆盖**抽取类 + 生成类**全部 prompt，不假设某类天然安全。

**理由（关键技术洞察）**：实测推翻了「抽取类天然跟随输入语言」的初判——`extract_concepts` 对知名实体也会翻译。机理边界是：
- **抽取/复述类**（`extract_concepts`/`extract_work_events`/`merge_content`/`select_*`/`gen_aliases`）：输入驱动，对**无中文锚**实体跟随输入，对**有中文锚**知名实体翻译 ❌
- **生成/概括类**（`decide_hub`/`generalize`/`gen_summary`/`gen_graph_summary`/`synthesize`）：prompt 驱动，跟随 prompt 语言（中文）❌

两类都有漂移、只是触发条件不同，故指令两类都加。`gen_aliases` 的示例 `["AAPL", "苹果公司", "苹果"]` 尤其要改——它是显式中文示范。

### Decision 4: 回答侧增强为主动对齐

**选择**：`LANGUAGE_FOLLOW_PROMPT` 在原「用用户语言回答 + 转述不一致的节点内容」基础上，加「不确定用户语言时先据用户消息判断再作答」。

**理由**：现状是被动转述（agent 已生成内容后转语言）。加主动对齐让 agent 在作答前先锚定语言，减少中途漂移。低成本、与写入侧修复互补。

## Risks / Trade-offs

- **[LLM 不 100% 遵守软指令]** → 测试用真实 LLM 覆盖「知名英文实体不翻译」场景（`Apple`/`Tesla`/`Google`）；bench 小集 A/B 验证修复增益。若软方案实测不足，升级到混合方案（Open Questions）。
- **[node_class 英文枚举让某些 LLM 在中英混合 prompt 下困惑]** → parse 向后兼容中文值兜底（LLM 吐中文也能 parse）；回归测试覆盖中文语料。
- **[中文语料回归]** `golden_cage` 等中文 bench 行为可能受指令影响 → 加中文语料回归测试（中文 ingest 仍产中文节点、中文别名质量不退）。
- **[gen_aliases 去中文化影响中文概念别名质量]** → 中文概念别名回归测试；示例改为语言中立（如 `["US", "United States", "America"]` 这种不预设语言的形态，或同时给中英示例）。
- **[指令加长 prompt → token 成本]** 语言跟随指令每条约 1-2 行，影响小；与铁律一「估算==渲染」无冲突（prompt 不进节点活跃视图估算）。

## Migration Plan

- **无数据迁移**：`node_class` 存储取值不变，存量图与读路径零改动。
- **代码部署**：prompt 文本 + parse 映射 + `LANGUAGE_FOLLOW_PROMPT` 一次性切换；parse 向后兼容保证旧测试（若硬编码中文 `node_class` 输出期望）在调整后通过。
- **bench 重建**：英文 bench（`multihop_rag`/`locomo`/`longmemeval`）需删除旧图、重新 ingest 才吃到修复；中文 bench（`golden_cage`）无需重建。
- **回滚**：纯 prompt/parse 文本变更，git revert 即可；无 schema / 数据不可逆操作。

## Open Questions

- **软方案是否足够**：需在实现后用真实 LLM + 英文 bench 小集验证「知名实体不翻译」是否稳定成立。若不足，后续 change 引入混合方案（`IngestInput.language` 可选锚）。
- **极短/混合语言输入的边界**：单词输入（如纯 `"Apple"`）或中英混合句的语言判定，交给 LLM 据上下文判断（指令措辞需覆盖「混合语言时按主体语言/逐实体保留原文」）。
- **`gen_aliases` 示例的最终形态**：纯英文示例 vs 语言中立示例，实现时定（倾向语言中立，避免再次诱导）。
