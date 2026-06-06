## Context

### 当前状态

```
mcs/bench/
├── __init__.py
├── hotpot.py              # HotpotQA 评测代码
├── multihop_rag.py        # MultiHop-RAG 评测代码
├── doc_rerank.py          # 文档级重排辅助
├── README.md              # HotpotQA 说明
├── MULTIHOP_RAG.md        # MultiHop-RAG 说明
└── MULTIHOP_RERANK_REPORT.md  # 重排实验报告
```

项目根目录散落：
- `_run_multihop_chat_200_whole.py` — 临时启动脚本
- `multihop_*.db` — 评测数据库
- `multihop_output_*` — 输出目录

### 约束

1. 评测代码作为 `mcs.bench` 模块，可被外部导入使用
2. 启动脚本应独立于库代码，便于配置和运行
3. 输出文件不应污染项目根目录

## Goals / Non-Goals

**Goals:**
1. 建立清晰的 bench 目录结构，按评测类型分类
2. 统一启动脚本规范，每个脚本可独立运行
3. 输出文件集中管理，便于追踪和清理
4. 保留评测代码作为可导入模块的能力

**Non-Goals:**
1. 不改变评测代码的核心逻辑
2. 不改变评测指标的计算方式
3. 不引入新的评测类型（仅重组现有）

## Decisions

### D1: Bench 代码保留在 `mcs/bench/`

**理由**：
- 评测代码作为库的一部分，可被外部项目导入使用
- 与 `mcs/core/` 等核心模块保持一致的包结构
- 避免循环依赖

**替代方案**：
- 移到顶层 `bench/` → 破坏 `from mcs.bench import ...` 导入路径

### D2: 启动脚本独立于库代码

**理由**：
- 启动脚本包含具体配置（db 路径、输出目录），不应混入库代码
- 便于不同实验配置的脚本并存

**目录结构**：
```
bench/                           # 顶层 bench 目录
├── multihop-rag/                # MultiHop-RAG 评测
│   ├── config/                  # 配置文件（可选）
│   │   └── default.json
│   ├── scripts/                 # 启动脚本
│   │   ├── run_baseline.py      # 基线评测
│   │   ├── run_node_rerank.py   # 节点级重排
│   │   └── run_doc_rerank.py    # 文档级重排
│   ├── reports/                 # 测试报告
│   │   └── *.md
│   └── README.md                # 评测说明
├── hotpotqa/                    # HotpotQA 评测（占位）
│   └── README.md
└── README.md                    # bench 总体说明
```

### D3: 启动脚本无命令行参数

**理由**：
- 配置硬编码在脚本中，避免参数传递错误
- 不同配置用不同脚本文件区分
- 便于复现实验

**脚本模板**：
```python
"""评测脚本：<描述>"""

import sys
from pathlib import Path

# 配置（硬编码）
DB_PATH = Path(__file__).parent.parent / "data" / "multihop.db"
OUTPUT_DIR = Path(__file__).parent.parent / "outputs" / "baseline"
CORPUS_SUBSET = 200

def main():
    from mcs.bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

    config = MultiHopEvalConfig(
        db_path=str(DB_PATH),
        output_dir=str(OUTPUT_DIR),
        corpus_subset=CORPUS_SUBSET,
        # ...
    )
    runner = MultiHopEvalRunner(config)
    metrics = runner.run()
    print(metrics)

if __name__ == "__main__":
    main()
```

### D4: 输出目录结构

```
bench/multihop-rag/
├── data/                        # 数据文件（软链或说明）
│   └── README.md                # 数据下载说明
├── outputs/                     # 输出目录（gitignore）
│   ├── baseline/
│   ├── node_rerank/
│   └── doc_rerank/
└── reports/                     # 报告（提交到 git）
    └── *.md
```

## Risks / Trade-offs

### Risk 1: 导入路径变更

**风险**：现有代码可能直接运行 `python -m mcs.bench.multihop_rag`

**缓解**：
- 保留 `mcs/bench/` 作为库代码
- 启动脚本通过 `from mcs.bench import ...` 调用
- 更新文档说明新的运行方式

### Risk 2: 历史输出文件丢失

**风险**：移动输出文件可能丢失历史实验结果

**缓解**：
- 先归档到 `reports/` 目录
- 确认后再删除根目录散落的文件

### Trade-off: 脚本数量增加

**代价**：每个实验配置需要一个脚本文件

**收益**：
- 配置清晰、可复现
- 避免参数传递错误
- 便于版本控制