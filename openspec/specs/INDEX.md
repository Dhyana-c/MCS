# Capability Spec 索引

> 按能力域分组的 spec 导航。每个 spec 定义 SHALL/MUST 形式的契约。

## 核心引擎

| Capability | 关注 |
|------------|------|
| [query-pipeline](query-pipeline/spec.md) | 读流程 5 段管线（前置→种子定位→语义 Loop→仲裁→后置），默认返回 `Subgraph` |
| [write-pipeline](write-pipeline/spec.md) | 写流程 7 段管线（前置→关联定位→提取→判定→更新→压缩→落盘） |
| [store-interface](store-interface/spec.md) | 统一存储接口（StoreInterface ABC + InMemoryStore + SQLiteStore），边 API 基于 `type`（关联/互斥），`get_relations` 统一反查 |
| [llm-interaction](llm-interaction/spec.md) | LLM 调用统一模式（`purpose` + `nodes_in` + `free_args`），杜绝厂商 SDK 直接调用 |
| [subgraph-bounding](subgraph-bounding/spec.md) | 最大上下文子图不变量：邻域容量约束、token 估计精度、LLM 语义归纳、一进多出聚类、hub 复用 |
| [seed-graph-hierarchy](seed-graph-hierarchy/spec.md) | 种子图层级结构：统一边模型（关联/互斥）、核心 BFS 导航、hub 标记识别、递归 bounding 抗退化 |
| [unified-graph-schema](unified-graph-schema/spec.md) | 统一图模型核心契约：4 类节点（概念/事实/事件/source）、边仅关联/互斥、谓词落点、核心/事件双层、守门挂在改图操作上 |

## 插件体系

| Capability | 关注 |
|------------|------|
| [plugin-protocol](plugin-protocol/spec.md) | 插件基类 Plugin、PluginType 枚举、各阶段插件接口与生命周期管理 |
| [plugin-directory-by-type](plugin-directory-by-type/spec.md) | 插件目录按 PluginType 分组，import 路径反映类型 |
| [preprocess-plugin](preprocess-plugin/spec.md) | 前置插件接口（WRITE_PREPROCESS / QUERY_PREPROCESS），类型安全挂载点 |
| [edge-extension-model](edge-extension-model/spec.md) | 边扩展字段模型（`Edge.extensions` + `EdgeExtensionInterface`），逐条保真存取 / 反查 / 重组 |
| [mcs-builder](mcs-builder/spec.md) | MCS 实例构建契约：Builder 全量组装、MCS 瘦门面、双 PluginManager |
| [mcs-presets](mcs-presets/spec.md) | Phase1Builder + create_mcs() 快捷工厂函数 |

## 查询增强

| Capability | 关注 |
|------------|------|
| [query-rerank](query-rerank/spec.md) | 查询输出相关性重排，词法打分器 + 可插拔打分器接口 |
| [batch-neighbor-traverse](batch-neighbor-traverse/spec.md) | 批量邻居扩展，减少遍历 LLM 调用次数 |
| [token-budget-traverse](token-budget-traverse/spec.md) | token 预算驱动遍历，替代 max_picked 节点计数 |
| [lightweight-query](lightweight-query/spec.md) | 轻量查询模式，写入管线阶段②快速定位关联节点 |
| [estimate-memoization](estimate-memoization/spec.md) | 查询期 token 估算缓存，避免重复计算 |

## LLM 适配器

| Capability | 关注 |
|------------|------|
| [claude-llm-adapter](claude-llm-adapter/spec.md) | Anthropic Claude 适配器（Messages 协议，零 prompt 模板） |
| [ollama-llm-adapter](ollama-llm-adapter/spec.md) | Ollama 本地适配器（原生 /api/chat，支持 think 开关） |
| [llm-retry-backoff](llm-retry-backoff/spec.md) | LLM 适配器指数退避重试（429 / 网络错误自动重试） |

## 持久化与压缩

| Capability | 关注 |
|------------|------|
| [auto-persistence](auto-persistence/spec.md) | 写入后自动持久化，auto_persist 配置开关 |
| [merge-content-compaction](merge-content-compaction/spec.md) | merge 后 content 超阈值自动压缩重写 |
| [store-provenance](store-provenance/spec.md) | 存储库建库出处（schema_version / 扩展名集）记录与打开时补列 |
| [graph-summary](graph-summary/spec.md) | 图级主题摘要（图级 meta 存储 + GraphSummaryPlugin 归纳），注入 agent system prompt 供路由判断 |

## 评测

| Capability | 关注 |
|------------|------|
| [multihop-rag-eval](multihop-rag-eval/spec.md) | MultiHop-RAG 评测流程与指标计算 |
| [bench-directory-structure](bench-directory-structure/spec.md) | bench 评测目录结构规范 |
| [bench-doc-rerank](bench-doc-rerank/spec.md) | 文档级重排评测能力 |
| [bench-doc-rerank-plugin](bench-doc-rerank-plugin/spec.md) | 文档级重排 bench-only 插件 |
| [bench-utils](bench-utils/spec.md) | bench 公共工具（`bench/_env.py` 的 `load_dotenv()` 等 .env 加载） |

## 项目骨架

| Capability | 关注 |
|------------|------|
| [project-skeleton](project-skeleton/spec.md) | 项目目录结构与接口层完整性 |
| [entities-package](entities-package/spec.md) | `mcs.entities` 包职责边界：纯数据模型独占，服务 / 契约 / 异常外置 |
| [config-file-loading](config-file-loading/spec.md) | 从 YAML 配置文件加载 MCSConfig（`MCSConfig.from_file`） |
| [doc-hierarchy](doc-hierarchy/spec.md) | 文档层级规范（L1 入口 / L2 概念 / L3 规范）、docs/ 结构与开源文档规范 |
| [test-helpers](test-helpers/spec.md) | 测试辅助（`MockLLMBuilder` 等 fixture，继承 MCSBuilder 走完整 build） |
| [phase1-defaults](phase1-defaults/spec.md) | Phase 1 默认插件清单与优先级配置 |

## 应用接口

| Capability | 关注 |
|------------|------|
| [result-rendering](result-rendering/spec.md) | 核心库共享结果渲染纯函数（`mcs/rendering.py`），供 `mcs_mcp` / `mcs_agent` 复用，杜绝跨应用私有引用 |
| [mcp-server](mcp-server/spec.md) | MCP（stdio）server（顶层包 `mcs_mcp`），从 YAML 配置 build MCS 并服务 ingest / query 工具 |
| [memory-agent](memory-agent/spec.md) | 基于 MCS 的记忆 agent（独立 `mcs_agent` 包）：单线程 MCS 包装 + 5 导航工具（learn/search/associate/reason/recall）+ ReAct loop + FastAPI + 前端 |
| [graph-visualization](graph-visualization/spec.md) | 记忆图谱只读可视化：`MemoryStore.graph_view` 只读原语 + `GET /graph/expand` JSON 端点 + `graph.html` 默认渲染根子图 + 点击下钻 |

## 研究型

| Capability | 关注 |
|------------|------|
| [graph-construction-quality](graph-construction-quality/spec.md) | 图质量诊断工具与构建增强对照实验 |

## 已废弃

| Capability | 关注 |
|------------|------|
| [seed-selector-plugin](seed-selector-plugin/spec.md) | ~~种子语义筛选~~（已合并到 TrimPlugin 链） |
