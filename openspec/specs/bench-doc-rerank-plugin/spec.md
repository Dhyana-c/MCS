## ADDED Requirements

### Requirement: bench-only 文档级重排作为 PostprocessPlugin

`doc_rerank.py` SHALL 迁移到 `bench/plugins/doc_rerank.py`，作为 bench-only 的后置处理插件，不入核心 query 插件链。它 SHALL 提供 `DocRerankPlugin` 类实现 `PostprocessPluginInterface`，同时也 SHALL 保留 `doc_rerank()` 纯函数供直接调用。

#### Scenario: 插件类实现 PostprocessPluginInterface

- **WHEN** 导入 `DocRerankPlugin`
- **THEN** 类 MUST 继承 `PostprocessPluginInterface`
- **AND** `get_type()` MUST 返回 `PluginType.POSTPROCESS`

#### Scenario: 纯函数保留供直接调用

- **WHEN** 导入 `doc_rerank` 函数
- **THEN** 函数签名 MUST 为 `doc_rerank(nodes: list[Node], query: str, top_n: int | None, min_score: float) -> list[str]`

#### Scenario: 不入核心 query 插件链

- **WHEN** 检查 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** `config.read_plugins` MUST NOT 包含 `doc_rerank` 或 `DocRerankPlugin`

#### Scenario: bench 测试可独立使用

- **WHEN** 在 bench 脚本中导入 `from bench.plugins.doc_rerank import doc_rerank`
- **THEN** 导入 MUST 成功，无需依赖 `mcs.bench` 包

---

### Requirement: bench 插件目录结构

`bench/plugins/` 目录 SHALL 存放 bench-only 插件，这些插件不入核心管线，仅供评测使用。

#### Scenario: bench 插件目录存在

- **WHEN** 检查 `bench/` 目录
- **THEN** MUST 存在 `plugins/` 子目录
- **AND** `plugins/` 下 MUST 包含 `__init__.py`

#### Scenario: bench 插件不污染 mcs 包

- **WHEN** 检查 `mcs/plugins/` 目录
- **THEN** MUST NOT 存在 `doc_rerank.py` 或 `DocRerankPlugin` 相关文件
