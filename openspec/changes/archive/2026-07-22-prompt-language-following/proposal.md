## Why

MCS 的所有 prompt 均为中文，对英文语料会系统性地产出中文节点，破坏英文 benchmark 的召回。端到端实测（真实 deepseek + 临时 sqlite）：英文 ingest 一段含 `Apple`/`Tesla`/`Google`/`Twitter`/`Amazon`/`Microsoft`/`Nvidia`/`Netflix`/`Airbnb` 等知名实体的文本，落图 35 个节点中 **12 个（34%）被翻译成中文**（`Apple→苹果公司`、`Tesla→特斯拉`、`Google→谷歌`…），且是概念节点本身被中文化、不是 hub。机理：LLM 对「训练知识里有中文名的知名实体」会主动翻译；对没有中文名的实体（`Sergey Brin`、`FTX`、`Meta`）才保持英文。另测得 `decide_hub` 对纯英文节点群概括出的 `theme` 全为中文。

后果：英文 benchmark（`multihop_rag` / `locomo` / `longmemeval`）的 keyword 召回失配——英文 query `"Apple"` 搜不到图里的 `苹果公司`，召回阶段即丢信息；回答侧的 `LANGUAGE_FOLLOW_PROMPT`（已存在）救不回。这极可能是 `multihop_rag −21pt`（multi-hop 整合不足）的直接根因。中文语料（`golden_cage`）不受影响、自洽。

## What Changes

- **写入侧·抽取 + 生成类 prompt 加语言跟随指令**：节点 `content` / 概括 / 别名 MUST 用输入文本或被处理节点的原文语言，**即使该实体在通用知识里有其他语言（如中文）的名称也不翻译**，保留原文语言表述。覆盖 `extract_concepts` / `extract_work_events` / `judge_relations` / `decide_hub` / `generalize` / `gen_summary` / `gen_graph_summary` / `synthesize` / `merge_content` / `gen_aliases`。
- **`gen_aliases` 示例去中文化**：当前 USER_TEMPLATE 示例 `["AAPL", "苹果公司", "苹果"]` 是中文诱导，改为语言中立示例。
- **`node_class` 枚举英文化**：prompt 中 `node_class="概念"|"事实"` → `"concept"|"fact"`；parse 层做英文→中文常量映射（`concept→CLASS_CONCEPT`、`fact→CLASS_FACT`），并**向后兼容仍接受中文值**。**存储层 `node_class` 取值不变（仍为中文常量）**——只动 prompt 字面值与 parse 翻译，故存量数据完全兼容、非 BREAKING。
- **回答侧增强**：`LANGUAGE_FOLLOW_PROMPT` 由被动转述增强为主动语言对齐（不确定用户语言时先据用户消息判断再作答）。
- **不在本次范围**：tokenizer（`ChineseTokenizer`/jieba 对英文切词次优）走单独 change；存量污染数据不迁移，仅对新 ingest 生效（英文 bench 需重建图）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `llm-interaction`：新增「prompt 语言跟随」要求——每个 purpose 的默认 prompt MUST 指示 LLM 用输入/节点原文语言、不翻译；新增「`node_class` 枚举英中映射」要求——prompt 暴露 `concept`/`fact`、parse 映射回中文常量且向后兼容中文值。
- `write-pipeline`：新增「抽取产物语言跟随输入」要求——`extract_concepts` / `judge_relations` 对英文语料产出英文节点、知名实体不翻译成中文。
- `memory-agent`：新增「回答侧语言跟随」要求——将 `LANGUAGE_FOLLOW_PROMPT` 正式化为 spec 条款并增强为主动语言对齐。

## Impact

- **代码**：
  - `mcs/prompts/`：约 10 个 prompt 文件加语言跟随指令（`extract_concepts` / `extract_work_events` / `judge_relations` / `decide_hub` / `generalize` / `gen_summary` / `gen_graph_summary` / `synthesize` / `merge_content` / `gen_aliases`）；`gen_aliases` 示例去中文化。
  - `mcs/prompts/extract_concepts.py`、`mcs/prompts/judge_relations.py`：`node_class` 枚举字面值改 `concept`/`fact` + parse 加英中映射。
  - `mcs_agent/loop.py`：`LANGUAGE_FOLLOW_PROMPT` 增强主动对齐。
- **不动**：LLM 调用签名、数据流、`IngestInput`、存储 schema、`node_class` 存储取值（纯软方案）。
- **向后兼容**：parse 仍接受中文 `node_class` 值，旧库 / 旧测试不破。
- **benchmark**：英文 bench（`multihop_rag` / `locomo` / `longmemeval`）需重建图才吃到修复；中文 bench（`golden_cage`）行为不变。
- **文档**：`CLAUDE.md`（补 prompt 协议层 `node_class` 枚举为 `concept`/`fact`、映射中文常量的表述）、README、`docs/graph-model-design.md` 若提及 `node_class` 字面值处同步。
