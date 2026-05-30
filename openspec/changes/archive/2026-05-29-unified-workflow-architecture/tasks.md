## 1. 文档落地

- [x] 1.1 删除 `openspec/specs/architecture.md`（v2.0，旧 9+7 状态点架构文档）
- [x] 1.2 验证 4 个 capability spec delta 在本 change 的 `specs/` 下就位：`query-pipeline/spec.md`、`write-pipeline/spec.md`、`plugin-protocol/spec.md`、`llm-interaction/spec.md`（archive 时由 openspec 自动落地到 `openspec/specs/`）
- [x] 1.3 在 `openspec/specs/` 下新建一份精简的 `architecture.md`（索引文档），仅指向 4 个 capability spec、`MCS技术方案.md` 与 `project-skeleton/spec.md`
- [x] 1.4 更新 `README.md`：项目简介从"知识图谱与检索引擎"改为"可扩展记忆系统"；引用链接从旧 architecture.md 改为 4 个新 capability

## 2. 验收

- [x] 2.1 运行 `openspec validate unified-workflow-architecture --strict` 通过
- [x] 2.2 `openspec show unified-workflow-architecture` 显示 4 个 capability 的 ADDED Requirements 列表完整
- [x] 2.3 4 个 capability spec 各自至少含 1 个 Requirement 且每个 Requirement 至少含 1 个 Scenario（OpenSpec 硬约束）
- [x] 2.4 design.md 的 16 项决策都能在 4 个 spec delta 中找到对应 Requirement（D01-D16 全部追溯到 Requirement，trace 见下方）

## 3. 下游 change 已就位（参考，无 checkbox）

代码层改造（接口重写、核心引擎按新管线改造、Phase 1 五插件落地、测试、示例）已分流到独立 change：

- `openspec/changes/phase1-implement-unified-workflow/`
  - 范围：完整 Phase 1 实现（含测试与示例）
  - 依赖：本 change 必须先归档（4 个 capability spec 落地到 `openspec/specs/`）后才能 apply
  - 新增 capability：`phase1-defaults`（Phase 1 选型契约）

本 change 与下游 change 的职责切分：
- 本 change：**定义新架构契约**（4 个 capability 的 SHALL/MUST 规则）
- 下游 change：**实施新架构**（具体代码 + 默认选型 + 测试）

## 4. 决策追溯（§2.4 verification trace）

| 决策 | 落地的 Requirement |
|------|-------------------|
| D01 MCS 定位 = 可扩展记忆系统 | query-pipeline: "query 默认返回节点集合而非答案文本" |
| D02 默认返回 List[Node] | query-pipeline: "query 默认返回节点集合而非答案文本" |
| D03 读流程 5 段 | query-pipeline: "读流程为 5 段固定管线" |
| D04 写流程 6 段 | write-pipeline: "写流程为 6 段固定管线" |
| D05 写复用读 | write-pipeline: "关联节点定位通过复用读流程实现" |
| D06 入口策略全部插件化 | query-pipeline: "入口插件链累积合并并按优先级排序" + "顶点导航兜底作为最低优先级入口插件" |
| D07 裁剪/截取统一 TrimPlugin | query-pipeline: "种子裁剪使用统一 TrimPluginInterface" + plugin-protocol: "提供 TrimPluginInterface" |
| D08 Loop = BFS + visited + 上限 | query-pipeline: "语义理解 Loop 为 BFS 且维护 visited 集合" + "语义理解 Loop 的硬上限" |
| D09 仲裁单一职责 ≤1，后置开放可串 | query-pipeline: "仲裁单一职责且每条管线至多一个" + "后置处理链开放可串联" |
| D10 提取/判定分两次 LLM | write-pipeline: "概念提取与关系判定分两次 LLM 调用" |
| D11 决策/应用严格分开 | write-pipeline: "DecisionList 为纯数据，与图更新严格分离" |
| D12 压缩判定插件化 | write-pipeline: "压缩判定为插件链且条件触发" + plugin-protocol: "提供 CompactionPluginInterface" |
| D13 写流程线性 | write-pipeline: "写流程为 6 段固定管线"（含 scenario "写流程不含内部 Loop"） |
| D14 写流程无独立仲裁位 | write-pipeline: "写流程无独立仲裁位" |
| D15 LLM 接口收 Node 对象 | llm-interaction: "LLM 调用使用统一签名" + "框架统一序列化节点对象" + "提供 ContextRenderer 取代旧 Serializer" |
| D16 prompt 用户可覆盖 | llm-interaction: "system_prompt / user_template / parser 用户可覆盖" |
