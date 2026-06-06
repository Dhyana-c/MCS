# MCS HotpotQA 评测框架

HotpotQA 是业界标准的多跳问答 benchmark，天然适合验证 MCS 的核心赌注——"知识有足够的局部性，几跳语义游走就能连到一起"。

## 组织结构

评测代码保留在 `mcs/bench/` 包内，可被外部项目导入使用。启动脚本位于顶层 `bench/` 目录。

```
bench/                     # 启动脚本、配置、报告
├── multihop-rag/          # MultiHop-RAG 评测
│   ├── scripts/           # 启动脚本（无命令行参数）
│   ├── reports/           # 实验报告
│   └── README.md
└── hotpotqa/              # HotpotQA 评测（占位）
    └── README.md

mcs/bench/                 # 评测库代码
├── hotpot.py              # HotpotQA 评测核心
├── multihop_rag.py        # MultiHop-RAG 评测核心
└── doc_rerank.py          # 文档级重排辅助
```

## 概述

MCS 提供 `mcs.bench` 模块，一条命令跑通 HotpotQA 子集评测：

- **数据加载**：从 `hotpot_dev_distractor_v1.json` 加载 + 按 type 分层采样
- **Ingest 适配**：每条数据独立 MCS 实例（`:memory:` 存储），避免跨条污染
- **Query 适配**：从 `List[Node]` 提取 answer + supporting_facts
- **指标计算**：输出 EM/F1、sp_EM/sp_F1、joint_EM/joint_F1

## 数据结构

### HotpotItem

一条 HotpotQA 数据项包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `_id` | str | 数据唯一标识 |
| `question` | str | 多跳问题 |
| `answer` | str | 答案（yes/no 或实体） |
| `supporting_facts` | list[[title, sent_idx]] | 支撑事实来源 |
| `context` | list[[title, sentences]] | 10 个段落（2 支撑 + 8 干扰） |
| `type` | str | bridge / comparison |
| `level` | str | dev 全为 hard |

### 采样策略

- **uniform**：每个 type 平均分配（诊断优先）
- **proportional**：按自然分布比例采样

dev_distractor 共 7405 条，全为 `level=hard`，type 分布为 bridge:comparison ≈ 4:1。

## 评测流程

```
┌─────────────────────────────────────────────────────────────┐
│  加载 HotpotQA 数据                                          │
│  → HotpotDataLoader(path, subset, strategy)                 │
├─────────────────────────────────────────────────────────────┤
│  逐条处理                                                    │
│  for item in items:                                          │
│    ① 创建独立 MCS 实例 (:memory:)                            │
│    ② 摄入 10 个段落 (doc_id=_id, section_title=title)       │
│    ③ query(question) → List[Node]                           │
│    ④ extract_prediction(nodes) → answer + sp                │
│    ⑤ 记录进度                                                │
├─────────────────────────────────────────────────────────────┤
│  输出结果                                                    │
│  → predictions.json                                          │
│  → gold_subset.json                                          │
│  → metrics.json                                              │
└─────────────────────────────────────────────────────────────┘
```

## 预测提取

### Answer 提取

从 `List[Node]` 中提取答案：

- **yes/no 问题**：检查节点内容是否包含肯定/否定表述
- **实体问题**：返回最高 rank 节点的 name

### Supporting Facts 提取

从节点 `extensions["source_tracking"]["sources"]` 提取：

- `section_title` 作为 title
- `sent_idx` 统一取 0（段落级溯源下界）

**注意**：MCS 来源追踪最细只到 chunk/section，没有句子级溯源。段落级摄入下，sp_EM/sp_F1 是下界。

## 断点续跑

评测运行器维护 `progress.json`，记录已完成的 `_id` 列表。重启时自动跳过已完成的数据。

- **续跑粒度**："条"——单条中途崩溃则整条重跑
- **图不复用**：每条数据独立实例，续跑靠 `_id` 进度文件而非复用落盘图

## Token 消耗估算

| 配置 | 预估 tokens | 预估费用 (DeepSeek) |
|------|------------|--------------------|
| 100 条 | ~1.0M | ¥0.14 |
| 500 条 | ~5.0M | ¥0.70 |
| 全量 (7405) | ~77M | ¥120 |

使用 `--dry-run` 模式查看具体估算。

## 使用示例

### 基本用法

```python
from mcs.bench import HotpotEvalRunner, HotpotEvalConfig

config = HotpotEvalConfig(
    subset=100,
    llm_backend="deepseek",
    output_dir="./bench_output",
)

runner = HotpotEvalRunner(config)
metrics = runner.run()
```

### 切换 Claude 后端

```python
config = HotpotEvalConfig(
    subset=100,
    llm_backend="claude",
)
```

### 全量评测

```python
config = HotpotEvalConfig(
    subset=None,  # 全量 7405 条
    sample_strategy="proportional",  # 按自然分布
)
```

### Dry Run

```python
runner = HotpotEvalRunner(config)
estimate = runner.dry_run()
print(estimate)
```

## 关键设计决策

### D1: 评测框架作为独立模块

放在 `mcs/bench/` 下，与核心 `mcs/core/` 解耦。

### D2: 答案提取用规则而非 LLM 综合

规则提取零额外 token 消耗，直接评估 MCS 的召回能力。

### D3: 每条数据独立 MCS 实例

避免跨题干扰，保证评测公平性。

### D4: 按 type 分层采样

让 bridge 和 comparison 都有覆盖，结果更有诊断价值。

### D5: 断点续跑靠 `_id` 进度文件

不依赖共享落盘图（因为每条独立实例）。

### D7: 复用 hotpot_evaluate_v1 的打分函数

导出子集 gold 文件，用 `update_answer/update_sp` 自行聚合。

### D8: 段落级溯源下界

sent_idx 只能取 0，sp_EM/sp_F1 为下界。Phase-2 句子级摄入可提升精度。

## 依赖

- HotpotQA dev_distractor 数据文件（`hotpot_dev_distractor_v1.json`）
- `hotpot_evaluate_v1.py` 评测脚本（依赖 `ujson`，已在 pyproject.toml 添加）
- DeepSeek / Claude API key

## 文件结构

```
mcs/bench/
├── __init__.py       # 导出 HotpotDataLoader, HotpotEvalRunner, HotpotEvalConfig, HotpotItem
├── hotpot.py         # 评测核心代码
├── multihop_rag.py   # MultiHop-RAG 评测核心代码
├── doc_rerank.py     # 文档级重排辅助
└── README.md         # 本文档
```

## 测试

```bash
pytest tests/test_bench_hotpot.py -v
```

测试覆盖：
- 分层采样
- 段落格式化
- answer/supporting_facts 提取
- 评测运行器（mock LLM）
