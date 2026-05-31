## Why

MCS 是基于 LLM 语义驱动的知识图谱记忆系统，核心能力是"多跳语义游走"——通过 BFS 在图上逐步扩展相关节点来回答需要跨多个概念推理的问题。但目前缺乏端到端的定量评测：无法回答"MCS 的多跳召回能力到底有多强？"这个根本问题。HotpotQA 是业界标准的多跳问答 benchmark，天然适合验证 MCS 的核心赌注——"知识有足够的局部性，几跳语义游走就能连到一起"。

## What Changes

- 新增 `mcs/bench/` 模块，包含 HotpotQA 评测框架
- 新增 HotpotQA 数据加载器：从 `hotpot_dev_distractor_v1.json` 读取数据、采样子集
- 新增 context → MCS ingest 适配器：将每条数据的 context（10 个段落）批量摄入
- 新增 MCS query → HotpotQA 预测格式转换器：从返回节点中提取 answer 和 supporting facts
- 新增评测运行器：驱动 ingest + query + 评估全流程，输出 HotpotQA 官方指标
- 新增配置方案：支持子集大小、LLM 后端、token 预算等参数化
- 适配 `hotpot_evaluate_v1.py` 评测脚本，不修改原始代码（但需安装其依赖 `ujson`）

## Capabilities

### New Capabilities
- `hotpot-eval`: HotpotQA 多跳问答端到端评测框架，包括数据加载、ingest 适配、查询适配、指标计算

### Modified Capabilities

## Impact

- 新增 `mcs/bench/` 模块（不影响现有核心代码）
- 依赖本地已有的 HotpotQA 数据文件（`D:\code\hotpot\hotpot_dev_distractor_v1.json`）
- 依赖 `hotpot_evaluate_v1.py`（已下载到 `D:\code\hotpot\`）及其依赖 `ujson`
- 每条数据使用独立存储（`:memory:` 或独立 db），避免 load-on-startup 跨条污染
- 查询端需要新增 answer 提取逻辑（从 List[Node] → answer string + supporting facts），supporting_facts 取自 `source_tracking` 的 `section_title`
- 每次评测会产生实际 LLM API 调用费用