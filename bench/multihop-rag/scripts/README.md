# MultiHop-RAG 启动脚本

本目录包含 MultiHop-RAG 评测的启动脚本。每个脚本**无需命令行参数**，配置硬编码。

## 脚本列表

| 脚本 | 用途 | 说明 |
|------|------|------|
| `run_whole_doc.py` | 整篇文档摄入 | 标题+正文作为单个单元，文本 100% 覆盖 |
| `run_baseline.py` | 基线评测 | 切块摄入，不启用重排 |
| `run_node_rerank.py` | 节点级重排 | 启用 LexicalScorer 对节点打分 |
| `run_doc_rerank.py` | 文档级重排 | 对候选文档直接打分排序 |
| `run_dry_run.py` | 成本估算 | 不调用 LLM，估算建图成本 |

## 运行方式

```bash
# 从项目根目录运行
python bench/multihop-rag/scripts/run_whole_doc.py

# 或进入脚本目录运行
cd bench/multihop-rag/scripts
python run_dry_run.py
```

## 配置

脚本配置硬编码在文件中。如需修改：

1. 打开脚本文件
2. 找到 `# 配置（硬编码）` 注释下的变量
3. 修改 DB_PATH、OUTPUT_DIR、CORPUS_SUBSET 等参数

也可使用 `bench/multihop-rag/config/default.json` 作为配置参考。

## 输出

输出目录结构：

```
bench/multihop-rag/outputs/
├── whole_doc/          # run_whole_doc.py 输出
├── baseline/           # run_baseline.py 输出
├── node_rerank/        # run_node_rerank.py 输出
├── doc_rerank/         # run_doc_rerank.py 输出
└── 32k/                # 32k token 预算实验
```

每个输出目录包含：

- `*.db` — SQLite 持久化图
- `metrics.json` — 评测指标
- `llm_calls.jsonl` — LLM 调用记录
- `decisions.log` — 决策日志（部分脚本）

## 数据依赖

脚本默认从 `D:\code\hotpot\MultiHopRAG\` 读取数据。如需使用其他路径，修改脚本中的 `--corpus` 和 `--queries` 参数，或使用 CLI 方式：

```bash
python -m bench.multihop_rag --corpus /path/to/corpus.json --queries /path/to/qa.json
```

## 续跑

所有脚本默认启用 `resume=True`，支持断点续跑。已摄入的文档块自动跳过。
