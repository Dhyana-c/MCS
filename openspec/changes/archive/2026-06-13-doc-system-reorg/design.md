## Context

MCS 项目准备开源，文档散落在多个位置：
- 根目录 3 个文档（README.md、MCS技术方案.md、PENDING_FIXES.md）
- `openspec/specs/` 下 27 个 capability spec
- `bench/` 下评测文档
- 各模块 `__init__.py` 中的 docstring

**当前问题**：
1. 无统一入口，新人难以快速定位
2. README 20KB 过重，混合架构/评测/开发状态（不像开源项目"名片"）
3. 文档职责重叠（README 含架构细节、评测说明等）
4. 过期内容未清理（PENDING_FIXES.md 多数已修复、测试方案.md 已过时）
5. 缺少架构总览和变更历史索引
6. 缺少开源必备文档（LICENSE、CONTRIBUTING.md、CHANGELOG.md）

**约束**：
- 不能破坏 OpenSpec 的工作流（归档 change 仍需要 `openspec/specs/` 下的 spec）
- 需保持向后兼容（现有链接不能断裂）
- 文档是给人读的，不是代码，不能过度工程化
- 面向中文社区开源，README 以中文为主
- 文档现在定结构/骨架，内容后续基于代码填充

## Goals / Non-Goals

**Goals:**

1. 建立清晰的文档层级规范（三层：入口层 → 概念层 → 规范层）
2. 创建 `docs/` 目录集中管理概念层文档
3. 提供统一的文档索引入口（`docs/INDEX.md`）
4. 清理过期文档和重复内容
5. 明确各文档的职责边界
6. 规划 README 结构，符合中文社区开源项目惯例
7. 补充开源必备文档（LICENSE、CONTRIBUTING.md、CHANGELOG.md）

**Non-Goals:**

1. 不改变 OpenSpec 的工作流和目录结构
2. 不重写技术方案或 spec 内容（仅迁移和组织）
3. 不创建自动化文档生成系统
4. 不处理 i18n/多语言（中文为主）

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
| L1 入口 | 根目录 | 定位 + 快速开始 + 开源标配 | README.md, CONTRIBUTING.md, CHANGELOG.md |
| L2 概念 | docs/ | 理解性文档（架构、流程、设计原理） | architecture.md, core-flows.md |
| L3 规范 | openspec/specs/ | 约束性文档（契约、接口、测试规范） | query-pipeline/spec.md |

### D2: docs/ 目录结构

**决策**：创建 `docs/` 目录，包含以下文件：

```
docs/
├── INDEX.md              # 文档总索引（主入口）
├── architecture.md       # 架构总览
├── core-flows.md         # 核心流程
├── technical-design.md   # 技术方案（从 MCS技术方案.md 迁入）
├── known-issues.md       # 已知问题
└── faq.md                # 常见问题
```

**理由**：
- 集中管理"理解性"文档，与"约束性"的 spec 分离
- `INDEX.md` 作为统一导航入口
- `technical-design.md` 保留完整技术方案（从根目录迁入，不删不缩）
- `faq.md` 对开源项目很实用（降低重复提问成本）

**替代方案**：
- 不创建 docs/，在根目录平铺 → 会导致根目录混乱，违背 D1
- 使用 `openspec/docs/` → 与 OpenSpec 工作流耦合过紧

### D3: README.md 结构规划

**决策**：README.md 精简为以下结构，符合中文社区开源项目惯例：

```markdown
# MCS - Maximum-Context Subgraph
  一句话定位（与现有保持一致）

## 核心赌注
  核心假设（保持不变）

## 快速开始
  安装 → 基本用法 → 切换后端（Claude/Ollama）

## 文档
  导航入口 → docs/INDEX.md

## 评测
  一段话简述 + 指向 bench/README.md

## 贡献
  指向 CONTRIBUTING.md

## 许可证
  指向 LICENSE
```

**移出的内容**：
- 架构详解（双层结构、边类型、不变量等）→ `docs/architecture.md`
- 读写工作流图 → `docs/core-flows.md`
- 项目结构树 → `docs/architecture.md`
- 模式与配置表 → `docs/architecture.md`
- 评测详解（CLI 参数、实测要点等）→ `bench/README.md`
- 开发状态 → `docs/architecture.md`
- 依赖列表 → `docs/architecture.md`

