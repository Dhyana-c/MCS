# MCS 评测框架

本目录组织各类 benchmark 评测，与核心包 `mcs/bench/` 解耦：

- **评测代码**：保留在 `mcs/bench/` 包内，可被外部项目导入使用
- **启动脚本**：位于 `bench/<评测类型>/scripts/`，独立运行、配置硬编码
- **输出文件**：集中到 `bench/<评测类型>/outputs/`，不污染项目根目录

## 目录结构

```
bench/
├── multihop-rag/           # MultiHop-RAG 检索评测
│   ├── config/             # 配置文件
│   ├── data/               # 数据文件（不提交）
│   ├── scripts/            # 启动脚本（无命令行参数）
│   ├── reports/            # 测试报告
│   └── README.md           # 评测说明
├── hotpotqa/               # HotpotQA 多跳问答评测（占位）
│   └── README.md
└── README.md               # 本文档
```

## 评测类型

### MultiHop-RAG

文档级多跳检索评测。一次建图、多 query，指标为 Hit@k / MAP@k / MRR@k。

```bash
# 查看可用脚本
ls bench/multihop-rag/scripts/

# 运行评测（整篇文档摄入）
python bench/multihop-rag/scripts/run_whole_doc.py
```

详见 `bench/multihop-rag/README.md`。

### HotpotQA

标准多跳问答评测。每条数据独立实例，指标为 EM/F1、sp_EM/sp_F1。

目前代码在 `mcs.bench.hotpot`，启动脚本待迁移。

详见 `mcs/bench/README.md`。

## 启动脚本规范

每个脚本：

- 无需命令行参数，配置硬编码或从配置文件读取
- 文件名清晰表达用途，如 `run_baseline.py`、`run_doc_rerank.py`
- 输出目录、db 路径等固定在脚本中

## 输出管理

- `outputs/` 目录已加入 `.gitignore`，输出文件不提交
- 评测报告存放在 `reports/` 目录，提交到版本控制
