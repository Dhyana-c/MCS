## Context

MCS 的核心假设是"知识有足够的局部性，几跳语义游走就能连到一起"。HotpotQA 的每条数据包含：一个多跳问题、10 个段落（2 个是支撑事实 + 8 个干扰）、答案、支撑事实标注。MCS 需要将段落摄入图谱、通过语义游走找到正确答案和支撑事实。

之前已分析过 token 消耗：全量 7405 条约需 77M tokens（DeepSeek ¥120 / Claude $275）。因此评测框架必须支持子集运行。

已有自动落盘机制（change add-auto-persistence），每条 ingest 后数据可持久化到 SQLite。但本评测为保证每条数据的图隔离（见 D3），默认用独立 `:memory:`/db，不依赖共享落盘做跨条续跑；续跑改由 `_id` 进度文件实现（见 D5）。

HotpotQA 评测脚本 `hotpot_evaluate_v1.py` 提供了 EM/F1（答案准确度）、sp_em/sp_f1（支撑事实召回）、joint_em/joint_f1（联合指标）。

## Goals / Non-Goals

**Goals:**
- 提供 `mcs.bench` 模块，一条命令跑通 HotpotQA 子集评测
- 支持 MCS 端到端评测：context → ingest → query → answer + supporting_facts
- 支持子集采样（100/500/全量），控制 token 消耗
- 输出 HotpotQA 官方指标
- 支持 DeepSeek / Claude 双 LLM 后端
- 支持"断点续跑"：按 `_id` 进度文件跳过已完成的数据（未完成的整条重跑）

**Non-Goals:**
- 不实现 SOTA 竞赛级优化（MCS 不是为 HotpotQA 设计的专用模型）
- 不实现分布式评测（单进程足够）
- 不改造 MCS 核心代码以适配评测（评测是外部消费者）
- 不做 HotpotQA fullwiki 模式（仅 distractor 模式）

## Decisions

### D1: 评测框架作为 `mcs/bench/` 独立模块

**选择**：在 `mcs/bench/` 下新增评测相关代码，与核心 `mcs/core/` 解耦。

**备选**：放在项目根目录 `bench/` 或 `scripts/`。

**理由**：作为 `mcs` 包的子模块，可以直接 `from mcs.bench import ...` 复用 MCS 核心；同时通过 `__init__.py` 的命名空间隔离，不影响核心代码。

### D2: 答案提取策略——从查询结果节点中提取

**选择**：`query()` 返回 `List[Node]` 后，通过规则提取 answer：
- 如果 answer 是 yes/no → 检查返回节点的 content/statements 中是否包含肯定/否定表述
- 如果 answer 是实体 → 检查返回节点的 name 和 content 中是否包含该实体
- 支撑事实 → 返回节点 `source_tracking` 的 `section_title` 与 `supporting_facts` 中的 title 匹配（sent_idx 取 0，见 D8）

**备选**：增加一次 LLM 调用让模型从返回节点中综合回答。

**理由**：规则提取零额外 token 消耗，且能直接评估 MCS 的召回能力（如果召回了正确节点，规则提取就能命中；如果没召回，LLM 也变不出答案）。LLM 综合回答可以作为 Phase 2 增强但不是评测 MCS 图谱能力的正确方式。

### D3: 每条数据独立摄入而非全局共享图

**选择**：每条 HotpotQA 数据创建新的 MCS 实例，独立摄入该条数据的 10 个段落。

**备选**：所有数据共享一个全局图，逐条摄入。

**理由**：HotpotQA 的每条数据是独立的问答对，段落之间无关联。共享图会导致跨题干扰——前面题目的节点可能影响后面题目的查询路由。独立实例保证评测公平性，且可并行。

**关键实现约束**：默认配置的 `sqlite_storage.path = "mcs.db"` 是全局共享文件，而 `MCS.initialize()` 末尾的 load-on-startup（`_try_load_from_storage`，仅在图为空时触发）会把已落盘的所有节点加载进新实例。若每条数据复用同一个 db，第 N 条的图会被前 N-1 条的节点污染，D3 的隔离形同虚设。因此评测运行器 MUST 为每条数据配置**独立存储**：要么 `sqlite_storage.path = ":memory:"`，要么每条一个独立文件（如 `{output_dir}/graphs/{_id}.db`）。默认采用 `:memory:`（图不跨条复用，落盘仅为可选的事后检查）。

### D4: 采样策略——按 type 分层采样

**选择**：默认按 type（bridge/comparison）均匀采样，确保两类都有覆盖。

**备选**：随机采样 / 顺序截取 / 按自然分布比例采样。

**理由**：bridge 和 comparison 的多跳模式不同，MCS 可能对其中一种更擅长，type 分层让结果更有诊断价值。

**注意（数据事实）**：`hotpot_dev_distractor_v1.json` 共 7405 条，**全部为 `level=hard`**（easy/medium 仅存在于 train 集），因此**不按 level 分层**——`HotpotItem.level` 字段保留但在 dev 集恒为 `"hard"`。此外 type 的自然分布为 bridge:comparison ≈ 5918:1487（≈4:1），"均匀采样"会相对过采样 comparison；如需贴合自然分布，用 `sample_strategy="proportional"`。默认 `sample_strategy="uniform"`（诊断优先）。

