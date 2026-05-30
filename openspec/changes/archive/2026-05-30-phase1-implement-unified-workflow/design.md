# Design: Phase 1 Implementation on Unified Workflow

本文档记录 Phase 1（知识图谱模式）在新统一工作流之上的具体选型。架构层契约见 `unified-workflow-architecture` change（已归档则见 `openspec/specs/` 下 4 个 capability spec）。

## 1. Phase 1 默认插件集

```
EntryPlugin chain (按 priority 降序):
  ├─ AliasEntryPlugin       priority=100, exclusive=False
  └─ HubFallbackEntryPlugin priority=0,   exclusive=False

TrimPlugin (种子裁剪 + 仲裁底层):
  └─ PriorityTrimPlugin

ArbitrationPlugin (读流程 ④):
  └─ <None>   (Phase 1 不启用，accumulated 直通)

PostprocessPlugin chain:
  读流程 ⑤: <空>          (Phase 1 默认返回 List[Node])
  写流程 ①: SourceTrackingPlugin (作为前置, 含幂等检查)

CompactionPlugin chain (写流程 ⑥):
  └─ FanoutReducerPlugin   (扇出超 T 触发, 含 LLM decide_hub 调用)
  └─ SummaryRegenPlugin    (内容变更触发, 含 LLM gen_summary)

NodeExtension (挂载在 Node.extensions[plugin.name]):
  ├─ AliasEntryPlugin    → extensions["alias_entry"]["aliases"]
  ├─ SummaryPlugin       → extensions["summary"]["text"]
  └─ SourceTrackingPlugin→ extensions["source_tracking"]["sources"]

Storage / LLM 厂商:
  ├─ SQLiteStoragePlugin
  └─ DeepSeekLLMPlugin
```

## 2. 9 个 purpose 的默认 prompt + parser

| Purpose | prompt 文件 | parser 输出类型 |
|---------|-------------|-----------------|
| extract_concepts | `mcs/prompts/extract_concepts.py` | `List[ConceptDraft]` |
| judge_relations | `mcs/prompts/judge_relations.py` | `DecisionList` |
| decide_directions | `mcs/prompts/decide_directions.py` | `List[node_id]` |
| decide_hub | `mcs/prompts/decide_hub.py` | `HubDecision` |
| navigate_hub | `mcs/prompts/navigate_hub.py` | `List[node_id] \| "to_position"` |
| arbitrate | `mcs/prompts/arbitrate.py` | `List[node_id]` |
| synthesize | `mcs/prompts/synthesize.py` | `str` |
| gen_aliases | `mcs/prompts/gen_aliases.py` | `List[str]` |
| gen_summary | `mcs/prompts/gen_summary.py` | `str` |

每个 prompt 文件导出三个常量：`SYSTEM_PROMPT` / `USER_TEMPLATE` / `parse_<purpose>`。

用户覆盖路径：`MCSConfig.prompt_overrides = {"extract_concepts": {"system": "...", "template": "...", "parser": fn}}`。

## 3. 默认 token budget 与 Loop 上限

- `token_budget.T = 8000`（约 W/2，假设 W=16000）
- `query.max_rounds = 5`（BFS 最大跳数）
- `query.max_picked = 50`（累积节点上限）
- `extract_concepts` 单次 ingest 概念数软上限 = 20（超过时 LLM 自行裁剪，框架不约束）

## 4. ContextRenderer 渲染策略

```
purpose 渲染配方:
  extract_concepts:   related 节点用 name + summary, 不要 full content
  judge_relations:    related 节点用 name + content, 加 extensions 贡献
  decide_directions:  focus 节点用 content, 邻居用 name + summary
  decide_hub:         focus 节点 + 全部邻居都用 name + summary
  navigate_hub:       与 decide_directions 同
  arbitrate:          全部节点用 name + statements (versions, 若插件提供)
  synthesize:         全部节点用 content + sources 贡献
  gen_aliases:        单节点 name + content
  gen_summary:        单节点 content

NodeExtension.render(node, purpose) 贡献:
  AliasEntry        → 不贡献 (aliases 由词法索引使用, 不入 prompt)
  Summary           → 不贡献 (核心字段降级时由 renderer 自取)
  SourceTracking    → purpose=synthesize 时贡献 "出处: doc_id/chunk_id"
                      其他 purpose 不贡献
```

## 5. DecisionList schema

