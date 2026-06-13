# Capability Spec 索引

> 按能力域分组的 spec 导航。每个 spec 定义 SHALL/MUST 形式的契约。

## 核心引擎

| Capability | 关注 |
|------------|------|
| [query-pipeline](query-pipeline/spec.md) | 读流程 5 段管线（前置→种子定位→语义 Loop→仲裁→后置），默认返回 `List[Node]` |
| [write-pipeline](write-pipeline/spec.md) | 写流程 7 段管线（前置→关联定位→提取→判定→更新→压缩→落盘） |
| [store-interface](store-interface/spec.md) | 统一存储接口（StoreInterface ABC + InMemoryStore + SQLiteStore） |
| [llm-interaction](llm-interaction/spec.md) | LLM 调用统一模式（`purpose` + `nodes_in` + `free_args`），杜绝厂商 SDK 直接调用 |
| [subgraph-bounding](subgraph-bounding/spec.md) | 最大上下文子图不变量：邻域容量约束、token 估计精度、LLM 语义归纳、一进多出聚类、hub 复用 |
| [seed-graph-hierarchy](seed-graph-hierarchy/spec.md) | 种子图层级结构：全图单向边模型、导航沿出边下钻、递归 bounding 抗退化 |

## 插件体系

| Capability | 关注 |
|------------|------|
| [plugin-protocol](plugin-protocol/spec.md) | 插件基类 Plugin、PluginType 枚举、各阶段插件接口与生命周期管理 |
| [plugin-directory-by-type](plugin-directory-by-type/spec.md) | 插件目录按 PluginType 分组，import 路径反映类型 |
| [preprocess-plugin](preprocess-plugin/spec.md) | 前置插件接口（WRITE_PREPROCESS / QUERY_PREPROCESS），类型安全挂载点 |
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

## 评测

| Capability | 关注 |
|------------|------|
| [multihop-rag-eval](multihop-rag-eval/spec.md) | MultiHop-RAG 评测流程与指标计算 |
| [bench-directory-structure](bench-directory-structure/spec.md) | bench 评测目录结构规范 |
| [bench-doc-rerank](bench-doc-rerank/spec.md) | 文档级重排评测能力 |
| [bench-doc-rerank-plugin](bench-doc-rerank-plugin/spec.md) | 文档级重排 bench-only 插件 |

## 项目骨架

| Capability | 关注 |
|------------|------|
| [project-skeleton](project-skeleton/spec.md) | 项目目录结构与接口层完整性 |
| [phase1-defaults](phase1-defaults/spec.md) | Phase 1 默认插件清单与优先级配置 |

## 研究型

| Capability | 关注 |
|------------|------|
| [graph-construction-quality](graph-construction-quality/spec.md) | 图质量诊断工具与构建增强对照实验 |

## 已废弃

| Capability | 关注 |
|------------|------|
| [seed-selector-plugin](seed-selector-plugin/spec.md) | ~~种子语义筛选~~（已合并到 TrimPlugin 链） |
