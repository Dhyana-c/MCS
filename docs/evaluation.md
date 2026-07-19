# 评测

> MCS 的评测框架在顶层 `bench/` 目录。当前有两类评测：**multihop-rag**（文档级多跳检索）与
> **extraction_quality**（概念 vs 事实抽取准确率）。本文讲框架结构、指标定义与运行方式。
> 评测入口与目录约定也见 [`bench/README.md`](../bench/README.md)。

## 框架结构

```
bench/
├── multihop_rag/            # MultiHop-RAG 检索评测
│   ├── builder.py           # 语料建图（build_shared_graph / _make_mcs）
│   ├── data.py              # 语料 / QA 加载与过滤
│   ├── metrics.py           # Hit@k / Recall@k / MAP@k / MRR@k
│   ├── config/              # 配置
│   ├── data/                # 数据集（不提交）
│   ├── scripts/             # 启动脚本（build / agent_full_run / analyze 等）
│   ├── reports/             # 测试报告（提交）
│   └── README.md            # 详细说明
├── plugins/                 # bench 专用插件（如 doc_rerank，不进核心插件链）
├── extraction_quality.py    # 概念 / 事实抽取准确率评测
├── _env.py                  # 环境变量 / .env 加载
└── README.md                # 评测入口
```

## MultiHop-RAG 检索评测

在 MCS 的 Phase-1 能力区间内评测"跨文档多跳检索"。**一次建图、多 query**：把整个语料摄入同一张共享持久图，
再对所有 query 做检索。

数据集（`bench/multihop_rag/data/`）：609 篇新闻文档 + 2556 个 query（含 question_type 与 evidence_list）。
可从 HuggingFace `yixuantt/MultiHop-RAG` 重新下载。

### 指标（`metrics.py`）

`query()` 返回的节点经 `source_tracking` 扩展映射回**来源文档**（`retrieved_docs`，按 rank 去重），与 gold
`evidence_list` 的来源文档比对。对每个 query 算这四个指标，再按 `question_type`（inference / comparison /
temporal）分组 + overall 汇总：

| 指标 | 含义 |
|------|------|
| **Hit@k** | top-k 是否命中至少一个 gold 文档（0/1） |
| **Recall@k** | top-k 命中的 gold 文档占全部 gold 的比例 |
| **MAP@k** | top-k 的平均精度（命中位置越靠前越高） |
| **MRR@k** | 第一个命中 gold 的倒数排名 |

`null_query`（语料中无答案）从 Hit@k 中排除，单独报"平均检索文档数"作抗干扰诊断。

> **文档级口径**：doc_id = 文档 title，比官方 chunk 级粗，是 MCS 的诚实粒度，仅作自我诊断 / 纵向对比。

### 运行

```bash
# 先建图（一次建图很贵，之后复用该图；幂等续跑）
.venv/Scripts/python.exe bench/multihop_rag/scripts/build.py \
    --output bench/multihop_rag/outputs/run --docs 50 --token-budget 16000

# 小规模真实评测（agent ReAct 轨，限量 N 题）
.venv/Scripts/python.exe bench/multihop_rag/scripts/agent_full_run.py \
    --graph-dir bench/multihop_rag/outputs/run --limit 50

# 全量
```

> 读查询编排（框架 `mcs.query` runner / `python -m bench.multihop_rag`）已退役（retire-framework-query-pipeline）——
> 检索评测改走 agent ReAct 轨（`scripts/agent_full_run.py`）。关键参数：`--limit`（限量题数）、
> `--graph-dir`（图库目录）、`--shard i/k`（分片并发）、`--context-budget`（会话上下文预算）。
> API key 从 `DEEPSEEK_API_KEY` 读取（会尝试自动加载项目根 `.env`）。

> **重排是检索主力**：agent 导航召回好但排名差。排序由评测层文档级重排 `bench.plugins.doc_rerank`
> 离线完成（对 agent 触达节点映射的候选文档词法打分、零额外 LLM）。细节见 [bench/multihop_rag/README.md](../bench/multihop_rag/README.md)。

## extraction_quality 抽取评测

评测 `extract_concepts` prompt **区分概念 vs 事实**的准确率（统一图模型下，概念是名词性实体、事实是含谓词的
命题——分错会污染后续连边与互斥判断）。

需要标注数据集（JSONL），每条含 `text` + `expected`（每项 `name` / `content` / `node_class`）。指标：

| 指标 | 含义 |
|------|------|
| **precision** | 抽出的 `node_class` 正确率（概念被标为概念 / 事实被标为事实） |
| **recall** | 期望条目被抽出的比例 |
| **f1** | precision 与 recall 的调和平均 |

### 运行

```bash
python -m bench.extraction_quality --dataset data/extraction_samples.jsonl
```

Phase 1 是手工小样本验证（~20 条），确认 prompt 方向正确；Phase 2 扩大样本并引入转述嵌套测试。

## 输出管理

- `outputs/` 已加入 `.gitignore`，输出文件不提交；
- 评测报告存 `reports/`，提交到版本控制。

## 进一步阅读

- [bench/README.md](../bench/README.md) — 评测入口与目录约定
- [bench/multihop_rag/README.md](../bench/multihop_rag/README.md) — 检索评测完整说明（重排 A/B、口径）
- [architecture.md](architecture.md) — 被评测的系统本体
