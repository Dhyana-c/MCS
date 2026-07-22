# bench-doc-rerank-plugin Delta

> migration-audit-fixes：E2 spec 仍称 `DocRerankPlugin` 实现 `PostprocessPluginInterface`，但该接口 +
> `PluginType.POSTPROCESS` 已随 retire-framework-query-pipeline 退役删除；`bench/plugins/doc_rerank.py` 现状
> 是纯函数模块（无插件类）。收敛 spec 到代码现状。

## REMOVED Requirements

### Requirement: bench-only 文档级重排作为 PostprocessPlugin

> REMOVED：`DocRerankPlugin` 类 / `PostprocessPluginInterface` / `PluginType.POSTPROCESS` 三者随
> retire-framework-query-pipeline 退役删除；`doc_rerank.py` 现为纯函数模块，无插件类。由下方 ADDED 的
> 「bench-only 文档级重排为纯函数（无插件类）」取代。

## ADDED Requirements

### Requirement: bench-only 文档级重排为纯函数（无插件类）

`bench/plugins/doc_rerank.py` SHALL 为 bench-only 的**纯函数**模块（离线文档级重排），MUST NOT 入核心 query 插件链（核心读查询已改由记忆 agent 驱动、插件链已退役）。MUST NOT 定义 `DocRerankPlugin` 类、MUST NOT 继承 `PostprocessPluginInterface`、MUST NOT 引用 `PluginType.POSTPROCESS`（三者随 retire-framework-query-pipeline 删除）。SHALL 保留 `doc_rerank()` 纯函数供评测脚本直接调用。

#### Scenario: 不实现任何核心插件接口

- **WHEN** 检查 `bench/plugins/doc_rerank.py` 源码
- **THEN** MUST NOT 定义 `DocRerankPlugin` 类
- **AND** MUST NOT 继承 / import `PostprocessPluginInterface`
- **AND** MUST NOT 引用 `PluginType.POSTPROCESS`

#### Scenario: 纯函数保留供直接调用

- **WHEN** 导入 `doc_rerank` 函数
- **THEN** 函数签名 MUST 为 `doc_rerank(nodes: list[Node], query: str, top_n: int | None, min_score: float) -> list[str]`

#### Scenario: 不入核心 query 插件链

- **WHEN** 检查 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** `config.read_plugins` MUST NOT 包含 `doc_rerank` 或 `DocRerankPlugin`

#### Scenario: bench 测试可独立使用

- **WHEN** 在 bench 脚本中导入 `from bench.plugins.doc_rerank import doc_rerank`
- **THEN** 导入 MUST 成功，无需依赖 `mcs.bench` 包