**理由**：
- README 是"名片"，不是"说明书"——中文社区开源项目（如 LangChain-Chatchat、MaxKB、Dify）的 README 都控制在"定位+快速开始+导航"范围内
- 架构/评测/开发状态等详细信息通过索引导航
- 保持精简便于快速理解项目定位

### D4: 文档去重策略

**决策**：采用"职责分离"原则处理重复文档：

| 重复对 | 策略 | 保留位置 |
|--------|------|----------|
| `openspec/specs/architecture.md` vs `docs/architecture.md` | 迁移 + stub | `docs/architecture.md`（原位置留 stub） |
| `MCS技术方案.md` vs `docs/technical-design.md` | 迁移 + 删除原文 | `docs/technical-design.md`（原文件删除） |

**理由**：
- `docs/architecture.md` 是理解性文档（解释"为什么"和"怎么理解"）
- `openspec/specs/architecture.md` 是索引性文档（指向各 spec）
- `MCS技术方案.md` 迁入 docs/ 后仍是完整技术方案，只是位置更合理

### D5: 过期文档处理

**决策**：
1. `测试方案.md` → **直接删除**（内容已过时，与实际实现不一致）
2. `PENDING_FIXES.md` → `docs/known-issues.md`（仅保留未修复项）
3. 归档 change 临时文件 → 删除（保留 proposal/design/tasks）

**理由**：
- `测试方案.md` 描述的是早期设计，部分与 Phase 1 实际实现不一致，保留会误导
- 过期文档误导读者，保持"待修复"标题但多数已修复会降低可信度

### D6: 开源必备文档

**决策**：在根目录增加以下开源项目标配文件：

| 文件 | 位置 | 内容 |
|------|------|------|
| `LICENSE` | 根目录 | 开源许可证（待定具体协议） |
| `CONTRIBUTING.md` | 根目录 | 贡献指南（环境搭建、开发流程、提交规范） |
| `CHANGELOG.md` | 根目录 | 变更历史索引（按时间倒序，社区惯例位置） |

**理由**：
- 中文社区开源项目（Dify、MaxKB、RAGFlow 等）均在根目录放置这三份文件
- `CHANGELOG.md` 放根目录是 GitHub Release 页面自动识别的位置
- `CONTRIBUTING.md` 放根目录是 GitHub 在 PR 页面自动提示的位置

## Risks / Trade-offs

### R1: 链接断裂风险

**风险**：现有文档中的链接可能指向移动后的位置。

**缓解**：
- 在原位置保留 stub 文件（如 `openspec/specs/architecture.md` → "已迁至 docs/architecture.md"）
- 使用相对路径而非绝对路径
- 变更后检查链接有效性

### R2: 维护成本增加

**风险**：新增 `docs/` 目录增加文档数量，可能增加维护负担。

**缓解**：
- `INDEX.md` 仅索引，不重复内容
- 明确文档职责边界，避免重复
- 文档骨架先行，内容基于代码填充

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

1. 重构 `README.md`（按 D3 结构精简）
2. 迁移 `MCS技术方案.md` → `docs/technical-design.md`
3. 清理 `PENDING_FIXES.md` → `docs/known-issues.md`
4. 删除 `测试方案.md`

### 阶段三：增加开源文档

1. 创建 `LICENSE`
2. 创建 `CONTRIBUTING.md`
3. 创建 `CHANGELOG.md`

### 阶段四：补充 spec 和 bench

1. 补充 TBD spec 的 Purpose
2. 创建 `openspec/specs/INDEX.md`
3. 精简 `bench/README.md`

### 阶段五：清理和验证

1. 删除空 placeholder
2. 删除归档 change 临时文件
3. 更新所有文档中的链接
4. 验证链接完整性

## Open Questions

1. **LICENSE 具体协议**：MIT / Apache 2.0 / 其他？
   - 建议：MIT（简洁宽松，中文社区常用）

2. **docs/ 是否需要子目录**：是否按类型分目录？
   - 建议：不分，当前文档数量不多，扁平即可

3. **README 是否需要英文版**：是否提供 `README_EN.md`？
   - 建议：暂不提供，中文社区开源项目以中文为主即可
