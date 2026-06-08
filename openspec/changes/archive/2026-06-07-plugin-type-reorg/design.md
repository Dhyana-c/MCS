## Context

当前代码结构存在命名与架构不一致问题：
- 插件目录 `mcs/plugins/phase1/` 按阶段命名，但 `PluginType` 枚举定义了 ENTRY、TRIM、POSTPROCESS 等类型
- phase2 目录为空壳预留，增加新插件时归属模糊
- `mcs/bench/` 与顶层 `bench/` 目录职责重叠，库代码与评测脚本混杂

本次重构旨在实现：
1. 插件目录结构直接反映 `PluginType` 类型分组
2. bench 库代码迁移到顶层 `bench/` 并按评测类型组织
3. 清理空目录和散落文件

## Goals / Non-Goals

**Goals:**
- 插件目录按 `PluginType` 类型分组，每个类型一个子目录
- 所有 `from mcs.plugins.phase1.xxx` import 更新为新路径
- 删除 `mcs/plugins/phase2/` 空目录
- `mcs/bench/doc_rerank.py` 迁移到 `bench/plugins/doc_rerank.py`
- `mcs/bench/multihop_rag.py` 拆分：预处理 utilities → `bench/multihop_rag/utils.py`，runner → `bench/multihop_rag/runner.py`
- 更新所有引用路径，保持功能不变

**Non-Goals:**
- 不修改插件接口定义（`Plugin`、`PluginType`）
- 不修改插件实现逻辑
- 不修改 MCSConfig 或 MCS 类的公开 API
- 不改变评测指标口径或 LLM 调用逻辑

## Decisions

### D1: 插件目录分组策略

**决策**：每个 `PluginType` 对应一个子目录，多类型插件放入其主要类型目录（通过注释标注其他类型）

**理由**：
- `PluginType` 是 `PluginManager` 的索引键，目录结构与之对齐降低认知负担
- 一个插件文件只能在一个目录下，多类型插件需选择"主要"归属
- `get_types()` 方法保证 PluginManager 按所有类型索引，目录位置不影响运行时查找

**分配表**：

| 插件 | 主要类型 | 目录 |
|------|----------|------|
| alias_entry | ENTRY | `plugins/entry/` |
| hub_fallback | ENTRY | `plugins/entry/` |
| priority_trim | TRIM | `plugins/trim/` |
| rerank | POSTPROCESS | `plugins/postprocess/` |
| summary | POSTPROCESS | `plugins/postprocess/` |
| idempotency_check | PREPROCESS | `plugins/preprocess/` |
| source_tracking | PREPROCESS + NODE_EXTENSION + STORAGE_SCHEMA_EXT | `plugins/preprocess/`（标注多类型） |
| fanout_reducer | MAINTENANCE | `plugins/maintenance/` |
| summary_regen | MAINTENANCE | `plugins/maintenance/` |
| alias_index | INDEX | `plugins/index/` |
| community_merger | INDEX | `plugins/index/` |
| deepseek_llm | LLM | `plugins/llm/` |
| claude_llm | LLM | `plugins/llm/` |
| ollama_llm | LLM | `plugins/llm/` |
| llm_seed_selector | SEED_SELECTOR | `plugins/seed_selector/` |

**替代方案**：保持 phase1 目录，添加类型注释
- 优点：无迁移成本
- 缺点：命名与架构仍不一致，扩展时 phase2 概念更混乱

### D2: phase2 目录处理

**决策**：直接删除 `mcs/plugins/phase2/` 目录

**理由**：
- phase2 目录仅含空 `__init__.py`，无实际代码
- "记忆系统模式"概念已废弃，新插件按类型归属
- 删除避免后续混淆

### D3: bench 目录迁移策略

**决策**：
- `mcs/bench/doc_rerank.py` → `bench/plugins/doc_rerank.py`（作为 bench-only 插件）
- `mcs/bench/multihop_rag.py` → `bench/multihop_rag/` 目录拆分
- `mcs/bench/__init__.py`、`mcs/bench/README.md` 删除或合并

**理由**：
- `doc_rerank.py` 是词法打分函数，符合 POSTPROCESS 形态，可作为 bench-only 插件
- `multihop_rag.py` 约 760 行，包含数据加载、图构建、查询评测多个职责，拆分更清晰
- 顶层 `bench/` 已有 `multihop-rag/` 目录，迁移后结构一致

**替代方案**：保持 `mcs/bench/` 作为库代码，只迁移脚本
- 缺点：bench-directory-structure spec 要求"评测代码保留在 mcs/bench/ 包内"与"顶层 bench/ 组织脚本"并存，当前做法已混淆

### D4: 多类型插件标注方式

**决策**：在插件类文档字符串中标注所有类型

**理由**：
- 不修改代码逻辑，仅增强文档
- 开发者一眼可见插件的多重身份
- `get_types()` 已确保运行时正确索引

## Risks / Trade-offs

### R1: 大规模 import 路径更新

**风险**：40+ 处 import 路径变更，遗漏导致运行时错误

**缓解**：
- 使用 Grep 搜索所有 `from mcs.plugins.phase1` 引用
- 分批更新：先更新 presets/phase1.py（插件注册表），再更新测试和管线
- 运行全量测试验证

### R2: 多类型插件归属选择

**风险**：开发者可能只看目录位置，忽略插件实际实现多个接口

**缓解**：
- 在文件顶部文档字符串明确标注所有类型
- 插件类注释说明 `get_types()` 返回值

### R3: bench 迁移后外部引用

**风险**：可能有外部代码依赖 `mcs.bench.doc_rerank`

**缓解**：
- `doc_rerank.py` 迁移后原路径保留一个 deprecated alias（过渡期）
- `multihop_rag.py` 拆分后保留 `from bench.multihop_rag import ...` 兼容

## Migration Plan

### Phase 1: 插件目录重组（不影响功能）

1. 创建新目录结构：`mcs/plugins/{entry,trim,postprocess,preprocess,maintenance,index,llm,seed_selector}/`
2. 移动插件文件到对应目录
3. 更新各目录 `__init__.py`
4. 删除 `mcs/plugins/phase1/`、`mcs/plugins/phase2/`

### Phase 2: 更新引用路径

1. 更新 `mcs/presets/phase1.py` 的插件注册表
2. 更新所有测试文件的 import
3. 更新 `mcs/core/write_pipeline.py` 等管线的 import
4. 更新 `mcs/bench/doc_rerank.py` 的 rerank 引用（迁移前）

### Phase 3: bench 目录迁移

1. 创建 `bench/plugins/doc_rerank.py`
2. 创建 `bench/multihop_rag/` 目录结构
3. 拆分 multihop_rag.py 代码
4. 删除 `mcs/bench/` 原文件

### Phase 4: 测试验证

1. 运行 `.venv/Scripts/python.exe -m pytest -q` 全量测试
2. 检查无遗漏 import 错误
3. 检查 bench 脚本可正常运行

## Open Questions

1. **multihop_rag.py 拆分粒度**：是按职责拆成 utils/runner/report，还是保持单文件迁移？
   - 当前倾向：拆分成 `utils.py`（数据加载/切块）、`runner.py`（评测逻辑）、`config.py`（配置类）

2. **doc_rerank.py 是否需要插件化**：目前是纯函数，是否需要包装成 POSTPROCESS 插件类？
   - 当前倾向：保留纯函数形态，作为 bench-only utility；后续可按需插件化