# 《黄金笼》纯 agent 评测

与 [`multihop_rag`](../multihop_rag/README.md) 平级、目录结构相同的中文小说多跳检索评测。
语料为小说《黄金笼》前 7 章（仓库根 `data/` 下的章节 Markdown），**建图与查询都走
agent 路线**（区别于 multihop_rag 的固定流程管线）：

- **建图**：`MemoryAgent`（ReAct）逐场景决策写入。`learn` 底层复用 MCS 写管线 + 守门；
  两条硬约束由评测侧 `BuildMemory` 保证——写入文本以场景原文钉死（LLM 转述不进图）、
  ingest 注入 `doc_id=场景 title`（文档级溯源）。agent 可在写入后用 `search` 复查、
  `merge`/`split` 收口修图。未调 `learn` 的场景强制补写（记 `forced`），不允许静默丢场景。
- **查询**：`MemoryAgent` 用 `search`/`associate`/`reason`/`generalize`/`arbitrate`
  导航探索（封闭语料 prompt：答案只来自图、找不到答 `Insufficient information.`），
  `CapturingMemory` 捕获触达节点 → lexical `doc_rerank` → 文档级
  hit@k / recall@k / mrr@k（与 multihop_rag 完全同口径）。

## 数据集

- `data/golden_cage_corpus.json` — 141 篇场景级文档（每章按独立 `---` 行切分，
  title 如 `第一章·场景03`；published_at 按章-场景序递增，保持故事内时间语义）
- `data/golden_cage_qa.json` — 150 条 query：inference 50 / comparison 45 /
  temporal 35 / null 20；非 null 证据跨 ≥2 场景、fact 逐字取自场景原文；
  null 的 answer 为 `Insufficient information.`（与官方 MultiHop-RAG 一致）
- 全量问题清单（人工审阅）：[`reports/dataset.md`](reports/dataset.md)
- 两个 json 被 `.gitignore` 忽略（`bench/*/data/*.json`），由脚本重建；
  case 定义源 `scripts/cases.py` 进版本控制

### 重新生成 / 校验数据集

```bash
python bench/golden_cage/scripts/build_corpus.py   # 小说 md → 场景级 corpus
python bench/golden_cage/scripts/build_qa.py       # cases.py → qa.json（内置逐字校验）
python bench/golden_cage/scripts/validate.py       # 独立校验落盘文件
```

测试：`tests/test_golden_cage_dataset.py`。

## 跑评测

```bash
# agent 建图（141 场景，断点续跑；DEEPSEEK_API_KEY 从 .env 读）
python -m bench.golden_cage build
# agent 查询（150 题，断点续跑）+ 指标 + 报告
python -m bench.golden_cage run
# 冒烟
python -m bench.golden_cage build --limit 3
python -m bench.golden_cage run --limit 3
# 只重生报告
python -m bench.golden_cage report
```

启动脚本（无参数）：`scripts/build.py` / `scripts/run.py`。
配置：`config/default.json`（llm / token_budget / max_turns / 输出目录）。

## 产出（`outputs/agent_run/`，不提交）

- `graph.db` — agent 建的共享图
- `build_log.jsonl` — 逐场景建图轨迹（tool_seq / learn 次数 / forced / token / 耗时）
- `results.jsonl` — 逐题查询结果（ranked / reached_gold / 工具与 token 成本 / 回答）
- `metrics.json` + `AGENT_REPORT.md` — 指标与报告（检索指标 + null 封闭语料准确率 + 成本）

## 指标口径

- **文档级**：触达节点经 `source_tracking` 映射回场景文档，与 gold `evidence_list`
  的场景比对；hit@k / recall@k / map@k / mrr@k 按 question_type 分组 + overall。
- **null 题不进 hit@k**：按封闭语料口径判对（回答含 `Insufficient information`），
  另报平均触达文档数作抗干扰诊断。
- **reached（召回天花板）**：gold 出现在触达集中（任意名次）的比例，衡量导航能力，
  与排序无关。
