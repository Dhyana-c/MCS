# 实现任务 — spec-hygiene

## ① 主 spec 格式修正（直接改主 spec）

- [x] 6 个单 delta 头 spec：`## ADDED Requirements` → `## Requirements`
  （bench-doc-rerank / bench-doc-rerank-plugin / multihop-rag-eval / ollama-llm-adapter / plugin-directory-by-type / unified-graph-schema）
- [x] `auto-persistence`：头改名 + 删除 `## MODIFIED Requirements` 整段（stale 错置，write-pipeline 已有正本）

## ② project-skeleton 内容刷新（delta）

- [x] MODIFIED 项目目录结构（docs 清单 + mcs 子目录 + plugins 按类型）
- [x] MODIFIED 接口层完整性（当前接口文件、删 pipeline_hook/query_hook）
- [x] MODIFIED 核心引擎骨架（MCS 瘦门面方法、删 initialize/persist_full）
- [x] MODIFIED Git 与 README 集成（删 technical-design 引用）
- [x] REMOVED Phase 1 插件占位 / Phase 2 插件预留
- [x] ADDED 插件按 PluginType 组织

## ③ 草稿清理

- [x] 删除 README_v2.md

## ④ 验收

- [x] `openspec validate spec-hygiene --strict` 通过
- [x] `openspec archive spec-hygiene --yes`（同步 project-skeleton delta）
