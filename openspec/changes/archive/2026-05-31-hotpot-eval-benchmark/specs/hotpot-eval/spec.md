## ADDED Requirements

### Requirement: HotpotQA 数据加载与采样

The system SHALL provide a `HotpotDataLoader` that reads HotpotQA JSON files and supports stratified sampling by type (dev_distractor is entirely `level=hard`, so level is not a stratification dimension).

#### Scenario: 加载 dev_distractor 数据

- **WHEN** 调用 `HotpotDataLoader(path, subset=100)`
- **THEN** 框架 MUST 从 `hotpot_dev_distractor_v1.json` 读取数据，按 type（bridge/comparison）均匀采样 100 条（dev_distractor 全部为 `level=hard`，故不按 level 分层）；MUST 返回 `list[HotpotItem]`

#### Scenario: subset=None 加载全量

- **WHEN** 调用 `HotpotDataLoader(path, subset=None)`
- **THEN** 框架 MUST 返回全部数据项

#### Scenario: HotpotItem 数据结构

- **WHEN** 检查 `HotpotItem` 字段
- **THEN** MUST 包含 `_id`, `question`, `answer`, `supporting_facts`, `context`, `type`, `level`

#### Scenario: 分层采样保证 type 覆盖

- **WHEN** subset=100 且数据包含 bridge 和 comparison
- **THEN** 框架 MUST 在采样结果中包含两种 type；每种 type 的数量 MUST 不为 0

---

### Requirement: Context → MCS ingest 适配

The system SHALL provide an adapter that converts HotpotQA `context` (10 paragraphs of title + sentences) into MCS `ingest()` calls.

#### Scenario: 每条数据的 context 摄入独立 MCS 实例

- **WHEN** 对一条 HotpotItem 执行 ingest
- **THEN** 框架 MUST 为该条数据创建新的 MCS 实例，且该实例 MUST 配置**独立存储**（`sqlite_storage.path=":memory:"` 或每条独立 db 文件），以避免 load-on-startup 加载到其他数据的节点；MUST 将 context 中的 10 个段落逐个调用 `mcs.ingest()`，并传入 `doc_id=_id`、`chunk_id=<段落序号>`、`section_title=<段落标题>` 元数据（否则 source_tracking 不记录来源，supporting_facts 无法提取）

#### Scenario: 段落格式化为 "Title: sentence1. sentence2." 输入

- **WHEN** 将 context 的一个段落 `[title, [s1, s2, ...]]` 转换为 ingest 输入
- **THEN** 框架 MUST 格式化为 `"{title}: {s1}. {s2}. ..."` 字符串

#### Scenario: 摄入完成后的持久化与隔离

- **WHEN** 所有段落摄入完成
- **THEN** 框架 MUST 保证该实例的图与其他数据隔离（独立 `:memory:` 或独立 db 文件），不与全局 `mcs.db` 共享；断点续跑 MUST 依赖运行器维护的 `_id` 进度文件，而非复用落盘的图

---

### Requirement: MCS query → HotpotQA 预测格式转换

The system SHALL provide an adapter that converts MCS `query()` results into HotpotQA prediction format.

#### Scenario: 提取 answer

- **WHEN** `mcs.query(question)` 返回 `List[Node]`
- **THEN** 框架 MUST 从返回节点的 name 和 content 中提取 answer 字符串：
  - 若 answer 为 "yes"/"no" → 检查节点内容是否包含肯定/否定表述，返回 "yes" 或 "no"
  - 若 answer 为实体 → 返回最匹配的节点 name；若多个匹配取 rank 最高者

#### Scenario: 提取 supporting_facts

- **WHEN** `mcs.query(question)` 返回 `List[Node]`
- **THEN** 框架 MUST 从返回节点的 `extensions["source_tracking"]["sources"]` 读取 `section_title` 作为 HotpotQA 的 title；由于 MCS 无句子级溯源，sent_idx MUST 取 0，输出 `[(section_title, 0), ...]`（已知下界，见 design D8）；title MUST 去重

#### Scenario: 查询返回空时的降级

- **WHEN** `query()` 返回空列表
- **THEN** 框架 MUST 输出 answer="" 和 supporting_facts=[]

#### Scenario: 预测文件格式

- **WHEN** 运行器输出预测供 `hotpot_evaluate_v1` 打分
- **THEN** 框架 MUST 写出 `{"answer": {_id: answer_str}, "sp": {_id: [[title, sent_idx], ...]}}` 结构的 JSON（顶层键为 `answer` 与 `sp`）

---

### Requirement: 评测运行器

The system SHALL provide a `HotpotEvalRunner` that drives the full eval pipeline and outputs official metrics.

#### Scenario: 运行完整评测

- **WHEN** 调用 `HotpotEvalRunner(config).run()`
- **THEN** 框架 MUST 依次：加载数据 → 逐条 ingest + query → 提取预测 → 写出预测文件与子集 gold 文件 → 复用 `hotpot_evaluate_v1` 的 `update_answer`/`update_sp` 聚合得到指标字典（不依赖只 `print` 的 `eval()`）

#### Scenario: 输出官方指标

- **WHEN** 评测完成
- **THEN** 框架 MUST 输出 `em`, `f1`, `sp_em`, `sp_f1`, `joint_em`, `joint_f1` 六个指标

#### Scenario: 子集 gold 导出

- **WHEN** subset 不为全量
- **THEN** 框架 MUST 导出只含本次评测 `_id` 的 gold 文件供打分；MUST NOT 用全量 gold（否则未预测的 `_id` 被判 missing 并按全量 `N` 平均，指标被稀释）

#### Scenario: 断点续跑

- **WHEN** 评测中断后重启，且存在进度文件记录已完成的 `_id`
- **THEN** 框架 MUST 跳过已完成的 `_id`，只评估剩余数据

#### Scenario: 进度显示

- **WHEN** 评测运行中
- **THEN** 框架 MUST 打印当前进度（已完成/总数）和每条数据的预测结果

#### Scenario: dry-run 模式

- **WHEN** 调用 `HotpotEvalRunner(config).dry_run()`
- **THEN** 框架 MUST 仅统计预估 token 消耗，不执行 LLM 调用；MUST 输出预估 token 数和费用

---

### Requirement: 评测配置

The system SHALL provide `HotpotEvalConfig` with configurable parameters.

#### Scenario: 配置项

- **WHEN** 检查 `HotpotEvalConfig` 字段
- **THEN** MUST 包含 `data_path: str`, `eval_script_dir: str`（`hotpot_evaluate_v1.py` 所在目录）, `subset: int | None`, `sample_strategy: str`（`"uniform"`/`"proportional"`）, `llm_backend: str`, `output_dir: str`, `dry_run: bool`, `resume: bool`

#### Scenario: 默认值

- **WHEN** 不提供配置
- **THEN** 默认 MUST 为 `subset=100`, `sample_strategy="uniform"`, `llm_backend="deepseek"`, `output_dir="./bench_output"`, `dry_run=False`, `resume=True`
