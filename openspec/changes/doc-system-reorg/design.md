## Context

MCS 项目完成 Phase 1 实施后，文档散落在多个位置：
- 根目录 4 个文档（README.md、MCS技术方案.md、测试方案.md、PENDING_FIXES.md）
- `openspec/specs/` 下 24 个 capability spec
- `bench/` 和 `mcs/bench/` 下评测文档
- 各模块 `__init__.py` 中的 docstring

**当前问题**：
1. 无统一入口，新人难以快速定位
2. 文档职责重叠（README 含架构细节、评测说明等）
3. 过期内容未清理（PENDING_FIXES.md 多数已修复）
4. 缺少架构总览和变更历史索引

**约束**：
- 不能破坏 OpenSpec 的工作流（归档 change 仍需要 `openspec/specs/` 下的 spec）
- 需保持向后兼容（现有链接不能断裂）
- 文档是给人读的，不是代码，不能过度工程化

## Goals / Non-Goals

**Goals:**

1. 建立清晰的文档层级规范（三层：入口层 → 概念层 → 规范层）
2. 创建 `docs/` 目录集中管理概念层文档
3. 提供统一的文档索引入口（`docs/INDEX.md`）
4. 清理过期文档和重复内容
5. 明确各文档的职责边界

**Non-Goals:**

1. 不改变 OpenSpec 的工作流和目录结构
2. 不重写技术方案或 spec 内容（仅迁移和组织）
3. 不创建自动化文档生成系统
4. 不处理 i18n/多语言

## Decisions

### D1: 三层文档体系

**决策**：采用 L1 入口层、L2 概念层、L3 规范层的三层结构。

**理由**：
- 符合认知规律：先定位（L1）→ 理解（L2）→ 约束（L3）
- 与代码层级对应：入口（README）→ 设计（docs）→ 契约（specs）
- 便于维护：每层职责清晰，避免混乱

**层级定义**：

| 层级 | 位置 | 职责 | 示例 |
|------|------|------|------|
| L1 入口 | 根目录 | 定位 + 快速开始 | README.md |
| L2 概念 | docs/ | 理解性文档（架构、流程、设计原理） | architecture.md, core-flows.md |
| L3 规范 | openspec/specs/ | 约束性文档（契约、接口、测试规范） | query-pipeline/spec.md |

### D2: docs/ 目录结构

**决策**：创建 `docs/` 目录，包含以下文件：

```
docs/
├── INDEX.md           # 文档总索引（主入口）
├── architecture.md    # 架构总览
├── core-flows.md      # 核心流程
├── testing-plan.md    # Phase 1 测试方案
├── known-issues.md    # 已知问题
└── CHANGELOG.md       # 变更历史索引
```

**理由**：
- 集中管理"理解性"文档，与"约束性"的 spec 分离
- `INDEX.md` 作为统一导航入口
- 保留历史（测试方案、变更历史）但不污染根目录

**替代方案**：
- 不创建 docs/，在根目录平铺 → 会导致根目录混乱，违背 D1
- 使用 `openspec/docs/` → 与 OpenSpec 工作流耦合过紧

### D3: README.md 精简策略

**决策**：README.md 精简为 4 个部分：
1. 项目定位（1 段话）
2. 核心赌注（保持不变）
3. 快速开始（安装 + 基本用法）
4. 文档导航（指向 `docs/INDEX.md`）

移出的内容：
- 架构详解 → `docs/architecture.md`
- 评测说明 → `bench/README.md`
- 详细依赖说明 → `docs/architecture.md`

**理由**：
- README 是"名片"，不是"说明书"
- 保持精简便于快速理解项目定位
- 详细内容通过索引导航

### D4: 文档去重策略

**决策**：采用"职责分离"原则处理重复文档：

| 重复对 | 策略 | 保留位置 |
|--------|------|----------|
| `mcs/bench/MULTIHOP_RAG.md` vs `bench/multihop_rag/README.md` | 合并为一份 | `bench/multihop_rag/README.md` |
| `mcs/bench/README.md` vs `bench/README.md` | 职责分离 | 前者 API 文档、后者入口文档 |
| `openspec/specs/architecture.md` vs `docs/architecture.md` | 迁移 + stub | `docs/architecture.md`（原位置留 stub） |

**理由**：
- `bench/` 是用户入口（启动脚本、配置）
- `mcs/bench/` 是库代码（API 用法）
- 分离后职责清晰，避免维护两份文档

### D5: 过期文档处理

**决策**：
1. `PENDING_FIXES.md` → `docs/known-issues.md`（仅保留未修复项）
2. 空 placeholder 文件 → 删除或补充最小内容
3. 归档 change 临时文件 → 删除（保留 proposal/design/tasks）

**理由**：
- 过期文档误导读者
- 保持"待修复"标题但多数已修复会降低可信度
- 清理后便于维护

## Risks / Trade-offs

### R1: 链接断裂风险

**风险**：现有文档中的链接可能指向移动后的位置。

**缓解**：
- 在原位置保留 stub 文件（如 `openspec/specs/architecture.md` → "已迁至 docs/architecture.md"）
- 使用相对路径而非绝对路径
- 变更后在 CI 中检查链接有效性（长期）

### R2: 维护成本增加

**风险**：新增 `docs/` 目录增加文档数量，可能增加维护负担。

**缓解**：
- `INDEX.md` 仅索引，不重复内容
- 明确文档职责边界，避免重复
- 定期清理过期文档（每个 change 归档时检查）

### R3: 与 OpenSpec 工作流冲突

**风险**：OpenSpec 归档时可能覆盖 `docs/` 下的文档。

**缓解**：
- `docs/` 与 `openspec/` 完全分离
- `openspec/specs/` 仅保留契约性 spec
- 不改变 OpenSpec 的目录结构和工作流

## Migration Plan

### 阶段一：创建 docs/ 目录和索引

1. 创建 `docs/INDEX.md`（文档总索引）
2. 创建 `docs/architecture.md`（从 `openspec/specs/architecture.md` 迁入并扩充）
3. 在原位置留 stub 文件

### 阶段二：规整根目录文档

1. 精简 `README.md`
2. 迁移 `测试方案.md` → `docs/testing-plan.md`
3. 清理 `PENDING_FIXES.md` → `docs/known-issues.md`

### 阶段三：规整评测文档

1. 合并 `mcs/bench/MULTIHOP_RAG.md` → `bench/multihop_rag/README.md`
2. 迁移 `mcs/bench/MULTIHOP_RERANK_REPORT.md` → `bench/multihop_rag/reports/`
3. 调整 `mcs/bench/README.md` 职责

### 阶段四：补充 spec Purpose

1. 检查所有 TBD spec
2. 补充 Purpose 描述
3. 创建 `openspec/specs/INDEX.md`

### 阶段五：清理过期文件

1. 删除空 placeholder
2. 删除归档 change 临时文件
3. 更新所有文档中的链接

## Open Questions

1. **CHANGELOG 格式**：采用 Keep a Changelog 格式还是简化版？
   - 建议：简化版，按 change 归档时间组织

2. **docs/ 是否需要子目录**：是否按类型（design/eval/spec）分目录？
   - 建议：不分，当前文档数量不多，扁平即可

3. **是否需要 docs/contributing.md**：贡献指南放在哪？
   - 建议：暂不创建，Phase 1 不需要贡献指南
