## 1. 创建 docs/ 目录和索引

- [x] 1.1 创建 `docs/INDEX.md`（文档总索引），包含 L1/L2/L3 三层文档导航
- [x] 1.2 创建 `docs/architecture.md`，从 `openspec/specs/architecture.md` 迁入内容并扩充为理解性文档
- [x] 1.3 在 `openspec/specs/architecture.md` 原位置创建 stub 文件，指向新位置
- [x] 1.4 创建 `docs/core-flows.md`，包含读写管线和图演化的说明骨架
- [x] 1.5 创建 `docs/faq.md`，包含常见问题骨架

## 2. 规整根目录文档

- [x] 2.1 重构 `README.md`：按 D3 结构精简（定位 + 核心赌注 + 快速开始 + 文档 + 评测 + 贡献 + 许可证）
- [x] 2.2 迁移 `MCS技术方案.md` → `docs/technical-design.md`，删除原文件
- [x] 2.3 清理 `PENDING_FIXES.md`：移除已修复项，仅保留未修复项 → `docs/known-issues.md`，删除原文件
- [x] 2.4 删除 `测试方案.md`

## 3. 增加开源文档

- [x] 3.1 创建 `LICENSE`（MIT 协议）
- [x] 3.2 创建 `CONTRIBUTING.md`，包含环境搭建、开发流程、提交规范骨架
- [x] 3.3创建 `CHANGELOG.md`，按时间倒序索引所有归档 change

## 4. 补充 spec 和 bench

- [x] 4.1 检查 `openspec/specs/` 下所有 spec 的 Purpose 字段
- [x] 4.2 补充 TBD spec 的 Purpose（`project-skeleton`、`phase1-defaults` 等）
- [x] 4.3 创建 `openspec/specs/INDEX.md`，按能力域分组索引所有 spec
- [x] 4.4 精简 `bench/README.md`：保留入口文档职责，评测详情下沉到各评测类型 README

## 5. 清理和验证

- [x] 5.1 删除空/placeholder 文件（补充 mcs/diagnostics/__init__.py 和 mcs/utils/__init__.py 导出）
- [x] 5.2 删除归档 change 目录中的临时文件（已无临时文件）
- [x] 5.3 更新所有文档中的断裂链接
- [x] 5.4 更新 CLAUDE.md 中的文档引用（无需更新）

## 6. 验证

- [x] 6.1 验证 `docs/INDEX.md` 链接完整性
- [x] 6.2 验证 README.md 精简后仍能引导用户快速开始
- [x] 6.3 验证无断裂链接
- [x] 6.4 验证 LICENSE、CONTRIBUTING.md、CHANGELOG.md 存在且结构合理
