## Why

MCS 项目文档体系目前存在以下问题：

1. **文档散乱、定位困难**：根目录有 `README.md`、`MCS技术方案.md`、`测试方案.md`、`PENDING_FIXES.md` 等；`openspec/specs/` 有 24 个 capability spec；`bench/` 和 `mcs/bench/` 各有 README；`mcs/__init__.py` 等模块也有文档字符串——**缺乏统一的索引入口**，新人难快速定位。

2. **文档职责重叠、边界不清**：
   - `README.md` 包含架构、快速开始、评测说明等（混合定位/用法/评测）
   - `MCS技术方案.md` 与多个 `openspec/specs/` spec 内容重叠（如 `subgraph-bounding`、`query-pipeline`）
   - `mcs/bench/README.md` 与 `bench/multihop_rag/README.md` 内容高度重复

3. **过期文档未清理**：`PENDING_FIXES.md` 中大部分问题已修复但仍保留"待修复"标题；部分 spec 的 Purpose 为 TBD（如 `project-skeleton/spec.md`）；归档的 change 目录未被清理索引。

4. **关键文档缺失**：缺少统一的"架构总览"文档（`architecture.md` 只索引 spec、不解释架构）；缺少"变更历史"索引；评测报告散落各处无统一入口。

现在规整，因为 Phase 1 已完成、评测框架已稳定，是确立文档体系的最佳时机。

## What Changes

### 1. 建立文档层级规范

定义三层文档体系：
- **L1 入口层**：`README.md`（定位 + 快速开始）、`docs/INDEX.md`（文档总索引）
- **L2 概念层**：架构、核心流程、设计原理等"理解性"文档
- **L3 规范层**：capability spec、接口契约、测试规范等"约束性"文档

### 2. 规整根目录文档

- `README.md`：精简为"定位 + 快速开始 + 导航入口"，移出架构细节和评测说明
- `MCS技术方案.md`：保留为核心设计文档，明确与 spec 的边界（方案解释原理、spec 定义契约）
- `测试方案.md`：移入 `docs/testing-plan.md`（Phase 1 测试方案，归档性质）
- `PENDING_FIXES.md`：清理已修复项，改为 `docs/known-issues.md`（仅保留未修复项）

### 3. 建立 docs/ 目录结构

创建 `docs/` 目录集中管理 L2 概念层文档：
```
docs/
├── INDEX.md           # 文档总索引（导航入口）
├── architecture.md    # 架构总览（从 openspec/specs/architecture.md 迁入并扩充）
├── core-flows.md      # 核心流程（读写管线、图演化）
├── testing-plan.md    # 测试方案（从根目录迁入）
├── known-issues.md    # 已知问题（从 PENDING_FIXES.md 清理）
└── CHANGELOG.md       # 变更历史索引（归档 change 概览）
```

### 4. 规整 openspec/specs/

- `architecture.md`：迁入 `docs/architecture.md`，原位置改为指向新位置的 stub
- 补充 TBD spec 的 Purpose（`project-skeleton`、`phase1-defaults` 等）
- 创建 `openspec/specs/INDEX.md`（spec 导航入口，按能力域分组）

### 5. 规整 bench 文档

- `bench/README.md`：保留为评测入口，精简为"目录结构 + 评测类型导航"
- `mcs/bench/README.md`：改为指向 `bench/README.md` + API 用法（职责分离）
- `mcs/bench/MULTIHOP_RAG.md`：与 `bench/multihop_rag/README.md` 合并（去重）
- `mcs/bench/MULTIHOP_RERANK_REPORT.md`：迁入 `bench/multihop_rag/reports/`（报告集中）

### 6. 删除过期文档

- 合并后的重复文档
- 空/placeholder 文件（如 `mcs/utils/__init__.py`、`mcs/diagnostics/__init__.py`）
- 归档 change 目录中的临时文件（保留 proposal/design/tasks，删除调试产物）

## Capabilities

### New Capabilities

- `doc-hierarchy`: 文档层级规范与索引体系（三层划分、docs/ 目录结构、导航入口）

### Modified Capabilities

- `project-skeleton`: 补充 docs/ 目录结构要求（新增 `docs/INDEX.md` 存在性检查）
- `bench-directory-structure`: 明确评测文档职责边界（`bench/README.md` 为入口、`mcs/bench/` 为 API 文档）

## Impact

- **新目录**：`docs/` 目录及其下 6 个文档文件
- **修改文件**：`README.md`（精简）、`mcs/bench/README.md`（职责调整）、多个 spec（补充 Purpose）
- **删除文件**：合并后的重复文档、过期 placeholder
- **用户体验**：新人可通过 `docs/INDEX.md` 快速定位所需文档，开发者可明确文档职责边界