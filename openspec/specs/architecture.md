---
name: mcs-architecture
description: MCS 架构索引 - 指向各 capability spec 和底层设计文档
metadata:
  type: architecture-index
  version: 3.0
  phase: 1
---

# MCS 架构索引

MCS（Maximum-Context Subgraph）是**可扩展的记忆系统**。本文档不重复 capability 契约，仅作导航。

## 定位

MCS 是图结构的"基于语义的记忆检索 + 写入"引擎。MCS 类是瘦门面——只暴露双管线（writer/reader）和定向插件管理，所有组装工作由 Builder 一次 `build()` 完成。它不预设上层用法：

- **写入**：把原始文本组织成由概念节点 + 无类型邻接边构成的图
- **读取**：基于 query 返回与之语义相关的节点集合（`List[Node]`），由调用方决定后续如何使用

调用方（RAG / Agent / Chatbot）拿到 MCS 返回的记忆节点后，可以自行：合成自然语言答案、做多轮对话、追问加深、写回新事实。MCS **不**做这些——它专注于记忆本身。

## 架构契约（按 capability 拆分）

每个 capability 在 `openspec/specs/<name>/spec.md` 下以 SHALL/MUST 形式定义契约：

| Capability | 关注 |
|------------|------|
| [`store-interface`](store-interface/spec.md) | 统一存储接口（StoreInterface ABC + InMemoryStore + SQLiteStore），消费者依赖接口而非实现 |
| [`query-pipeline`](query-pipeline/spec.md) | 读流程 5 段管线（前置 → 种子定位 → 语义 Loop → 仲裁 → 后置），BFS 遍历的硬约束（visited / max_rounds / max_picked），默认返回 `List[Node]` 的契约 |
| [`write-pipeline`](write-pipeline/spec.md) | 写流程 7 段管线（前置 → 关联定位 → 提取 → 判定 → 应用 → 压缩 → 自动落盘），写复用读的对称性，决策清单与图更新的分离契约 |
| [`mcs-builder`](mcs-builder/spec.md) | MCS 实例构建契约：Builder 全量组装、MCS 瘦门面、双 PluginManager 架构、插件注册/注销 API |
| [`plugin-protocol`](plugin-protocol/spec.md) | 5 类插件接口（Entry / Trim / Arbitration / Postprocess / Compaction），插件链的优先级 / 累积 / 短路语义，定向注册/注销 API |
| [`llm-interaction`](llm-interaction/spec.md) | LLM 调用统一模式（`purpose` + `nodes_in` + `free_args`），`ContextRenderer` 的渲染契约，`system_prompt` / `user_template` / `parser` 的覆盖机制 |
| [`project-skeleton`](project-skeleton/spec.md) | Python 包目录结构、ABC 接口完整性、包管理与测试框架约束 |
| [`hotpot-eval`](hotpot-eval/spec.md) | HotpotQA 多跳问答评测框架：数据加载、ingest 适配、query 适配、评测运行器、评测配置 |

## 底层设计与背景

- [MCS技术方案.md](../../MCS技术方案.md) — 完整的机制设计文档（双层结构、无类型边、版本化、社区合并、激活扩散等）
- [测试方案.md](../../测试方案.md) — 分阶段验证测试计划
- [README.md](../../README.md) — 项目简介与快速开始

## 工作流总图

```
读 (RECALL)                            写 (INGEST)
─────────────────────────              ─────────────────────────
input: query, [ctx]                    input: text

① 前置插件链 (可选)                    ① 前置插件链 (可选)
        │                                       │
        ▼                                       ▼
② 种子定位                              ② 关联节点定位
   入口插件链 + 裁剪              ◄─── (复用 ← 读流程)
        │                                       │
        ▼                                       ▼
③ 语义理解 Loop                         ③ 概念提取 (LLM)
   BFS + visited + 上限                         │
        │                                       ▼
        ▼                              ④ 关系判定 (LLM) → DecisionList
④ 仲裁 (≤1, 单一职责)                          │
        │                                       ▼
        ▼                              ⑤ 图更新 (无 LLM)
⑤ 后置处理链 (0..N, 串联)                       │
                                                ▼
                                       ⑥ 压缩判定插件链 (条件触发)
                                                │
                                                ▼
                                       ⑦ 自动落盘 (StorageInterface)

OUTPUT: result (默认 List[Node])       OUTPUT: 图状态更新 + 已持久化
```

详细见各 capability spec。
