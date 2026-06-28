> ⚠️ **架构修订（change [`mcs-mem-package-extract`](../mcs-mem-package-extract/proposal.md)）**：
> 本 change 原 design「端点挂 `mcs_agent` app、`mcs_agent/diary.py`」已被推翻——日记模块
> 现位于独立 `mcs_mem` 包，端点经 `mcs_mem.create_app` 挂同一 app（单向依赖 `mcs_mem` →
> `mcs_agent` → `mcs`）。下文「挂 `mcs_agent` app」「`mcs_agent/diary.py`」应据此理解为 `mcs_mem`。

## Why

捕获层（Slice 1）攒下当天零散碎片，但碎片是流水账，不好回看。用户想要把**当天的记忆碎片概括成一篇日记**——一段人读的连贯叙述，方便日后翻阅。

这与"整合入图"（Slice 2）是**两个并行的产物**，互不依赖：
- Slice 2：碎片 → 图谱（机器检索 / 推理用）
- Slice 3（本片）：碎片 → 日记（人读用）

二者**筛选标准各自独立**：日记概括当天**全部碎片**，**不**跳过 Slice 2 去噪丢弃的内容——图谱噪声 ≠ 日记噪声（"喝了杯咖啡"对图是噪声、对日记是正经记录）。详见 design D6。

**日记暂不进图**（用户明确）——它是外部产物，不作为节点 / source。

## What Changes

- 新增 **日记生成（diary-generation）**：读当天 MD 碎片（Slice 1 的 `FragmentStore.read`）→ 一次 LLM 概括 → 生成一篇日记 Markdown（连贯叙述），存独立目录
- 日记**不进图**：不 ingest、不建 source 节点、不碰图引擎
- 新增 HTTP 端点（挂 `mcs_agent` app）：`POST /diary`（生成 / 重生成）、`GET /diary/{date}`（读）、`GET /diaries`（列表）
- 与 Slice 2 解耦：日记生成**只依赖 Slice 1**（读 MD），不需要整合先跑

## Capabilities

### New Capabilities

- `diary-generation`: 日记生成——当天 MD 碎片 → LLM 概括 → 一篇日记 MD（人读、不进图）；`/diary*` 端点；可重生成

## Impact

- **依赖 Slice 1**：读碎片用 `FragmentStore`；端点挂同一 `mcs_agent` app；概括复用 `mcs_agent` 的 `llm_call`
- **不依赖 Slice 2**：可独立生成，不需整合
- **存储**：日记 MD 存独立目录（默认 `~/.mcs_memory/diaries/`），与碎片目录分开
- **不碰 `mcs/` 核心 / 图谱**：日记纯外部产物
- **可重生成**：与整合的"单日锁定"不同——日记是无副作用的纯产物，重生成只覆盖文件（见 design D3）
