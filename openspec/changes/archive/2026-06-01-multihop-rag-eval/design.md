## Context

MCS 的核心赌注是"知识有足够的局部性，几跳语义游走就能连到一起"。HotpotQA-distractor 无法验证这一点：它每条数据独立、只给 10 段、用完即弃，逼着我们用每条独立实例（hotpot 的 D3），把 MCS 最核心的"共享、可积累大图"关掉，实测还要 ~90K token/条建一次性图。

MultiHop-RAG 是"共享语料 + 多跳检索"benchmark：一个新闻语料（约 600 篇文档）+ 约 2500 个 query，每个 query 需跨 2–4 篇不同文档取证再推理。它静态、事实一致、无相互矛盾、无时间淘汰——恰好落在 MCS **Phase-1** 能力区间内（共享图、source_tracking、多跳语义游走），不触发尚未实现的 Phase-2（矛盾仲裁/时序淘汰/版本）。

数据集本地尚不存在，需从 HuggingFace `yixuantt/MultiHop-RAG` 下载 `corpus.json` + `MultiHopRAG.json`。

## Goals / Non-Goals

**Goals:**
- 提供 `mcs.bench.multihop_rag`：把整个语料一次建成共享持久图，再对所有 query 检索评测
- 主指标为**检索召回** Hit@k / MAP@k / MRR@k（绕开 MCS 不是答题器的弱点）
- 利用 SQLite 持久化做"build-once、query-many"，并支持复用已建图续跑
- 支持 corpus 子集 + query 同步过滤，控制首建图成本
- dry-run 用实测 token 模型预估费用

**Non-Goals:**
- 不实现矛盾仲裁/时序淘汰/版本（Phase-2，未实现），也不选需要它们的 query 行为
- answer 合成与 answer 准确率不在首期范围（留作后续增强）
- 不追求 SOTA；不复刻官方 chunk 级检索的精确粒度（采用文档级，见 D5）
- 不改造 MCS 核心代码

## Decisions

### D1: 作为 `mcs/bench/multihop_rag.py` 独立模块

复用 `mcs/bench/hotpot.py` 已验证的模式（config dataclass、runner、增量落盘、UTF-8 stdout、官方指标聚合风格），但 ingest/查询架构是全新的"共享图"。与 hotpot 模块解耦、互不影响。

### D2: 共享持久图（build-once、query-many）——与 hotpot 的 D3 相反

**选择**：构建**一个**共享 MCS 实例，把整个语料逐篇 `ingest()` 进同一张图；之后对所有 query 调 `query()`。

**备选**：每个 query 独立实例（hotpot 模式）。

**理由**：MultiHop-RAG 所有 query 共用同一语料、答案需跨文档连接。共享图正是 MCS 的主场：一次建图、查多次，摊薄昂贵的 ingest，并真正考验"大图里几跳找到证据"。每 query 重建既贵又测不到大图导航。

### D3: SQLite 持久化 + resume 复用已建图（load-on-startup 在此是特性）

**选择**：`sqlite_storage.path = <db_path>`（非 `:memory:`）。build 阶段 ingest 整个语料、`auto_persist` 落盘；query 阶段或重启时 `load-on-startup` 直接复用已建图。

**理由**：hotpot 里 load-on-startup 会跨条污染（D3 隔离的敌人）；这里恰恰相反——我们就是要"建一次、之后复用"。`idempotency_check`（doc_id+chunk_id+hash）保证重复 ingest 自动跳过，build 阶段天然可续跑。

### D4: corpus 子集 + query 同步过滤

**选择**：`corpus_subset=N` 时采样 N 篇文档；**必须**同步过滤 queries——只保留 `evidence_list` 的来源文档**全部**落在已摄入子集内的 query。全量时不过滤。

**理由**：若证据文档没被摄入，召回天然为 0，会污染指标、错怪 MCS。过滤保证"可达性"，让指标只反映检索能力。

### D5: Node→evidence 的**文档级**映射与 Hit@k 定义

**选择**：`query()` 返回按 rank 排序的 `List[Node]`；每个 node 经 `extensions["source_tracking"]["sources"]` 取其来源文档标识（doc_id = 文档 title/url，一个 merge 后的概念可能有多个来源，取并集）。去重后得到"按 rank 的来源文档有序列表"。gold = `evidence_list` 去重后的来源文档集合。
- **Hit@k**：top-k 文档中命中的 gold 文档数 / gold 文档总数（召回率）；同时报"是否命中 ≥1"的命中率。
- **MAP@k / MRR@k**：按文档级排名计算。

**备选**：官方的 chunk/fact 级检索匹配。

**理由**：MCS 检索的是"概念节点"，其溯源到文档/chunk，而非官方的句子级 fact。文档级是 MCS 的**诚实粒度**；注明与官方 chunk 级数字不可直接对比。

### D6: null_query 单独诊断，不计入 Hit@k

**选择**：`question_type == "null_query"`（语料中无答案）的 query 从 Hit@k/MAP/MRR 中**排除**，单独报"检索克制度"诊断（如平均返回文档数、是否返回强相关节点）。

**理由**：null_query 没有 gold 证据，纳入召回无意义；它考的是"会不会乱捞/乱编"，属抗干扰诊断，不需要 Phase-2 能力。

### D7: 主指标检索召回，answer 留后续

**选择**：首期只算检索指标。answer 准确率（规则或一次合成调用）作为后续增强。

**理由**：MCS 返回节点名而非答案 span，answer EM 会系统性失真；检索召回直接测"语义游走有没有捞对证据"，是评估 MCS 核心能力的正确镜头。

### D8: 两层断点续跑

**选择**：(1) ingest 阶段靠 `idempotency_check` 自动跳过已摄入文档块；(2) query 阶段维护 query 进度文件（已评估 `query_id`）+ 增量落盘检索结果。resume=True 时复用已落盘图与进度。

**理由**：build 一次很贵、query 很多，两层都要能中断续跑，避免重复付费。

## Risks / Trade-offs

- **[首建图一次性成本]** 语料 ingest ≈ 文档数 × 每文档 token；约 600 篇可能上 ¥几十～上百 → 缓解：`corpus_subset`、dry-run 预估、build 一次长期复用
- **[文档级 vs 官方 chunk 级粒度]** Hit@k 是文档级近似，与官方榜单数字不可直接比 → 注明为 MCS 诚实粒度，仅作自我诊断/纵向对比
- **[source_tracking 依赖]** 映射 Node→文档要求 ingest 时传 `doc_id`（文档标识）→ ingest 适配 MUST 传 `doc_id/chunk_id/section_title`（否则 sources 为空，召回恒 0）
- **[子集可达性]** corpus 子集会让部分 query 证据不可达 → 必须按 D4 过滤 query
- **[查询预算 < k]** `query()` 默认受 `token_budget`/`max_picked` 限制，可能返回不足 k 个不同文档 → k 取值需结合查询预算；必要时为评测调大 `token_budget`/`max_picked`
- **[概念跨文档]** merge 后一个概念可能来自多篇文档 → Hit 判定用节点来源文档的并集，避免漏判

## Open Questions

- 证据匹配是否需要从文档级细化到 chunk/fact 级（首期先文档级）
- k 默认取值（如 [2,4,10]）与查询 `token_budget`/`max_picked` 的关系，是否需为评测单独放大查询预算
- 是否需要一个查询后处理，把 `query()` 结果显式整理成"按 rank 的文档列表"以稳定排名指标