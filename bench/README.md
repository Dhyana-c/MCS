# MCS 评测框架

> 评测入口文档。各评测类型的详细说明见各自的 README。

## 目录结构

```
bench/
├── multihop_rag/           # MultiHop-RAG 检索评测
│   ├── config/             # 配置文件
│   ├── data/               # 数据文件（不提交）
│   ├── scripts/            # 启动脚本（无命令行参数，配置硬编码或从配置文件读取）
│   ├── reports/            # 测试报告
│   └── README.md           # 评测详细说明
├── golden_cage/            # 《黄金笼》纯 agent 评测（结构同 multihop_rag）
├── plugins/                # bench 专用插件（如 doc_rerank）
└── README.md               # 本文档
```

## 评测类型

### [黄金笼（纯 agent）](golden_cage/README.md)

中文小说《黄金笼》前 7 章的场景级多跳检索评测（141 场景 + 150 QA，MultiHop-RAG 格式）。
**建图与查询都走 agent 路线**：ReAct agent 逐场景决策写入（learn 底层复用 MCS 写管线 +
守门，场景原文钉死保真）、agent 导航检索（封闭语料口径），文档级指标与 multihop_rag 同口径。

### [MultiHop-RAG](multihop_rag/README.md)

文档级多跳检索评测。一次建图、多 query，指标为 Hit@k / MAP@k / MRR@k。

关键特性：
- **相关性重排默认开**（recall@10 从 ~0.16 → ~0.73）
- **关键词召回是检索主力**（AliasEntry），分层种子图导航目前边际贡献有限
- 支持 `--whole-doc`（整篇摄入）和 `--no-rerank`（关闭重排做对照）

## 输出管理

- `outputs/` 目录已加入 `.gitignore`，输出文件不提交
- 评测报告存放在 `reports/` 目录，提交到版本控制

## 启动脚本规范

每个脚本：
- 无需命令行参数，配置硬编码或从配置文件读取
- 文件名清晰表达用途
- 输出目录、db 路径等固定在脚本中