### D5: 断点续跑——利用 SQLite 持久化

**选择**：评测运行器把已完成的 `_id` 列表记录到进度 JSON 文件（如 `{output_dir}/progress.json`），重启时跳过已完成的数据。断点续跑粒度是"条"——单条中途崩溃则整条重跑。

**备选**：不做断点续跑，失败就重来。

**理由**：100 条子集约需 1M tokens，跑完需要时间。中途崩溃后能续跑是实用性要求。但注意 D3 选择了每条数据独立实例，所以断点续跑的核心是"记录已评估的 `_id`"，而不是"复用已有图"（因为每条数据的图是独立的）。

### D6: 评测输出格式

**选择**：输出 JSON 文件，包含每条数据的预测结果 + 汇总指标。同时打印人类可读的摘要到终端。

**备选**：仅打印终端输出 / 仅输出文件。

**理由**：JSON 文件可供后续分析和可视化；终端输出方便即时查看进度和结果。

### D7: 集成 hotpot_evaluate_v1 的方式

**选择**：复用 `hotpot_evaluate_v1.py` 的打分函数，不修改原脚本：
1. 运行器把预测写成 `{"answer": {_id: answer_str}, "sp": {_id: [[title, sent_idx], ...]}}` 结构的 JSON 文件（键为 `answer` 与 `sp`）。
2. 运行器导出**子集 gold 文件**——只含本次评测的 `_id`（结构同原始数据项）。
3. 通过 `from hotpot_evaluate_v1 import update_answer, update_sp` 复用打分逻辑，自己跑聚合循环得到 metrics 字典。

**备选**：直接调用 `eval(pred_file, gold_file)`。

**理由**：原脚本的 `eval()` 有两个坑——(a) 它只 `print(metrics)` 并 `return None`，拿不到返回值；(b) 它顶部 `import ujson`，而当前 `.venv` 未安装 ujson，直接 import 模块会 `ModuleNotFoundError`。因此把 **`ujson` 加入评测依赖**（满足"不改原脚本"），并复用 `update_answer/update_sp` 自行聚合以拿到指标字典。

**关键坑（gold 必须切子集）**：`eval` 按 `N = len(gold)` 求平均。若 gold 用全量 7405 条、预测只有 100 条，其余 7305 条会被判 missing 并按 0 计入，指标被稀释成约 1/74。所以子集模式 MUST 导出对应子集的 gold 文件。

### D8: supporting_facts 的来源粒度

**选择**：每个段落作为一个 chunk 摄入（`doc_id=_id`、`chunk_id=段落序号`、`section_title=段落标题`），source_tracking 因此记录到**段落级**来源。query 端从 `node.extensions["source_tracking"]["sources"]` 取 `section_title` 作为 HotpotQA 的 title，sent_idx 统一取 0。

**备选**：每个**句子**作为一个 chunk 摄入（`chunk_id=sent_idx`），让 source_tracking 记录到句子级，从而精确还原 `(title, sent_idx)`。

**理由**：HotpotQA 的 sp 是 `(title, sent_idx)`，但 MCS 的来源追踪最细只到 chunk/section，没有句子级溯源。段落级摄入符合 design 既定的 token 成本预算（每条 ~10 次 ingest）；句子级会把 ingest 次数放大 ~4 倍、token 与费用同比上升。**代价**：段落级方案下 sp_em/sp_f1 是**下界**（sent_idx 只能猜 0）。句子级摄入作为 Phase-2 增强，可让 sp 指标变得可比。

## Risks / Trade-offs

- **[答案提取不准]** 规则提取可能漏掉已召回的正确信息 → 缓解：这是评测 MCS 召回能力的下界；若规则提取 EM=0 但节点召回率高，说明需要 LLM 综合回答（Phase 2）
- **[token 消耗]** 即使 100 条子集也需 ~1M tokens → 缓解：支持配置开关和采样大小；提供 dry-run 模式仅统计预估 token
- **[评测耗时]** 每次 ingest 涉及多次 LLM 调用，100 条可能需要 10+ 分钟 → 缓解：支持断点续跑；显示进度条
- **[MCS 不是 QA 模型]** MCS 是记忆系统不是问答模型，EM/F1 可能不高 → 这是预期内的；评测目的是诊断图谱构建和语义游走的瓶颈，而非追求 SOTA
- **[sp 粒度下界]** MCS 来源追踪无句子级溯源，段落级方案下 sent_idx 只能取 0，sp_em/sp_f1 为下界 → 缓解：Phase-2 句子级摄入（D8 备选）；当前以 sp_recall（按 title 命中）作为辅助诊断指标
- **[图污染]** 每条数据复用共享 db 会被 load-on-startup 污染（见 D3）→ 缓解：每条独立 `:memory:` 或独立 db 文件
- **[依赖 ujson]** `hotpot_evaluate_v1.py` 顶部 `import ujson`，未安装则 import 失败 → 缓解：把 ujson 列入评测依赖（见 D7）
