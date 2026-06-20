## Why

`docs/graph-model-design.md` §5.1 把 ingest 定义为**统一流程**：① 规则入库（整个输入存为事件、source 按类型切分，不经 LLM）→ ③ LLM 只抽 content 的概念 / 事实 → ④ 事件 / source 对抽出节点连背书边。但当前代码只实现了概念 / 事实那条路——`ingest(text)` 从不产生事件 / source，`ingest_event` / `ingest_source` 是从不被 `ingest` 调用的游离手工方法。结果是**出处与时间轴模型缺失**（无法回答"我何时、从哪份资料学到这个概念"），且代码与已写定的设计背离。docs-migration 把这个缺口暴露了出来；本 change 把代码对齐到 §5.1。

## What Changes

- **BREAKING**：`ingest` 输入从 `str` 改为**结构体**（`content` + `timestamp` + 可选 `source` 元信息 + 自由字段）。`str` 仍接受——经向后兼容重载薄封装为"当前时间戳 + 无 source"，老调用零改动。
- **每次 ingest 把整个输入记为一个事件节点**（带 `timestamp`）——这是**记录行为**本身（"我何时记下这段输入"），落在用户时间轴上。content 内转述的过去事件（"三年前发生 X"）仍按既有规则抽成**带时间属性的事实**，不盖成时间轴事件（保持 `unified-graph-schema` 既有契约）。
- **source 元信息按规则切分**存为 source 节点（不经 LLM，保真不改写）。
- **LLM 只解析 content** → 概念 / 事实，对齐已有节点；事件 / source 对抽出的概念 / 事实连 `关联` 背书边。
- `ingest_event` / `ingest_source` 从游离方法变为**统一 ingest 内部调用的规则原语**（保留为低层入口）。
- 写流程由"7 段"扩为含**规则入库段**；`WriteContext` 增事件 / source 节点字段。
- 保持**载重规则**（核心节点 `get_relations` 过滤事件边）与**"事件 / source 靠规则、不经 LLM"铁律**不变。
- 同步更新调用方（`mcs_mcp` ingest 工具、`mcs_agent.learn` / `MemoryStore`、`bench/multihop_rag/builder`、`examples`）与文档（graph-model-design §5.1 去过渡注、api-reference、getting-started、architecture）。
- **先改宪法**：`CLAUDE.md` 总体流程 + graph-model-design §5.1 补"每次 ingest 整个输入记为一个事件"，再改代码。

## Capabilities

### New Capabilities

（无——本 change 修改既有 ingest 契约，不引入新能力。）

### Modified Capabilities

- `write-pipeline`: ingest 输入改结构体（向后兼容 `str`）；新增**规则入库段**（每次 ingest 整存为事件节点 + source 节点切分，不经 LLM）；LLM 仅作用于 content；事件 / source 对抽出概念 / 事实连背书边；`WriteContext` 增事件 / source 字段；明确"每次 ingest = 一条记录事件"且与"转述过去→事实"区分。

## Impact

- **API（BREAKING + 兼容垫片）**：`MCS.ingest` / `WritePipeline.ingest` 签名；新增结构化输入数据类（如 `IngestInput`，置于 `mcs/entities/`）。
- **核心**：`WritePipeline` 新增规则入库段，复用 `ingest_event` / `ingest_source` 原语建事件 / source 节点 + 背书连边；`WriteContext` 增字段；载重规则（store 层 `get_relations` 事件边过滤）须验证不被破坏。
- **调用方**：`mcs_mcp/server.py`（ingest 工具）、`mcs_agent`（`learn` / `MemoryStore`）、`bench/multihop_rag/builder.py`、`examples/basic_usage.py` 与 `wiki_example.py`。
- **文档**：graph-model-design §5.1（去"过渡态"注、转为已实现）、api-reference（ingest_event/source 表述）、getting-started、architecture 写入流程。
- **宪法**：`CLAUDE.md` 总体流程 + graph-model-design §5.1 补"每次 ingest = 一个事件"。
- **测试边界**：纯文本（无 source）兼容；带 source 切分；每次 ingest 恰一个事件节点；事件 / source → 概念 / 事实背书边正确；核心节点 `get_relations` 仍过滤事件边（载重不漏）；str 向后兼容路径。
