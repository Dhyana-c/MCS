## Context

这份设计是个人记忆系统 4 片拆分的 **Slice 1（捕获层）**。它取代了旧版 `personal-memory-system`（独立 `mcs_mem` 包 + MD→图 抽取流）的设计——旧设计的数据流方向、包结构、不改 mcs_agent 约束都已在探讨中被推翻，详见各 D 节的「偏离旧设计」。

**全局架构（4 片合起来）**：

```
记录:  消息 ──cheap 追加(本片)──▶ 当天 MD 碎片层 (不经 LLM)
整合:  当天 MD ──去噪(Consolidator应用层) → 逐条 mcs.ingest──▶ 图谱  [Slice 2]
日记:  当天 MD ──LLM 概括──▶ 一篇日记 MD (人读，不进图)              [Slice 3]
召回:  query ──只读 ReAct(/recall，禁 learn)──▶ 图谱推理              [Slice 4]
UI:    mcs_agent/static 管理看板                                    [Slice 4]
```

本片只负责第一行：把消息落成保真的当天 MD 碎片。

现有约束（已对照代码核实）：
- `mcs_agent` 已有 FastAPI app（`mcs_agent/app.py`），挂 `/chat`、`/health`、`/graph/expand`，并在 `/` 兜底挂 `static/`（`StaticFiles(html=True)`）。捕获端点复用这个 app。
- MCS 非线程安全 + SQLite 绑线程，`MemoryStore` 用单 worker 封装。**但捕获层不碰 MCS**（纯文件 IO），故不需要走 worker 线程——捕获是图引擎之外的旁路。

## Goals / Non-Goals

**Goals:**
1. 低摩擦记录：每条消息实时追加到当天 MD 碎片文件，零 LLM 成本
2. 碎片 MD 作为保真原始层，不丢任何输入
3. 碎片可人工编辑（编辑器直接改）+ API 编辑（`PUT`，供 Slice 4 UI）
4. 捕获端点挂在 `mcs_agent` app 上——确立"走 agent"接缝
5. 按日期归档、列表、读取，供 Slice 2（整合读 MD）/ Slice 3（概括读 MD）/ Slice 4（UI 展示）复用

**Non-Goals:**
- 不入图、不调度、不概括（Slice 2/3）
- 不做 source 注册（旧 D9 作废——碎片不再作为 source 连事件）
- 不做实时入图（记录只写 MD；入图交 Slice 2 的夜间 agent 整合，省每条 LLM 成本）

## Decisions

### D1: 走 agent 接缝——捕获端点挂 `mcs_agent` app（推翻旧 D5/D6）

**选择**：捕获的 HTTP 端点加到 `mcs_agent/app.py` 的 `create_app` 里；碎片存储逻辑放 `mcs_agent` 内新模块（如 `mcs_agent/fragments.py`）。**不**新建独立 `mcs_mem` 包、**不**起独立端口。

**偏离旧设计**：旧 `personal-memory-system` 的 D1（独立顶层包 `mcs_mem`）/ D5（子类化 MemoryStore、不改 mcs_agent）/ D6（独立 FastAPI app + 独立端口）全部作废。理由：用户明确"记忆系统走 agent"——agent 是唯一入口/大脑，记录 / 整合 / 召回 / UI 都从 `mcs_agent` 出。一个 app、一个端口、一套前端挂载点，后续三片复用同一接缝。

**代价**：要改 `mcs_agent` 既有文件（app.py 加路由）。可接受——这正是"走 agent"的题中之义。

### D2: 碎片层——纯 Markdown 追加，与 MCS 解耦

**选择**：每日一个 `YYYY-MM-DD.md`，每条消息追加一行 `HH:MM 内容`，时间戳取服务器本地时间。存默认 `~/.mcs_memory/fragments/`。

**与 MCS 线程模型的关系**：捕获是纯文件 IO，**不经** `MemoryStore` 的 worker 线程——它根本不碰 MCS。捕获模块自管文件锁（同进程内追加串行化即可）。

**理由**：MD 是个人知识管理事实标准，可被任何编辑器打开 / 改；整合（Slice 2）/ 概括（Slice 3）读到的就是当前（含手改）内容。`content` 只放消息正文、不含时间前缀——时间走行首 `HH:MM`，解析时分离。

### D3: 编辑——人工编辑 + `PUT` API 双通道

**选择**：碎片 MD 既能用编辑器直接改磁盘文件，也能经 `PUT /fragments/{date}`（整文件覆盖）改——后者供 Slice 4 的网页编辑器。`PUT` 直接覆盖当天文件，不做行级 diff。

**理由**：网页内编辑日记是用户明确要的（Slice 4）。整文件覆盖最简、与"文件是保真层"一致；并发编辑冲突在个人单用户场景可忽略（后续如需要再加版本号乐观锁，不在本片）。

### D4: 命名——`fragment-capture`，把"日记"让给 Slice 3

**选择**：捕获层 capability 命名 `fragment-capture`，文件目录 `fragments/`。**不**沿用旧名 `journal-layer`。

**理由**：架构反转后，"日记 / journal"指的是 Slice 3 LLM 概括的**产物**；捕获层存的是**碎片**（raw fragments）。继续叫 journal 会与产物混淆。

## Risks / Trade-offs

- **[改 mcs_agent]** 捕获路由进 `mcs_agent/app.py` → 与既有 `/chat` 等同居一 app。缓解：路由互不重叠；捕获不依赖 agent / MCS，挂载是纯加法
- **[MD 格式]** 人工编辑可能引入不符 `HH:MM 内容` 的行 → 本片不解析（只存 / 读 / 列表），解析容错是 Slice 2/3 的事；本片对内容无格式约束
- **[`PUT` 覆盖丢内容]** 整文件覆盖若客户端传了残缺内容会丢行 → 缓解：UI（Slice 4）编辑器以"先读全量再整体保存"为契约；保真层本就允许用户改
