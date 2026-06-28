> ⚠️ **架构修订（change [`mcs-mem-package-extract`](../mcs-mem-package-extract/proposal.md)）**：
> 本 change 原 design D1「代码放 `mcs_agent` 内、端点挂 `mcs_agent` app」已被推翻——记忆功能
> 代码现位于独立 `mcs_mem` 包（单向依赖 `mcs_mem` → `mcs_agent` → `mcs`）；端点经
> `mcs_mem.create_app` 组装、挂同一 FastAPI app。`mcs_agent` 核心（`MemoryStore` / 工具 /
> `MemoryAgent`）不变。下文「挂 `mcs_agent` app」「`mcs_agent/fragments.py`」等措辞应据此
> 理解为 `mcs_mem`。

> 📍 **片归属**：本 change 目录名 `personal-memory-system` 沿用系统总名，但仅实现其中
> **Slice 1（碎片捕获层，capability `fragment-capture`）**。完整 4 片见各片 proposal；归档时
> archive 目录名同此（不重命名，避免 git / `.openspec.yaml` 噪音）。

## Why

MCS 当前是图谱引擎 + `mcs_agent`（ReAct 导航）。缺一个**面向个人日常记忆的低摩擦入口**：随手发条消息就被记下来，事后能查能整理。完整愿景拆成 4 个 change 叠进 `mcs_agent`（全走 agent，不另起独立 app）：

```
本 change  Slice 1  捕获层(碎片 MD)          ← 你在这里
           Slice 2  agent 整合入图           depends-on Slice 1
           Slice 3  日记生成(概括产物)        depends-on Slice 1
           Slice 4  管理 UI                  depends-on 1/2/3
```

> **归档顺序**：Slice 1 → (2, 3) → 4（依赖图决定；先归地基 Slice 1，再并行归 2 / 3，最后归依赖
> 1/2/3 的 Slice 4。`graph-renderer-align`、`mcs-mem-package-extract` 与各片归档顺序解耦）。

本 change 只做**最底层的捕获**：随手记 → 当天 Markdown 碎片文件（零 LLM、零 agent 决策）。它是其余三片的地基。

## What Changes

- 新增 **碎片捕获层（fragment-capture）**：每日一个 Markdown 文件，实时追加用户消息（`HH:MM 内容`），作为原始记录的**保真层**
- 捕获相关 HTTP 端点（`/note`、`/fragments`、`/fragments/{date}`、`PUT /fragments/{date}`）**挂到 `mcs_agent` 现有的 FastAPI app**（不再是独立 app / 独立端口）——"走 agent"接缝由此 change 确立，后续三片复用
- 碎片文件**可人工编辑**，也可经 `PUT` 在管理 UI（Slice 4）里编辑
- **不做** source 注册 / 不入图 / 不调度 / 不概括——那些是 Slice 2/3 的事；本 change 之后碎片只活在 MD 层

## Capabilities

### New Capabilities

- `fragment-capture`: 当天 MD 碎片捕获层——按日期归档、实时追加、人工 / API 编辑、列表 / 读取；端点挂在 `mcs_agent` 的 FastAPI app 上

### Modified Capabilities

（无 spec 级修改——捕获端点作为 `fragment-capture` 自带的 HTTP 契约，复用 `mcs_agent` app 的挂载点，不改写 `memory-agent` 既有需求）

## Impact

- **改 `mcs_agent`**：在其 FastAPI app（`mcs_agent/app.py`）上**新增**捕获路由 + 新增碎片存储模块（如 `mcs_agent/fragments.py`）。这推翻了旧设计"独立 mcs_mem 包 / 不改 mcs_agent"的 D5/D6——见 design「D1 走 agent 接缝」
- **不改 `mcs/` 核心**：捕获层不碰图引擎（不 ingest）
- **存储**：碎片 MD 存配置目录（默认 `~/.mcs_memory/fragments/`，`pathlib.Path.home()` 兼容 Windows）
- **依赖**：无（地基片）；Slice 2/3/4 依赖本片
