# MultiHop-RAG 检索评测

在 MCS 的 **Phase-1 能力区间**内对"跨文档多跳检索"做评测。与 `hotpot.py` 相反，这里是
**一次建图、多 query**：把整个语料摄入**同一张共享持久图**，再对所有 query 做检索。

## 与 hotpot bench 的架构差异

| | hotpot.py | multihop_rag.py |
|---|---|---|
| 图 | 每条数据**独立** `:memory:` 实例 | **一个共享**持久图（SQLite） |
| 摄入 | 每题重建 10 段（用完即弃） | 全语料建一次、长期复用 |
| 续跑 | 按 `_id` 进度文件 | idempotency 跳过已摄入 + query 进度文件 |
| 主指标 | EM/F1/sp（答题口径） | **Hit@k / MAP@k / MRR@k**（检索召回口径） |
| 适配性 | 与 MCS 错配（被迫关掉大图） | 贴合 MCS（考验大图多跳找路） |

## 数据下载

数据集不在仓库内，需从 HuggingFace `yixuantt/MultiHop-RAG` 下载两个文件：

- `multihoprag_corpus.json`（609 篇新闻文档：title/body/source/published_at/url/author/category）
- `multihoprag_qa.json`（2556 个 query：query/answer/question_type/evidence_list）

本地默认路径：`D:\code\hotpot\MultiHopRAG\`。可用 `huggingface-cli download yixuantt/MultiHop-RAG --repo-type dataset` 或网页下载后放入该目录。

## 用法

```bash
# 先估算首建图成本（不调用 LLM）
python -m mcs.bench.multihop_rag --dry-run --corpus-subset 50

# 小规模真实评测（采样 50 篇文档，自动过滤到证据可达的 query）
python -m mcs.bench.multihop_rag --corpus-subset 50 --k 2,4,10

# 全量（一次建图很贵，之后 query 复用该图）
python -m mcs.bench.multihop_rag
```

关键参数：`--corpus-subset N`（采样 N 篇文档并同步过滤 query）、`--db`（共享图落盘路径，
复用即续跑）、`--k`（逗号分隔）、`--max-chunks`（每文档最多切块数，控成本）、`--no-resume`、
`--dry-run`、`--exclude-null`（只评非 null 的可达 query）。API key 从环境变量
`DEEPSEEK_API_KEY` 读取（CLI 会尝试自动加载项目根 `.env`）。

## 查询重排（reranker）与零成本验证

`query()` 召回好但**排名差**（gold 文档中位 rank 36/~165），是 Hit@k 偏低的主因。
零成本词法重排可把 recall@10 从 0.14 拉到 0.81。重排做成一个 **opt-in** 的
`query_postprocess` 插件（`mcs/plugins/phase1/rerank.py`），用查询给 `query()` 返回的
节点打相关性分 → 过滤 → 降序 → 截断 top-N。**默认不启用**，不影响既有评测基线。

bench 侧开关（仅作用于 query 阶段，**不重建图**）：

| 参数 | 含义 | 默认 |
|---|---|---|
| `--rerank` | 启用相关性重排（lexical 打分器，零额外 LLM 调用） | 关 |
| `--rerank-top-n N` | 重排后截断 top-N（`0`=不截断） | 10 |
| `--rerank-min-score F` | 过滤阈值，低于该分丢弃（默认不误杀） | 0.0 |

**验证流程（在现有图上、近乎零成本）**：

1. 先做**零 LLM** 的 reload 自检——序列化修复后，`SQLiteStoragePlugin.load()` 能把历史
   db 里的 `source_tracking` 还原成可用的 `Source`（含向后兼容历史字符串化格式），
   `retrieved_docs` 非空。不需要 API key、不调用 LLM。
2. 再做重排 A/B：复用同一张 `--db`，分别跑**不带**与**带** `--rerank` 的 query 阶段，对比
   `metrics.json` 的 Hit@k / MAP@k / MRR@k。query 阶段只走查询管线，成本远低于建图；
   idempotency 会跳过已摄入的块，**不会重建那张图**。

```bash
# 基线（不重排）
python -m mcs.bench.multihop_rag --db ./multihop_bench.db --output ./mh_baseline
# 重排（同一张图，仅 query 阶段不同）
python -m mcs.bench.multihop_rag --db ./multihop_bench.db --rerank --rerank-top-n 10 --output ./mh_rerank
```

打分器可插拔：`LexicalScorer`（已实装）之外预留了 `EmbeddingScorer` / `LLMScorer` 接口位，
用于后续接住"桥接文档不含查询词"的真·多跳（当前未实装）。

## 指标口径

- **文档级**召回：query() 返回的节点经 `source_tracking` 映射回来源文档（doc_id = 文档 title），
  与 gold `evidence_list` 的来源文档比对。比官方 chunk 级粗，是 MCS 的诚实粒度，仅作自我诊断/纵向对比。
- `null_query`（语料中无答案）从 Hit@k 中排除，单独报"平均检索文档数"作为抗干扰诊断。
- 按 `question_type`（inference/comparison/temporal）分组 + overall 汇总。
