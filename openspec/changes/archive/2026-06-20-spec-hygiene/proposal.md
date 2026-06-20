# Proposal: spec-hygiene——迁移后 spec 与草稿清理

## Why

`unified-graph-schema` / `unified-ingest` / `docs-migration` 三次变更已归档合并，但留下一批"未跟上"的 spec / 草稿：

1. **7 个主 spec 用非法 delta 头**（`## ADDED/MODIFIED Requirements`）——它们的 requirement 对 validate / list / archive 全部"不可见"，是早期同步写坏的产物。
2. **`project-skeleton` 主 spec 内容大面积过时**——仍要求已删的 `core-flows.md` / `technical-design.md` 存在、约定已不存在的 `plugins/phase1|phase2/` 目录、MCS 方法 `initialize` / `persist_full`（现已移除）、接口层仍是旧的 8 文件清单（含已废弃 `pipeline_hook.py` / `query_hook.py`）。
3. **`README_v2.md`** 是过时草稿（旧双关系模型 `property_graph` / `attribute_node`、指向已删文件的链接、错误插件数 12 vs 14），现 `README.md` 已是 canonical。

开源前需把 spec / 草稿对齐到当前代码。

## What Changes

### 1. 主 spec 格式修正（7 个，纯格式 + auto-persistence 清理）

- 6 个单 delta 头 spec：`## ADDED Requirements` → `## Requirements`
  （`bench-doc-rerank` / `bench-doc-rerank-plugin` / `multihop-rag-eval` / `ollama-llm-adapter` / `plugin-directory-by-type` / `unified-graph-schema`）
- `auto-persistence`：头改名 + **删除错置的 `## MODIFIED Requirements` 整段**（2 条 "写流程 6 段" / "WriteContext 七字段" 是 write-pipeline 的修改，write-pipeline 主 spec 已有 7 段 / 8 字段正本，删除无信息损失）

### 2. project-skeleton 内容刷新（真需求变更，走 delta）

- **MODIFIED**：项目目录结构（docs 清单 + mcs 子目录 + plugins 按类型）、接口层完整性（当前接口文件）、核心引擎骨架（MCS 瘦门面方法）、Git 与 README 集成（删 technical-design 引用）
- **REMOVED**：Phase 1 插件占位、Phase 2 插件预留（phase 目录已不存在）
- **ADDED**：插件按 PluginType 组织

### 3. README_v2.md 删除

过时草稿，删除。

## 不在范围

- 接口层 / 核心引擎骨架的更深度审计（本次只修正已核实与现码矛盾的需求）
- 其他主 spec 的内容审计

## 影响评估

纯 spec / 文档清理，零代码变更，零回归风险。