```python
@dataclass
class Decision:
    action: Literal["merge", "create", "attach_statement", "no_op"]
    concept: ConceptDraft           # 触发该决策的概念
    target_id: Optional[str] = None        # merge / attach_statement 用
    edges_to: Optional[List[str]] = None   # create 用
    initial_statements: Optional[List[str]] = None   # create 用
    statement: Optional[str] = None        # attach_statement 用
    reason: Optional[str] = None           # no_op 用

DecisionList = List[Decision]
```

`WritePipeline._apply_decisions(decisions, graph)` 按 action 派发到 GraphStore 原子操作。

## 6. 错误处理基线

| 情形 | 处理 |
|------|------|
| LLM 调用失败 / 超时 | 抛 `LLMCallError`，pipeline 中止；不重试（Phase 1） |
| parser 输出格式错误 | 抛 `LLMParseError`，pipeline 中止；附 raw response 供排查 |
| EntryPlugin chain 全空 | seeds 为空；query loop 立即终止；返回空 `List[Node]` |
| query loop 达到 max_rounds | 自然结束，accumulated 当前内容定型 |
| query loop 达到 max_picked | 强制结束，最后一轮可能不完整 |
| ingest LLM 抽出 0 个概念 | DecisionList 为空，⑤ 跳过，⑥ 跳过；ingest 静默返回 |
| 决策清单含未知 action | 抛 `UnknownActionError`，⑤ 中止 |

## 7. 测试策略

```
单元层:
  - GraphStore CRUD
  - ContextRenderer (purpose 驱动 + 贡献者聚合)
  - DecisionList apply 派发
  - PluginManager (优先级排序 + exclusive + 单例约束)
  - QueryContext / WriteContext 字段流转

集成层 (mock LLM):
  - 读 5 段流程: 注入 mock LLM 返回预定 decisions, 验证最终 result_set
  - 写 6 段流程: 注入 mock LLM 抽固定概念 + 固定决策, 验证图变更
  - 写复用读: 验证 ② 阶段确实调用了 query

端到端层 (真实 LLM, 默认跳过, 需 API key):
  - examples/basic_usage.py 可跑
  - examples/wiki_example.py 可跑
```

## 8. 与旧骨架的差异（迁移清单）

| 旧文件 | 新归宿 |
|--------|--------|
| `mcs/interfaces/pipeline_hook.py` | **删除** |
| `mcs/interfaces/query_hook.py` | **删除** |
| `mcs/interfaces/llm.py`（7 方法） | **重写**（新 `call` 签名）|
| `mcs/interfaces/node_extension.py` | 扩展（增加 `render` 可选方法）|
| `mcs/core/serializer.py` | **删除**（被 `context_renderer.py` 取代）|
| `mcs/core/write_pipeline.py`（9 状态点）| **重写**（6 段管线）|
| `mcs/core/query_engine.py`（7 状态点）| **重写**（5 段管线）|
| `mcs/plugins/phase1/alias_index.py`（实现 3 接口）| **重写**（拆为 `AliasEntryPlugin` + 保留 NodeExt）|
| `mcs/plugins/phase1/source_tracking.py` | **重写**（依赖新插件链）|
| `mcs/plugins/phase1/summary.py` | **重写**（按新 NodeExt.render 协议）|
| `mcs/plugins/phase1/sqlite_storage.py` | 轻改（适配 NodeExtension schema 收集）|
| `mcs/plugins/phase1/deepseek_llm.py` | **重写**（厂商适配纯化）|
| `mcs/prompts/*.py` | **重写**（按 9 个 purpose 重组织，每个 system+template+parser）|
| `mcs/utils/tokenizer.py` | 不变 |

## 9. 未决事项

- **a. ContextRenderer 输出格式**：先用缩进提纲（按 architecture.md §2.7 推荐），不引入 JSON/YAML。后续可能需要根据 LLM 表现调整。
- **b. DecisionList 在 ④ 之后、⑤ 之前是否暴露插件干预 hook**：Phase 1 不实现，Phase 2 引入审计/版本化时再加。
- **c. ConceptDraft 的字段精度**：先用 `{name, content_draft, relation_hints: List[str]}`，relation_hints 是 LLM 生成的自然语言关系描述，由 ④ 转成 attach_statement decisions。
- **d. 写流程 ② 复用读流程时的预算**：用整体 T 还是给一个独立的小预算？Phase 1 用整体 T，监控成本后再考虑独立配额。
