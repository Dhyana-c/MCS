## Context

ef2384d（rich-concept-content）将概念描述从平均 79 字提升到 2-4 句，root 扇出从 762 降到 14。但同时留下三个缺口：

1. **merge content 无界增长**：`_dispatch_merge` 纯追加 content（子串去重），但子串去重防不住同义改写。高频概念（如人名）在多篇文档中被反复 merge，content 持续膨胀。不变量守门（`_guard_invariant`）解决的是"节点+邻居超 T → 裂变邻居"，不压缩单节点自身。超长焦点节点会：① `estimate_node` 变大 → 遍历批次变小 → LLM 调用变多；② 词法重排噪声增大。
2. **别名通道被收窄**：`judge_relations` prompt 删掉了 `aliases_to_add` 字段，merge 时 LLM 不再贡献额外别名。而消融数据显示 **alias_entry 关键词召回是检索主力**——削弱别名富集可能直接打在主通道上。
3. **rerank 缓存 + 重试退避的 spec 缺陷**：pending 的 perf-optimization-overhaul 提案里，rerank token 缓存以 `node_id` 为 key 不感知 merge 原地改写；重试退避只覆盖 deepseek 适配器。

约束：
- 插件体系（`PluginType` 索引）、单向依赖（core 不依赖 interfaces）
- 铁律一（估算口径 == 渲染口径）不受影响——content 压缩改的是 `node.content` 本身，不是渲染方式
- `Decision.aliases_to_add` 字段和 `_dispatch_merge` 的别名并入逻辑仍存在于代码中（仅 prompt 端被移除）

## Goals / Non-Goals

**Goals:**

- merge 后 content 超过阈值时自动 LLM 压缩，防止单节点 content 无界增长
- 恢复 `judge_relations` 的别名富集能力，确保 alias 索引规模不因 ef2384d 而缩减
- 修正 perf-optimization-overhaul 的 rerank 缓存 key 方案，适配 merge 原地改写
- 将 LLM 重试退避提升为共享机制，三适配器统一覆盖
- 所有变更保持已有测试通过

**Non-Goals:**

- 不改变 content 压缩的 LLM prompt 质量——复用已有 `gen_summary`，不做新 prompt 调优
- 不做全量重建验证——那是 A3 bench 的事
- 不改动 `estimate_node` 估算口径
- 不做独立 gen_aliases 步骤（已有 prompt 但 Phase 1 不自动调用，本次通过 judge_relations 恢复即可）

## Decisions

### D1：content 压缩的触发机制

**选择**：在 `_dispatch_merge` 追加 content 后，检查 `len(node.content) > threshold`（默认 500 字），超阈值则调用 `llm_caller(purpose="gen_summary", ...)` 重写 `node.content`。

**理由**：
- `_dispatch_merge` 已经是内容变更的唯一点（create 不会合并），在此处拦截最直接
- 复用 `gen_summary` prompt——已有 `SummaryRegenPlugin` 证明此 prompt 可用，无需新建 purpose
- 阈值 500 字：2-4 句描述约 100-200 字，merge 2-3 次后约 300-600 字，500 阈值在 merge 3 次左右触发，合理平衡压缩频率和内容保真
- 压缩发生在 `_dispatch_merge` 内部、`_notify_indexes` 之前，保证索引拿到的是压缩后的内容

**替代方案**：
- ① 在 `SummaryRegenPlugin` 中加 content 压缩逻辑——`SummaryRegenPlugin` 是 CompactionPlugin（阶段 ⑥），而 `_dispatch_merge` 是阶段 ⑤，压缩延迟到 ⑥ 意味着 ⑤ 的守门检查看到的是未压缩的超长 content，可能导致误触发裂变
- ② 用子串去重 + 语义去重——语义去重本身需要 LLM，且不如直接压缩来得彻底
- ③ 不压缩，改用滑动窗口截断——会丢失信息，违反"概念描述自包含"的设计意图

