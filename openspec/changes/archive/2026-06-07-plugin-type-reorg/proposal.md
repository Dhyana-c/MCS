## Why

当前插件目录按"阶段"(phase1/phase2)分组，但实际插件按类型(PluginType)运作。这种命名与架构的不一致造成：
1. **认知负担**：开发者需在 phase1 目录下查找 ENTRY、TRIM 等类型插件，命名与职责脱节
2. **扩展障碍**：phase2 目录预留给"记忆系统模式"，但当前为空，增加新插件时归属模糊
3. **bench 代码职责混乱**：`mcs/bench/` 下既有库代码(doc_rerank.py、multihop_rag.py)又有评测脚本(hotpot.py)，与顶层 `bench/` 目录重叠

## What Changes

1. **插件目录按类型重组**：`mcs/plugins/phase1/` → `mcs/plugins/<type>/`
   - `mcs/plugins/entry/`：Entry 插件(alias_entry, hub_fallback)
   - `mcs/plugins/trim/`：Trim 插件(priority_trim)
   - `mcs/plugins/postprocess/`：Postprocess 插件(rerank, summary)
   - `mcs/plugins/preprocess/`：Preprocess 插件(idempotency_check, source_tracking)
   - `mcs/plugins/llm/`：LLM 插件(deepseek_llm, claude_llm, ollama_llm)
   - `mcs/plugins/node_extension/`：NodeExtension 插件(source_tracking 的扩展部分)
   - `mcs/plugins/maintenance/`：Maintenance 插件(fanout_reducer, summary_regen)
   - `mcs/plugins/index/`：Index 插件(alias_index, community_merger)
   - `mcs/plugins/seed_selector/`：SeedSelector 插件(llm_seed_selector)

2. **删除 phase2 空目录**：phase2 目前为空壳，删除避免混淆

3. **bench 目录迁移与重构**：
   - **迁移**：`mcs/bench/` → `bench/`（合并到已有顶层 bench 目录）
   - **doc_rerank.py 重构**：抽象为 `DocRerankPlugin`（POSTPROCESS 类型，bench-only）
   - **multihop_rag.py 重构**：预处理逻辑(data loading/chunking)保留为 bench utilities，MCS 构建与查询通过 builder + config 实现

4. **更新引用路径**：所有 `from mcs.plugins.phase1.xxx` 改为 `from mcs.plugins.<type>.xxx`

## Capabilities

### New Capabilities

- `plugin-directory-by-type`: 插件目录结构按 PluginType 分组，而非阶段划分
- `bench-doc-rerank-plugin`: 文档级重排作为 POSTPROCESS 插件（bench-only，不入核心链）

### Modified Capabilities

- `plugin-protocol`: 插件目录结构变更，不影响接口定义本身，但影响插件发现路径
- `mcs-presets`: Phase1Builder 的插件注册表路径从 phase1 改为按类型分组

## Impact

**影响范围**：
- 所有 `from mcs.plugins.phase1.xxx` 的 import 语句（约 40+ 处）
- `mcs/presets/phase1.py` 的插件注册表映射
- 测试文件中的插件 import
- `mcs/bench/doc_rerank.py` → `bench/plugins/doc_rerank.py`
- `mcs/bench/multihop_rag.py` → `bench/multihop_rag/`（拆分 utilities + runner）

**不影响**：
- 插件接口定义(`Plugin`, `PluginType`)
- 插件实现逻辑本身
- 外部 API（MCSConfig、MCS 类接口不变）