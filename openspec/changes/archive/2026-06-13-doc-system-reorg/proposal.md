## Why

MCS 项目文档体系目前存在以下问题：

1. **文档散乱、定位困难**：根目录有 `README.md`、`MCS技术方案.md`、`PENDING_FIXES.md` 等；`openspec/specs/` 有 27 个 capability spec；`bench/` 有 README——**缺乏统一的索引入口**，新人难快速定位。

2. **文档职责重叠、边界不清**：
   - `README.md` 包含架构详解、快速开始、评测说明等（混合定位/用法/评测，20KB 过重）
   - `MCS技术方案.md` 与多个 `openspec/specs/` spec 内容重叠（如 `subgraph-bounding`、`query-pipeline`）

3. **过期文档未清理**：`PENDING_FIXES.md` 中大部分问题已修复但仍保留"待修复"标题；`测试方案.md` 内容已过时（Phase 1 测试方案，部分与实际实现不一致）；部分 spec 的 Purpose 为 TBD（如 `project-skeleton/spec.md`）。

4. **关键文档缺失**：缺少统一的"架构总览"文档（`architecture.md` 只索引 spec、不解释架构）；缺少"变更历史"索引；**缺少开源项目必备文档**（LICENSE、CONTRIBUTING.md）。

5. **README 不符合开源项目惯例**：当前 README 20KB，混合了架构详解、评测说明、开发状态等，不符合"名片+导航"的定位；面向中文社区开源，需要更清晰的结构。

现在规整，因为项目准备开源，是确立文档体系的最佳时机。

## What Changes

### 1. 建立文档层级规范

定义三层文档体系：
- **L1 入口层**：`README.md`（定位 + 快速开始）、`docs/INDEX.md`（文档总索引）
- **L2 概念层**：架构、核心流程、设计原理等"理解性"文档
- **L3 规范层**：capability spec、接口契约等"约束性"文档

### 2. 规整根目录文档

- `README.md`：精简为"定位 + 快速开始 + 导航入口"，移出架构细节和评测说明
- `MCS技术方案.md`：迁入 `docs/technical-design.md`（保留完整内容，原位置留 stub）
- `测试方案.md`：**直接删除**（内容已过时，与实际实现不一致）
- `PENDING_FIXES.md`：清理已修复项，改为 `docs/known-issues.md`（仅保留未修复项）

### 3. 建立 docs/ 目录结构

创建 `docs/` 目录集中管理 L2 概念层文档：
```
docs/
├── INDEX.md              # 文档总索引（导航入口）
├── architecture.md       # 架构总览（从 openspec/specs/architecture.md 迁入并扩充）
├── core-flows.md         # 核心流程（读写管线、图演化）
├── technical-design.md   # 技术方案（从根目录 MCS技术方案.md 迁入）
├── known-issues.md       # 已知问题（从 PENDING_FIXES.md 清理）
└── faq.md                # 常见问题
```

### 4. 增加开源必备文档

- `LICENSE`：开源许可证（根目录）
- `CONTRIBUTING.md`：贡献指南（根目录）
- `CHANGELOG.md`：变更历史索引（根目录，社区惯例位置）

### 5. 规整 README.md 结构

面向中文社区开源项目，README 精简为以下结构：

```
# MCS - Maximum-Context Subgraph
  一句话定位

## 核心赌注
  核心假设（保持不变）

## 快速开始
  安装 → 基本用法 → 切换后端（Claude/Ollama）

## 文档
  导航入口 → docs/INDEX.md

## 评测
  简要说明 + 指向 bench/README.md

## 贡献
  指向 CONTRIBUTING.md

## 许可证
  指向 LICENSE
```

移出的内容：
- 架构详解（双层结构、边类型、不变量等）→ `docs/architecture.md`
- 读写工作流图 → `docs/core-flows.md`
- 项目结构树 → `docs/architecture.md`
- 模式与配置表 → `docs/architecture.md`
- 评测详解（CLI 参数、实测要点等）→ `bench/README.md`
- 开发状态 → `docs/architecture.md`
- 依赖列表 → `docs/architecture.md`

### 6. 规整 openspec/specs/

- `architecture.md`：迁入 `docs/architecture.md`，原位置改为指向新位置的 stub
- 补充 TBD spec 的 Purpose（`project-skeleton`、`phase1-defaults` 等）
- 创建 `openspec/specs/INDEX.md`（spec 导航入口，按能力域分组）

### 7. 规整 bench 文档

- `bench/README.md`：保留为评测入口，精简为"目录结构 + 评测类型导航"
- 评测报告已在 `bench/multihop_rag/reports/`，无需迁移

### 8. 删除过期文档

- `测试方案.md`（直接删除）
- 合并后的重复文档
- 归档 change 目录中的临时文件（保留 proposal/design/tasks，删除调试产物）

## Capabilities

### New Capabilities

- `doc-hierarchy`: 文档层级规范与索引体系（三层划分、docs/ 目录结构、导航入口、README 结构规范）

### Modified Capabilities

- `project-skeleton`: 补充 docs/ 目录结构要求 + 根目录开源文档要求（LICENSE、CONTRIBUTING.md、CHANGELOG.md 存在性检查）
- `bench-directory-structure`: 明确评测文档职责（`bench/README.md` 为入口）

## Impact

- **新目录**：`docs/` 目录及其下 6 个文档文件
- **新文件**：`LICENSE`、`CONTRIBUTING.md`、`CHANGELOG.md`（根目录）
- **修改文件**：`README.md`（精简重构）、多个 spec（补充 Purpose）
- **删除文件**：`测试方案.md`、合并后的重复文档、过期 placeholder
- **迁移文件**：`MCS技术方案.md` → `docs/technical-design.md`、`PENDING_FIXES.md` → `docs/known-issues.md`
- **用户体验**：新人可通过 `docs/INDEX.md` 快速定位所需文档，README 作为名片快速理解项目定位