**实现细节**：
- `_dispatch_merge` 签名不变，但需要访问 `llm_caller`。当前 `_dispatch_merge` 是 `WritePipeline` 的私有方法，`WritePipeline` 持有 `self.llm`（`LLMInterface`）
- 压缩调用：`self.llm.call(purpose="gen_summary", nodes_in=[node], free_args={"max_tokens": 200})` → 返回压缩后文本 → 替换 `node.content`
- 异常安全：压缩失败时 log warning，保留原始 content（不阻塞 merge 流程）
- 阈值可配置：`WritePipeline.__init__` 新增 `merge_content_threshold: int = 500` 参数

### D2：别名富集的恢复方式

**选择**：在 `judge_relations` 的 `SYSTEM_PROMPT` 和 `USER_TEMPLATE` 中恢复 `aliases_to_add` 字段说明，让 LLM 在 merge 决策时可以贡献额外别名。

**理由**：
- `Decision.aliases_to_add` 字段仍在 `decisions.py` 中（仅标记 deprecated），`_dispatch_merge` 的别名并入逻辑完好——只需要在 prompt 端恢复输出指引
- `judge_relations` 的 `parse` 函数已宽容解析 `aliases_to_add`（第 96 行），无需改动
- 这是最低成本的恢复方式：改两行 prompt 文本，零代码变更
- `gen_aliases` prompt 已存在但 Phase 1 不自动调用——后续如需更强别名富集可独立启用

**替代方案**：
- ① 独立 `gen_aliases` 步骤——每次 merge 额外一次 LLM 调用，成本高且调度复杂
- ② 在 `extract_concepts` 阶段加别名——extract_concepts 输出 `ConceptDraft`，无 alias 字段；加字段改动更大
- ③ 不恢复，靠 concept.name 作为唯一别名源——ef2384d 前的数据表明 alias 索引规模和候选召回率依赖 LLM 贡献的别名

**实现细节**：
- `SYSTEM_PROMPT` 加一句："merge 时如果该概念有同义词、缩写、变体写法，在 aliases_to_add 中列出。"
- `USER_TEMPLATE` 的 JSON 示例加 `"aliases_to_add": ["别名1", "别名2"]` 字段
- `Decision.aliases_to_add` docstring 去掉 `# DEPRECATED: 不再使用` 标记

### D3：rerank 缓存 key 方案

**选择**：`LexicalScorer._token_cache` 的 key 从 `node_id` 改为 `(node_id, content_hash)`，其中 `content_hash = hash(node.content or "")`。

**理由**：
- merge 原地改写 `node.content` 后，`hash()` 值自然变化 → 下次 `score()` 调用 cache miss → 重新分词 → 缓存自动失效
- 无需额外的失效逻辑或 hook——merge 不需要知道 rerank 缓存的存在
- `hash()` 对 < 1KB 文本开销可忽略；`score()` 本身已做分词（缓存命中时省的是分词开销），hash 比分词轻几个量级
- 跨查询场景：同一查询期间节点 content 不变，hash 稳定，缓存有效；跨查询时 `LexicalScorer` 实例重建（每次 `RerankPlugin.process` 新建 scorer 实例或缓存不跨请求），无脏缓存风险

**替代方案**：
- ① `_dispatch_merge` 后主动清缓存——需要 `WritePipeline` 知道 `LexicalScorer` 的存在，打穿插件边界
- ② `update_entry` hook 失效——需要在 `AliasIndexPlugin` 上加回调，且 perf 提案的 rerank 缓存在 `LexicalScorer` 内部而非 `AliasIndexPlugin`，不通
- ③ 不缓存 content，只缓存 name——name 几乎不变（merge 不改 name），但 content 是 rerank 的主要信号源，不缓存 content 收益大减

### D4：共享重试机制的归属

**选择**：在 `LLMInterface` 基类（`mcs/interfaces/llm.py`）新增 `_call_with_retry(fn, *args, **kwargs)` 方法，封装指数退避 + jitter 重试逻辑。三个适配器的 `_raw_call` 内部改调 `self._call_with_retry(self._single_call, system, user)`。

