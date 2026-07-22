# LoCoMo 对话记忆评测

> LoCoMo（ACL 2024, arXiv:2402.17753）面向**长期对话记忆**的评测基准。10 个虚构人物对
> 的多轮对话（272 会话 / 5882 轮 / ~182K token）+ 1922 道 QA，覆盖 5 类能力。设计依据见
> `openspec/changes/conversational-memory-bench/`（proposal / design / specs）。

## 为什么是 LoCoMo

MCS 的**双轨事件模型**（当下事件 vs 谈话中的事件）、universe 时间轴、互斥裁决、agent 工具
（timeline/search）恰恰是为长期对话记忆设计的——LoCoMo 几乎为 MCS 的能力面定制：

| 能力 | LoCoMo 题型（V2 数量） | MCS 对应 |
|---|---|---|
| 时间推理 | temporal（cat 2，308） | ③b 叙事事件层 + universe 时间轴 + `timeline` 工具 |
| 错误归因检测 | adversarial（cat 5，438） | null 诚实口径 + 互斥边 |
| 跨会话推理 | multi-hop（cat 1，261） | BFS 语义游走 + agent 探索 |
| 单点事实 | single-hop（cat 4，821） | 基础检索 |
| 开放推理 | open-domain（cat 3，94） | 概念网络覆盖度 |

横向基线：Mem0 92.5%（LLM-judge，排除 adversarial）、Zep 94.7%（LLM-judge）、Human 87.9（token-F1）。

## 数据三源合成（D1）

- **V2 base conversation + QA 为唯一主体**（V2 是去污染换名版，迫使 agent 依赖真实检索
  而非模型权重背答案）。
- **caption**：按 `dia_id` 从 V2 caption 变体（默认 moondream，834 轮）移植 VLM caption。
- **evidence**：按换名映射（仅由两版 `speaker_a/b` 机械建立，词边界 + 大小写不敏感，**不经
  LLM**）把 V1 evidence 移植到 V2 题（命中率 ~97%，诊断用）。

数据拉取见 [`data/README.md`](data/README.md)。`LoCoMoDataLoader` 校验类别分布
`{1:261, 2:308, 3:94, 4:821, 5:438}`、caption 移植数 834、evidence 命中率 ≥ 95%（漂移报错）。

## 双轨事件（D3/D4）

每会话一次 `mcs.ingest(IngestInput(content, timestamp=会话ISO, work_id=sample_id))`：

- **当下事件**（摄入行为，规则产生）：落 `__reality__` 时间轴（"这场对话 5 月 8 日发生了"）。
- **谈话中的事件**（③b `extract_work_events` LLM 抽取）：落对话 universe 叙事时间轴
  （"Sarah 5 月 7 日去了互助会"）——temporal 题的答案来源（经 `timeline(universe=对话)` 查询）。

> 相对时间（"yesterday"）→ 绝对日期的解析依赖配套 change `work-event-anchor-resolution`
> （T0，独立框架 change）。未落地前 temporal 类如实反映缺口（~71% 题受影响）——这本身是
> 有价值的基线。

每对话独立 SQLite db（`locomo_{sample_id}.db`，D4）。

## 双轨评测（D5/D7）

- **QA 轨**（1922 题，主指标）：`agent.chat(question)` → LLM 生成答案 → LLM judge 判对错。
  agent 工具集含 `timeline`（temporal 题查叙事时间轴）。adversarial 弃答判定交 judge（不用
  关键词匹配）。
- **检索轨**（evidence 题，诊断副指标）：记忆 agent 触达节点（含 search 种子 + associate
  邻居）经 `bench.plugins.doc_rerank` 离线重排 → session 级 Recall@k（any/all-evidence hit）。
  框架 `mcs.query()` 检索轨已随 retire-framework-query-pipeline 退役（改由 agent 触达驱动）。

**口径分离**（spec 硬要求）：主表仅 LLM-judge 正确率；F1 / 时间容忍 / 检索 Recall 为副表，
不混入同一对比表。

## 用法

```bash
# 0. 数据（探测复用 bench/longmemeval/data 下既有 clone，copy 到 bench/locomo/data）
python -m bench.locomo download

# 1. 试点：单对话 conv-26（194 题，~5M token 验证全链路）
python -m bench.locomo eval --sample-id conv-26

# 1b. 冒烟：限量每对话前 N 题（控成本验证链路）
python -m bench.locomo eval --sample-id conv-26 --max-questions 5

# 2. 汇总报告
python -m bench.locomo analyze

# 或全流程（限量 N 对话，conv-26 优先）
python -m bench.locomo all --max-conversations 1
```

环境变量（`.env`）：`DEEPSEEK_API_KEY`（必需）、`DEEPSEEK_MODEL`（默认 `deepseek-chat`）、
`DEEPSEEK_BASE_URL`。`MCS_NO_SUMMARY_REGEN=1` 默认开启（省 ~2.6× LLM 调用）。

断点续跑：建图按 db 文件存在跳过；评测按 qid 跳过（`results.jsonl` append 模式）。

## 成本（基于 golden_cage 实测重估）

| 阶段 | 预估 token | 说明 |
|---|---|---|
| Ingest（272 会话） | ~2M | 每次 ~7K（extract_concepts + judge_relations + extract_work_events + 守门） |
| Agent QA（1922 题） | ~42M | 每题 ~22K（agent 多轮工具循环） |
| LLM judge（1922 题） | ~5M | 每题 ~2.5K |
| 检索轨（抽样） | ~2.4M | 每题 ~8K |
| **合计** | **~51M** | |

**策略**：先跑 conv-26 单对话（~5M）验证全链路（③b 抽取质量、narr_timestamp 可排序比例、
timeline 命中率），确认后再放量。

## 结构

```
bench/locomo/
├── data.py              # 三源合成装载（LoCoMoDataLoader）
├── builder.py           # 对话式 ingest 建图（双轨事件）+ selfcheck_graph
├── metrics.py           # judge 主指标 + F1/时间容忍副指标 + 检索 Recall@k
├── __main__.py          # CLI：download / build / eval / analyze / all
├── scripts/
│   ├── download_data.py # 数据拉取（探测复用 copy）
│   ├── agent_eval.py    # QA 轨 + 检索轨 + 编排
│   └── analyze.py       # 汇总 REPORT.md（口径分离 + 基线对比）
├── config/default.json
├── data/                # 数据（不入 git）
└── outputs/             # 图 db + 结果 jsonl + REPORT.md（不入 git）
```
