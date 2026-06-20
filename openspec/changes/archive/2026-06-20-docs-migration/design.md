# Design: 文档体系迁移

## Context

`unified-graph-schema` 已合并到 main（41/41 tasks），代码全面迁移到统一图模型。但 `docs/` 目录仍停留在旧模型——3 个文件需删除、2 个需重写/修改、6 个需新建、3 个需更新。本文档记录迁移的关键技术决策。

**现状**：`docs/` 有 10 个文件，其中 `technical-design.md`（25% 准确率）和 `memory-agent-design.md`（20% 准确率）与当前代码根本矛盾；`architecture.md`（30%）和 `core-flows.md`（60%）含大量旧概念残留；唯一正确的核心文档 `graph-model-design.md` 仍标注"草稿尚未实现"。

**约束**：纯文档变更，零代码改动，零回归风险。

## Goals / Non-Goals

**Goals:**
- 删除所有与统一图模型矛盾的旧文档
- 每份文档严格对齐当前代码（4 类节点 / 2 类边 / 无 relation_model）
- 补齐开源必需但缺失的文档（上手指南、插件体系、API 参考、Agent 说明、评测说明）
- 文档间无重复覆盖（graph-model-design.md 为核心算法唯一权威源）

**Non-Goals:**
- 不改任何 Python 代码
- 不改 `README.md`（当前基本正确）
- 不做 `memory-agent-design.md` 的归档（直接删除，git 历史可追溯）
- 不写教程/ cookbook（超出 L3 范围，后续按需补充）

## Decisions

### D1: core-flows.md 直接删除而非合并

**选择**：删除。

**理由**：逐条对比 `core-flows.md` 与 `graph-model-design.md`：
- 写入管线 7 段 → `graph-model-design.md` §5.1 更详细（含守门+聚类细化流程图）
- 查询管线 5 段 → `graph-model-design.md` §5.2 更详细（含四工作区预算分离）
- 图演化（聚类/边吸收/守门）→ `graph-model-design.md` §3.3 + §5.1 细化
- core-flows.md 唯一增量是 L91-92 的 `relation_model` 切换逻辑——这恰好是需要删除的旧概念

100% 的有用内容已被覆盖，无合并价值。

### D2: technical-design.md 直接删除而非归档

**选择**：删除（不归档到 docs/archive/）。

**理由**：
- 归档意味着还有人会读，但该文档基于属性节点/label 边/role/版本列表，与当前模型根本矛盾，读它只会误导
- git 历史完整保留，任何需要查旧设计的人可 `git log` 找到
- 归档目录本身需要维护和索引，增加复杂度

### D3: architecture.md 重写而非修补

**选择**：从当前代码结构出发重写。

**理由**：
- 现有 30% 准确率，旧概念散布在系统定位、双层结构、核心不变量、边方向、读写管线、插件体系 6 个章节
- 逐段修补风险更高：容易漏改（如 L46-50 的 attribute_node 引用藏在"为什么不这样做"段落里）
- 重写可确保结构与当前代码一一对应

**重写内容来源**：
- 系统定位 → 旧版可复用（不涉及图模型）
- 双层结构 → `graph-model-design.md` §3.3（核心/事件双层）
- 核心不变量 → `graph-model-design.md` §1
- 模块职责 → 从当前代码目录结构提取
- 插件体系 → 从 `mcs/core/plugin.py` PluginType 枚举提取
- 数据流 → 从 `mcs/core/write_pipeline.py` + `query_engine.py` 提取

### D4: 新建文档的内容来源

| 文档 | 主要信息源 |
|------|-----------|
| `getting-started.md` | `README.md` 快速开始 + `examples/basic_usage.py` + `mcs_mcp/server.py` 启动方式 + `mcs_agent/app.py` 启动方式 |
| `plugin-system.md` | `mcs/core/plugin.py`（PluginType 枚举）+ `mcs/interfaces/`（14 个接口文件）+ `mcs/plugins/`（内置插件实现）+ `CLAUDE.md` 插件类型列表 |
| `api-reference.md` | `mcs/core/mcs.py`（公开方法）+ `mcs/entities/`（数据类）+ `mcs/presets/`（Builder）+ `mcs_mcp/server.py`（MCP 工具） |
| `memory-agent.md` | `mcs_agent/loop.py`（ReAct loop + 5 工具）+ `mcs_agent/memory.py`（MemoryStore）+ `mcs_agent/app.py`（FastAPI）+ `mcs_agent/static/`（前端） |
| `evaluation.md` | `bench/README.md` + `bench/multihop_rag/runner.py` + `bench/multihop_rag/metrics.py` + `bench/extraction_quality.py` |

### D5: INDEX.md 重写而非修补

**选择**：重写。

**理由**：3 个文件删除 + 6 个文件新建 + 多个描述更新，修补的 diff 量接近重写。重写可确保索引结构与实际文档一一对应，无遗漏。

### D6: 术语一致性规则

迁移时所有文档必须遵循以下术语，不得出现旧术语：

| 术语 | 正确用法 | 禁止用法 |
|------|---------|---------|
| 节点分类 | `node_class`（概念/事实/事件/source） | `role`、`type`（节点语境下） |
| hub | `extensions["hub"]` 标记 | `role="hub"`、`hub 节点类型` |
| 边类型 | `type`（关联/互斥） | `kind`、`label` |
| 关系查询 | `get_relations` | `get_facts`、`get_assoc` |
| 事实表示 | 事实节点（`node_class=事实`），谓词在 `content` | label 事实边、属性节点、属性关系 |
| 事件背书 | `事件 → 核心`，核心不反查（载重规则） | 双向事件边 |
| 模型模式 | 单一模型 | `relation_model`、`property_graph`、`attribute_node`、双模式 |

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| 重写 architecture.md 可能遗漏旧版中仍有价值的设计解释 | 重写前逐段审阅旧版，提取不依赖旧模型的通用解释（如系统定位、核心赌注） |
| 新建文档内容可能过时（代码持续演进） | 以代码为权威源撰写，不凭记忆；完成后与代码交叉验证 |
| faq.md 小修可能遗漏 | 搜索全文 `relation_model` / `property_graph` / `role` / `kind` / `label` 确认无残留 |
| getting-started.md 中的示例可能因 API 变更失效 | 从 `examples/basic_usage.py` 和现有测试中提取已验证的用法 |

## Open Questions

无。所有决策已在 D1-D6 中明确。
