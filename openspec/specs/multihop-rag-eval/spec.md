## Purpose
定义 MultiHop-RAG 评测流程，包括数据加载与子集过滤、共享图构建（build-once）、查询评测及 Hit/MRR 指标计算。

## Requirements

### Requirement: MultiHop-RAG 数据加载

The system SHALL provide a loader that reads MultiHop-RAG `corpus.json` (documents) and `MultiHopRAG.json` (queries with evidence), and supports corpus subsetting with synchronized query filtering.

#### Scenario: 加载语料与查询

- **WHEN** 调用加载器并提供 `corpus_path` 与 `queries_path`
- **THEN** 框架 MUST 返回文档列表（含 title、body、source、published_at、url）与查询列表（含 query、answer、question_type、evidence_list）

#### Scenario: 数据缺失时的明确报错

- **WHEN** `corpus_path` 或 `queries_path` 不存在
- **THEN** 框架 MUST 抛出清晰错误，提示从 HuggingFace `yixuantt/MultiHop-RAG` 下载数据集

#### Scenario: corpus 子集与 query 过滤

- **WHEN** 指定 `corpus_subset=N`
- **THEN** 框架 MUST 采样 N 篇文档，并 MUST 只保留 `evidence_list` 来源文档全部落在已采样子集内的 query（证据不可达的 query 被排除）

#### Scenario: 全量不过滤

- **WHEN** `corpus_subset=None`
- **THEN** 框架 MUST 摄入全部文档并保留全部 query

---

### Requirement: 共享图构建（build-once）

The system SHALL build a single shared, persisted MCS graph by ingesting the entire (possibly subset) corpus, and SHALL skip already-ingested documents on resume.

#### Scenario: 全语料摄入同一实例

- **WHEN** 执行构建
- **THEN** 框架 MUST 创建**一个**共享 MCS 实例（`sqlite_storage.path` 指向持久化 db，而非 `:memory:`），并 MUST 把每篇文档逐块 `ingest()` 进该实例；MUST 传入 `doc_id`（文档标识）、`chunk_id`、`section_title` 元数据以填充 source_tracking

#### Scenario: 重复构建自动跳过

- **WHEN** 在已存在的 db 上再次构建
- **THEN** 框架 MUST 依赖 `idempotency_check` 跳过已摄入的文档块，不重复消耗 LLM

#### Scenario: 复用已建图查询

- **WHEN** 构建完成后进入查询阶段（或重启后 resume）
- **THEN** 框架 MUST 通过 load-on-startup 复用已落盘的图，不重新摄入

---

### Requirement: 查询→证据映射与检索指标

The system SHALL convert each query's `query()` result into a ranked list of source documents and compute retrieval metrics against the gold evidence documents.

#### Scenario: Node 映射到来源文档

- **WHEN** `mcs.query(question)` 返回 `List[Node]`
- **THEN** 框架 MUST 从每个 node 的 `extensions["source_tracking"]["sources"]` 取来源文档标识（一个概念有多个来源时取并集），按 node rank 去重得到"按 rank 的来源文档有序列表"

#### Scenario: 计算 Hit@k / MAP@k / MRR@k

- **WHEN** 已得到检索文档排名与该 query 的 gold 证据文档集合
- **THEN** 框架 MUST 在配置的每个 k 上计算 Hit@k（top-k 命中的 gold 文档召回率）、MAP@k、MRR@k

#### Scenario: 查询返回空

- **WHEN** `query()` 返回空列表
- **THEN** 框架 MUST 记该 query 检索结果为空（所有 k 上 Hit/MAP/MRR 计 0），不报错

---

### Requirement: null_query 诊断

The system SHALL evaluate `null_query` items separately from retrieval recall.

#### Scenario: null_query 不计入召回

- **WHEN** query 的 `question_type == "null_query"`
- **THEN** 框架 MUST 将其从 Hit@k/MAP@k/MRR@k 统计中排除，并 MUST 单独报告检索克制度诊断（如平均返回文档数）

---

### Requirement: 评测运行器与断点续跑

The system SHALL provide a runner that drives build + query + metrics, supports two-level resume, and outputs results.

#### Scenario: 完整评测流程

- **WHEN** 调用运行器的 run
- **THEN** 框架 MUST 依次：加载数据（+子集过滤）→ 构建共享图 → 逐 query 检索并映射证据 → 计算并输出 Hit@k/MAP@k/MRR@k 及 null_query 诊断

#### Scenario: 两层断点续跑

- **WHEN** 评测中断后以 resume 重启
- **THEN** 框架 MUST 复用已落盘的图（ingest 阶段靠 idempotency 跳过），并 MUST 依据 query 进度文件跳过已评估的 `query_id`

#### Scenario: 增量落盘

- **WHEN** 每个 query 评估完成
- **THEN** 框架 MUST 增量落盘检索结果与进度，崩溃不丢已完成工作；stdout 输出 MUST 为 UTF-8 安全

#### Scenario: dry-run 预估

- **WHEN** 以 dry-run 模式调用
- **THEN** 框架 MUST 仅用实测 token 模型预估首建图 token 与费用，不执行 LLM 调用

---

### Requirement: 评测配置

The system SHALL provide a config dataclass with the parameters needed to run the benchmark.

#### Scenario: 配置项

- **WHEN** 检查配置字段
- **THEN** MUST 包含 `corpus_path: str`, `queries_path: str`, `corpus_subset: int | None`, `llm_backend: str`, `db_path: str`, `output_dir: str`, `k_values: list[int]`, `resume: bool`, `dry_run: bool`

#### Scenario: 默认值

- **WHEN** 不提供配置
- **THEN** 默认 MUST 为 `corpus_subset=None`（全量）, `llm_backend="deepseek"`, `k_values=[2, 4, 10]`, `resume=True`, `dry_run=False`