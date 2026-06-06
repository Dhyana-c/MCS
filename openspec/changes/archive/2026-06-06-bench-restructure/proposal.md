## Why

当前 `mcs/bench/` 目录混杂了评测代码、运行脚本和报告文档，且位于 `mcs/` 包内部，导致：
1. 评测代码与核心包耦合，增加包体积
2. 输出文件（db、报告）散落在项目根目录，难以追踪和管理
3. 启动脚本（如 `_run_multihop_chat_200_whole.py`）参数各异、无统一规范

将 bench 独立出来，按评测类型组织目录结构，统一启动脚本规范，便于后续扩展和维护。

## What Changes

### 目录结构调整

**新建顶层 `bench/` 目录，按评测类型分类**：
```
bench/
├── multihop-rag/           # MultiHop-RAG 检索评测
│   ├── config/             # 配置文件
│   ├── data/               # 数据文件（软链或说明）
│   ├── scripts/            # 启动脚本（无参数或固定参数）
│   ├── reports/            # 测试报告
│   └── README.md           # 评测说明
├── hotpotqa/               # HotpotQA 多跳问答评测（未来迁移）
│   └── ...
└── README.md               # bench 总体说明
```

### 代码迁移

- 将 `mcs/bench/` 下的 Python 代码移动到 `bench/` 顶层（或保留在 `mcs/bench/` 作为库代码，启动脚本独立）
- **BREAKING**: 原 `python -m mcs.bench.multihop_rag` 调用方式废弃，改为独立脚本

### 启动脚本规范

每个脚本文件：
- 无需命令行参数，配置硬编码或从配置文件读取
- 文件名清晰表达用途，如 `run_baseline.sh`、`run_doc_rerank.sh`
- 输出目录、db 路径等固定在脚本中

### 旧文件清理

- 删除项目根目录散落的 `multihop_*.db`、`multihop_output_*` 等临时输出
- 归档已有报告到对应评测类型的 `reports/` 目录

## Capabilities

### New Capabilities

- `bench-directory-structure`: bench 目录结构规范，定义评测类型分类、文件组织、脚本命名规范

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

### 代码变更

- 新建 `bench/` 顶层目录
- 迁移 `mcs/bench/*.py` 到 `bench/multihop-rag/` 或保留为库代码
- 创建启动脚本 `bench/multihop-rag/scripts/`
- 创建配置目录 `bench/multihop-rag/config/`
- 创建报告目录 `bench/multihop-rag/reports/`

### 依赖更新

- `pyproject.toml`: 更新包结构（如需）
- 导入路径变更（如 `from mcs.bench import ...`）

### 文件清理

- 删除根目录 `multihop_*.db`、`_run_*.py`
- 移动 `multihop_output_*` 到 `bench/multihop-rag/reports/`

### 文档更新

- 更新 `CLAUDE.md` 中 bench 相关说明
- 创建各评测类型的 README