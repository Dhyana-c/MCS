# query-rerank Spec Delta — retire-framework-query-pipeline

> **整体退役**：`query-rerank` capability 提供 `query_postprocess` 重排插件（`RerankPlugin` / `LexicalScorer`），仅服务读查询管线阶段 ⑤。随 `PluginType.POSTPROCESS` 删除与 `query()` 退役，capability **全部 requirement REMOVED**。归档时 `openspec/specs/query-rerank/` 整目录从 main spec 移除。
>
> 重排 / 摘要能力若未来需要，由记忆 agent 工具层实现，不在框架读管线内。

## REMOVED Requirements

### Requirement: 查询输出相关性重排插件
### Requirement: LexicalScorer 仅从 node.content 提取词法 token
### Requirement: LexicalScorer 维护节点 token set 缓存
