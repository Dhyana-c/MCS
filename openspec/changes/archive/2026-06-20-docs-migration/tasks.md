# 实现任务 — docs-migration

## ① 删除旧文档

- [x] 删除 `docs/core-flows.md`（被 graph-model-design.md §5 覆盖）
- [x] 删除 `docs/technical-design.md`（旧双模式模型，被 graph-model-design.md 取代）
- [x] 删除 `docs/memory-agent-design.md`（旧模型实验草案）

## ② 保留修改

- [x] `graph-model-design.md`：版本号 v0.1→v1.0，删"尚未实现"/"草稿"措辞

## ③ 重写

- [x] `architecture.md`：基于当前代码重写（系统定位、目录结构、模块职责、插件体系、数据流、扩展点）；删 relation_model / role / kind/label / property_graph / attribute_node 全部旧概念

## ④ 新建

- [x] `docs/getting-started.md`（L1）：5 分钟上手（安装→创建实例→ingest→query→持久化→MCP→Agent）
- [x] `docs/plugin-system.md`（L2）：14 类 PluginType + 接口签名 + 注册机制 + 生命周期 + 自定义插件开发指南（含示例）+ 内置插件清单
- [x] `docs/api-reference.md`（L2）：MCS 公开方法 + 数据类 + Builder + MCP 工具清单
- [x] `docs/memory-agent.md`（L3）：Agent 架构 + 5 导航工具 + learn_event + FastAPI 后端 + 前端 + 启动方式 + 与 MCP 区别
- [x] `docs/evaluation.md`（L3）：评测框架 + multihop-rag 指标 + extraction_quality + 运行方式

## ⑤ 更新现有文档

- [x] `docs/configuration.md`：删 relation_model 示例 + 删 provenance 拒绝节 + 更新字段叠加表（删 attribute_content_max）
- [x] `docs/mcp-server.md`：加 `ingest_event` 工具（更正：`ingest_source` / `run_maintenance` 未注册为 MCP 工具，仅 MCS 门面方法——已在文档注明）
- [x] `docs/faq.md`：不变量表述对齐 + 边语义对齐（关联/互斥）+ 返回类型更正为 Subgraph + 修复断链

## ⑥ 索引

- [x] `docs/INDEX.md`：重写索引，反映上述全部变更（删归档条目、加新文档、更新描述）

## ⑦ spec 同步与验收

- [x] 确认 `specs/doc-hierarchy/spec.md` delta 与实际文档动作一致（删/改/增逐条对应）
- [x] 修复因删文件产生的断链：`README.md`、`CONTRIBUTING.md`、`graph-model-design.md`
- [x] 全部文档落地后逐条核对 delta 的 scenario（术语零残留、必需文件清单、工具表一致、PluginType 枚举一致等）
- [x] `openspec validate docs-migration --strict` 通过

## 遗留（不在本 change）

- [ ] `openspec/specs/project-skeleton/spec.md` 同样要求 `core-flows.md` / `technical-design.md` 存在、README 引用 `technical-design.md`；且其 `plugins/phase1|phase2` 目录约定已与现码不符——需独立的 skeleton 刷新 change 处理。
- [ ] 根目录 `README_v2.md`（草稿）仍含指向已删文件的链接——待定其去留。
