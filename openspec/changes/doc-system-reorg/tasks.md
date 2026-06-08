## 1. 创建 docs/ 目录和索引

- [ ] 1.1 创建 `docs/INDEX.md`（文档总索引），包含 L1/L2/L3 三层文档导航
- [ ] 1.2 创建 `docs/architecture.md`，从 `openspec/specs/architecture.md` 迁入内容并扩充为理解性文档
- [ ] 1.3 在 `openspec/specs/architecture.md` 原位置创建 stub 文件，指向新位置
- [ ] 1.4 创建 `docs/core-flows.md`，包含读写管线和图演化的完整说明
- [ ] 1.5 创建 `docs/CHANGELOG.md`，按时间倒序索引所有归档 change

## 2. 规整根目录文档

- [ ] 2.1 精简 `README.md`：移出架构详解、评测详解，保留定位/快速开始/文档导航
- [ ] 2.2 迁移 `测试方案.md` → `docs/testing-plan.md`，在原位置创建 stub
- [ ] 2.3 清理 `PENDING_FIXES.md`：移除已修复项，仅保留未修复项 → `docs/known-issues.md`
- [ ] 2.4 删除根目录的 `MCS技术方案.md`（内容已在 docs/architecture.md 和 specs 中）

## 3. 规整评测文档

- [ ] 3.1 合并 `mcs/bench/MULTIHOP_RAG.md` 内容到 `bench/multihop-rag/README.md`
- [ ] 3.2 迁移 `mcs/bench/MULTIHOP_RERANK_REPORT.md` → `bench/multihop-rag/reports/doc_rerank_experiment.md`
- [ ] 3.3 调整 `mcs/bench/README.md`：移除重复内容，保留 API 文档职责
- [ ] 3.4 精简 `bench/README.md`：保留入口文档职责，详细说明下沉到各评测类型 README

## 4. 补充 spec Purpose

- [ ] 4.1 检查 `openspec/specs/` 下所有 spec 的 Purpose 字段
- [ ] 4.2 补充 TBD spec 的 Purpose（`project-skeleton`、`phase1-defaults` 等）
- [ ] 4.3 创建 `openspec/specs/INDEX.md`，按能力域分组索引所有 spec

## 5. 清理过期文件

- [ ] 5.1 删除空/placeholder 文件（`mcs/utils/__init__.py`、`mcs/diagnostics/__init__.py` 等空文件）
- [ ] 5.2 删除归档 change 目录中的临时文件（调试产物、中间结果）
- [ ] 5.3 更新所有文档中的断裂链接

## 6. 验证

- [ ] 6.1 验证 `docs/INDEX.md` 链接完整性
- [ ] 6.2 验证 README.md 精简后仍能引导用户快速开始
- [ ] 6.3 验证无断裂链接（grep 检查所有 `[...](...)` 格式链接）
- [ ] 6.4 更新 CLAUDE.md 中的文档引用（如有）