**理由**：
- perf 提案 D3 选择了"放在厂商适配器 `_raw_call` 内"——但三个适配器需要完全相同的重试逻辑，复制三份是维护负担
- 提升到 `LLMInterface` 基类：① 一次实现覆盖所有适配器；② 未来新增适配器自动获得重试能力；③ 厂商特化的错误类型仍可在子类 `_raw_call` 内区分
- `LLMInterface` 已有 `_raw_call` 抽象方法，新增 `_call_with_retry` 不改已有接口签名
- 退避参数（`max_retries`, `base_delay`）通过 `LLMInterface.__init__` 的 config 注入

**替代方案**：
- ① 三适配器各自实现重试——代码重复，且容易遗漏（当前只列了 deepseek）
- ② 装饰器 `@with_retry`——Python 装饰器在类方法上不如显式方法调用清晰，且需要额外 import
- ③ 在 `call()` 层统一重试——`call()` 是完整管线（渲染→组装→调用→解析），重试粒度太粗，解析失败不应重试

**实现细节**：
- `_call_with_retry(fn, *args, **kwargs)` 接受一个 callable（即原来的 `_raw_call` 逻辑），在基类中实现退避循环
- 可重试异常：网络错误、429 rate limit——由子类抛出的 `LLMCallError` 包含原始异常，基类通过 `isinstance(e.__cause__, ...)` 判断
- 退避公式：`delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)`（jitter）
- 参数：`max_retries=3`, `base_delay=1.0`，可通过 config 覆盖
- Ollama 适配器特殊性：HTTP 错误不抛异常类而是检查 `resp.status_code`，需在 `_raw_call` 内将 429/5xx 转为可重试异常

## Risks / Trade-offs

| 风险 | 缓解措施 |
|------|----------|
| content 压缩引入额外 LLM 调用，增加建图耗时 | 只在 merge 超 500 字阈值时触发；大多数 merge 不触发；压缩调用轻量（gen_summary，200 字以内） |
| 压缩后 content 丢失细节 | `gen_summary` prompt 要求"保留关键概念与定义"；压缩失败时保留原始 content（异常安全） |
| 别名恢复增加 judge_relations 输出 token | 每个 merge 决策多 0-3 个别名，JSON 字段级影响可忽略 |
| `hash()` 在不同 Python 进程间不稳定（PYTHONHASHSEED） | 缓存仅在单次 `score()` 调用链内有效，不跨进程/持久化，无影响 |
| 共享重试增加 `_raw_call` 调用延迟（最坏 3× 退避） | 默认 max_retries=3, base_delay=1s → 最坏约 7s；429 本身意味着需要等待；可通过 config 调整 |
| Ollama HTTP 错误需要额外包装才能被共享重试捕获 | Ollama `_raw_call` 内部将 429/5xx 包装为 `LLMCallError` 并标记可重试属性 |

## Migration Plan

本次变更无数据迁移、无 API breaking change。

**部署顺序**：

1. **Step 1 — B2 共享重试基类**（独立于其他改动，可先行）：
   - `LLMInterface` 新增 `_call_with_retry`
   - 三适配器 `_raw_call` 改走共享方法
   - 验证：`pytest -q`

2. **Step 2 — B1 rerank 缓存 key**（独立于其他改动）：
   - `LexicalScorer._token_cache` key 含 content hash
   - 验证：`pytest -q`

3. **Step 3 — A1 content 压缩 + A2 别名恢复**（需一起做，都在 write_pipeline 相关文件）：
   - `_dispatch_merge` 加压缩步骤
   - `judge_relations` prompt 恢复 `aliases_to_add`
   - `Decision.aliases_to_add` 取消 deprecated
   - 验证：`pytest -q`

4. **Step 4 — A3 bench 验证**：
   - 200 篇子集 A/B 对比 hit@10、alias 索引规模、候选召回率

**回滚策略**：每个 Step 独立可回滚。content 压缩可通过将 `merge_content_threshold` 设为 `0`（禁用）一步回滚。别名恢复通过还原 prompt 两行文本回滚。

**与 perf-optimization-overhaul 的关系**：Step 1 和 Step 2 是对 perf 提案任务 5/7 的修正，实现时应直接修改 perf change 的对应任务产出，而非独立并行。执行顺序：perf change 其他任务先完成 → Step 1+2 合并到 perf change → Step 3 → 全量重建。
