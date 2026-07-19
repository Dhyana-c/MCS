## Phase 0: 依赖（独立框架 change，不在本 change 实现）

- [ ] T0 `work-event-anchor-resolution`（仅跟踪依赖，不在此实现）：`extract_work_events` prompt 放宽——文本内含显式时间锚点时，相对时间 MAY 解析为 ISO 绝对时间；无锚点保留原文形态；"建安五年"类作品纪年行为不变。边界测试：有锚点解析（yesterday→ISO）、无锚点保持原样、作品纪年不受影响。本 change 的 temporal 类评测依赖它（D11）；未落地也可先跑（temporal 如实反映缺口，作为修复前基线）

## Phase 1: LoCoMo 评测框架

### T1: 数据拉取与三源合成

- [x] 实现 `bench/locomo/scripts/download_data.py`：探测复用 `bench/longmemeval/data/locomo_repo|locomo_v2`（校验通过则 **copy** 到 `bench/locomo/data/`，不重复下载、不影响姊妹 change）；否则从 GitHub 克隆 V1（`snap-research/locomo`）+ V2（`BrianV1981/locomo-v2`，含 Zone.Identifier restore）；校验数据文件存在 + 大小合理
- [x] 实现 `bench/locomo/data.py`：数据类 `LoCoMoSession`/`LoCoMoTurn`/`LoCoMoQA`/`LoCoMoDoc`；`LoCoMoDataLoader` 三源合成（D1：V2 base 主体 + caption 变体按 `dia_id` 移植 + V1 evidence 按**换名映射**移植）；caption 变体 conversation 与 base 逐轮一致性校验；时间戳解析 `"%I:%M %p on %d %B, %Y"`；会话排序；`filter_by_category`；预处理缓存到 `data/preprocessed/`；类别映射校验 `{1:261,2:308,3:94,4:821,5:438}`
- [x] 测试：换名映射边界（名字是常用词前缀时的词边界）、无 evidence 题处理、时间戳格式全量、caption 移植数=834、evidence 命中率≥95%、类别分布漂移报错

### T2: 对话式 ingest 建图（双轨事件）

- [x] 实现 `bench/locomo/builder.py`：`build_locomo_graph(doc, llm, db_dir)` 按会话顺序 ingest；会话→文本拼接（`[时间] 说话者: 内容`，带 caption 轮追加 ` [shared image: {caption}]`）；`IngestInput(content, timestamp=会话时间ISO, work_id=sample_id, metadata={doc_id, chunk_id=session_N})`；每 doc 独立 `locomo_{sample_id}.db`；resume（db 已存在则跳过）
- [x] 建图后自检：叙事事件数 > 0、narr_timestamp 可排序比例、universe 归属正确（抽查）—— `selfcheck_graph`
- [x] 框架 query 基线：`mcs.query()` 对照（抽样）—— T4 `run_retrieval_eval`（framework mcs.query 检索轨）
- [x] 测试：拼接格式、work_id 启用 ③b（叙事事件落对话 universe）、当下事件落 `__reality__`、resume 行为（用 mcs_with_mock_llm 真实 ingest，不 mock LLM）

### T3: 评测指标

- [x] 实现 `bench/locomo/metrics.py`：主指标 LLM-judge 正确率（5 类分项）；副指标 F1（token-level with stemming）、时间偏移容忍（temporal 单列）、rubric（open-domain）；检索轨 session 级 Recall@k（any/all-evidence hit，k=5/10/20）；adversarial 弃答交 LLM judge（不用关键词匹配）；聚合报告
- [x] 测试：dia_id→session 映射、any/all-evidence hit 判定、F1 计算、口径分离（F1/时间容忍不混入主表）

### T4: Agent 评测脚本

- [x] 实现 `bench/locomo/scripts/agent_eval.py`：加载对话→建图→agent 逐题评测→写结果 JSONL；agent prompt 适配（peer-to-peer，temporal 题提示优先 `timeline(universe=对话)`）；adversarial 弃答交 judge；逐题 resume；`--max-conversations N`（conv-26 优先）+ 检索轨 `run_retrieval_eval`（framework `mcs.query` 基线）
- [x] 实现 `bench/locomo/scripts/analyze.py`：汇总结果→REPORT.md；基线对比表（逐行注明口径：Mem0 92.5% LLM-judge 排除 adversarial、Zep 94.7% LLM-judge、Human 87.9 F1）；口径分离

### T5: 配置 + 文档

- [x] `bench/locomo/config/default.json`
- [x] `bench/locomo/README.md`：使用说明 + 数据下载 + 成本预估
- [x] `bench/locomo/data/README.md`：数据获取说明（数据不入 git）
- [x] `.gitignore` 补充：`bench/locomo/data/locomo_*/`、`bench/locomo/data/preprocessed/`（`bench/*/outputs/` 已有）

## 依赖关系

```
T0（独立 change，可与 T1-T3 并行）
T1 → T2 → T3 → T4 → T5
T4 的 temporal 完整评测依赖 T0 落地（未落地可先跑，作为修复前基线）
```

## 预估成本（基于 golden_cage 实测重估；会话数实测 272）

| 阶段 | LLM 调用 | 预估 token | 说明 |
|------|---------|-----------|------|
| Ingest（272 会话） | ~272 × 4 | ~2M | 每次 ~7K token（extract_concepts + judge_relations + extract_work_events + 守门） |
| Agent QA（1922 题） | ~1922 × 10 | ~42M | 每题 ~22K token（agent 多轮工具循环） |
| LLM judge（1922 题） | ~1922 | ~5M | 每题 ~2.5K token |
| 框架 query 对照（抽样 ~300 题） | ~300 | ~2.4M | 每题 ~8K；全量 1881 题 ~15M 按需 |
| **合计** | | **~51M** | 原估 800K 低了 60+ 倍 |

**执行策略**：先跑单对话 conv-26（194 题，~5M token）验证全链路——重点看 ③b 叙事事件抽取质量（对话语料首次）、narr_timestamp 可排序比例、timeline 工具命中率——确认后再决定全量。
