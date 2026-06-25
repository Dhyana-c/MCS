## Why

当前 `TokenBudget.estimate()` 使用统一经验式（CJK ≈ 1 字符/token、非 CJK ≈ 4 字符/token），不区分 LLM 模型。但不同模型的 tokenizer 差异显著：

| 模型族 | 中文实际 token/字 | 当前估算 | 偏差 |
|--------|:----------------:|:-------:|:----:|
| Claude 3.5 | ~1.5–2.0 | 1.0 | **低估 50–100%** |
| GPT-4o | ~1.5–2.0 | 1.0 | **低估 50–100%** |
| DeepSeek-V3 | ~0.6–1.0 | 1.0 | 略高估 |
| Qwen2.5 (Ollama) | ~0.6–1.0 | 1.0 | 略高估 |

**核心风险**：对 Claude/GPT 中文场景低估 50–100%，意味着守门认为"活跃视图 ≤ T"时实际可能已超 T——**核心不变量被悄悄破坏**。铁律一要求"估算口径 == 渲染口径"，但两者共用同一个粗略估算，等于两个错误互相抵消而非真正保证"实际 token ≤ T"。

同时，`TokenBudget` 与 `LLMInterface` 完全解耦——`builder.py` 构造 `TokenBudget` 时不知道将使用哪个 LLM，无法根据模型特性选择估算策略或调整 W/S/T/R 默认值。

## What Changes

### 1. LLMInterface 提供 token 计数能力

- `LLMInterface` 新增 `count_tokens(text: str) -> int` 方法
- 默认实现使用校准经验式（按模型族调整系数）
- DeepSeek/Ollama 覆盖为精确计数（tiktoken）；Claude 走默认校准式（口径一致性优先，API 仅离线校准）

### 2. 各 LLM 插件的精确 token 计数实现

**计数策略**：DeepSeek/Ollama 用本地 tiktoken（cl100k_base），失败降级校准经验式；
Claude 运行时直接用校准经验式（口径一致性优先），Anthropic count_tokens API 仅用于
bench/calibration 离线校准（不作运行时 counter）。

```
┌─────────────────────────────────────────────────────────────────────┐
│  ClaudeLLMPlugin                                                    │
│  ────────────────                                                   │
│  运行时：校准经验式（claude 族 ×1.7/÷3）——确定性、本地、口径一致     │
│  离线校准：Anthropic count_tokens API（仅 bench/calibration 用）      │
│                                                                     │
│  不 override count_tokens：走 LLMInterface 默认实现，按               │
│  _detect_model_family 选 claude 族系数。                             │
│  （API 不作运行时 counter：O(邻域) 网络调用 + 降级破坏口径一致性）    │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  DeepSeekLLMPlugin                                                  │
│  ──────────────────                                                 │
│  首选：tiktoken cl100k_base（DeepSeek tokenizer 与 GPT-4 相近，     │
│        误差 <10%；本地计算、零延迟、零成本）                          │
│  兜底：校准经验式（tiktoken 未安装时——必选依赖下理论上不会触发）       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  OllamaLLMPlugin                                                    │
│  ────────────────                                                   │
│  首选：tiktoken cl100k_base（Qwen 等模型 tokenizer 与 GPT-4 相近，  │
│        误差 <15%；本地计算、零延迟、零成本）                          │
│  兜底：校准经验式（tiktoken 未安装时——必选依赖下理论上不会触发）       │
│                                                                     │
│  注：Ollama 原生 API 无 count_tokens 端点；tiktoken 是最佳本地方案   │
└─────────────────────────────────────────────────────────────────────┘
```

**Claude count_tokens API 仅作离线校准（不作运行时 counter）**：
- 端点：`POST /v1/messages/count_tokens`，免费、精度高（误差 <5%），用于 bench/calibration 定标
- **不作运行时 counter 的原因**：API 作为 TokenBudget 全域 counter 时，查询 bounding/trim
  链逐节点 `estimate_node` 会产生 O(邻域) 次同步网络调用（延迟 + Tier1 100RPM 速率限制）；
  且 429/网络失败降级到校准式时，同一文本在不同调用返回不同值（API 值 ↔ ×1.7），破坏
  铁律一"口径一致性"——而口径一致性恰是精度论证的前提
- **运行时方案**：ClaudeLLMPlugin 不 override `count_tokens`，走默认实现（claude 族 ×1.7/÷3），
  确定性、本地、口径严格一致

**tiktoken 关键特性**：
- 纯本地计算，零延迟、零成本、无速率限制
- `cl100k_base`：GPT-4 / GPT-3.5-turbo 的编码，对 DeepSeek/Qwen 近似度足够
- `o200k_base`：GPT-4o 的编码，可按模型名自动选择
- 包体积 ~1MB + 词表缓存，轻量
- **作为必选依赖**加入 `pyproject.toml`，确保 DeepSeek/Ollama 插件始终可用本地精确计数

### 3. 校准经验式——兜底方案

新增 `CalibratedEstimator`，替代当前硬编码的 `CJK 1:1 + 非CJK 4:1`：

```
模型族         CJK 系数    非CJK 系数    来源
─────────────────────────────────────────────
claude         ×1.7        ÷3           文献/经验值（待实测）
gpt (tiktoken) ×1.7        ÷3           文献/经验值（待实测）
deepseek       ×1.3        ÷4           文献/经验值（待实测）
ollama/qwen    ×1.3        ÷4           文献/经验值（待实测）
unknown        ×1.7        ÷3           保守（宁可高估不破坏不变量）
```

**设计原则**：宁可高估（过早触发裂变、浪费容量）也不低估（破坏不变量）。unknown 模型采用 claude/gpt 系数（最保守）。

仅在精确方案不可用时使用（tiktoken 导入失败——必选依赖下理论上不会触发，但保留防御性兜底）。Claude 运行时直接走此校准式。系数为文献/经验值，`bench/calibration` 提供校准工具，待实测定标后更新。

### 4. TokenBudget 从 write_llm 获取 counter

- `MCSBuilder.build()` 中，先实例化 LLM 插件，再用 **write_llm** 的 `count_tokens` 构造 `TokenBudget`
- **选择 write_llm 的理由**：写入侧的守门是核心不变量的主要守护者（改图操作后检查邻域是否超 T），写入时必须准确估算
- `TokenBudget` 的 `counter` 注入点已预留，无需修改其接口
- 当 write_llm ≠ read_llm 时，查询侧的 token 估算也使用 write_llm 的 counter——保持全局口径一致，避免同一图在不同路径下对"是否超 T"判断不一致

### 5. 构建顺序调整

当前 `builder.py` 的 14 步流程中，step 2 构造 `TokenBudget`、step 4 才注册 LLM 插件。调整方案：

**将 LLM 插件实例化提前到 TokenBudget 之前**，具体步骤：

1. step 1: 实例化 Store（不变）
2. step 2: 实例化双 PluginManager（不变）
3. step 3: **按配置实例化并注册插件**（原 step 4，提前）——获取 write_llm / read_llm
4. step 4: **用 write_llm.count_tokens 构造 TokenBudget**（原 step 2，后移）
5. step 5-14: 其余步骤不变（SQLite 初始化、ContextRenderer、PluginContext 等）

**依赖分析**：LLM 插件实例化只需要 `config`（构造时传入），不依赖 Store / TokenBudget / ContextRenderer——因此提前是安全的。LLM 的 `initialize(context)` 仍发生在 step 7（PluginContext 构建后），`count_tokens` 在 `initialize` 之前就可使用（它只依赖 `self.model` 和 tiktoken/anthropic SDK，不依赖 ContextRenderer）。

### 6. W/S/T/R 默认值按模型上下文窗口自动建议

- `LLMInterface` 新增 `context_window_size` 属性（返回模型上下文窗口 token 数）
- 各 LLM 插件根据其默认模型的已知窗口大小提供值，**使用插件内映射表**（模型名 → 窗口大小）
- 映射表覆盖已知模型，未知模型回退默认值（16000）
- `MCSConfig.knowledge_graph()` 工厂方法根据 LLM 选择自动设置合理的 `token_budget`（T）默认值
- 用户显式配置 `token_budget` 时覆盖自动值（手动优先）

**已知模型窗口大小映射**：

| 模型 | 上下文窗口 |
|------|:---------:|
| claude-3-5-sonnet-latest | 200000 |
| claude-3-opus-latest | 200000 |
| deepseek-chat | 128000 |
| deepseek-reasoner | 128000 |
| qwen3.5:9b (Ollama) | 8192（= num_ctx，用户可配） |
| 默认/未知 | 16000 |

**T 默认值策略**：`T = min(8000, (context_window_size - S) // 2)`，其中 S 取 2000（系统提示词典型开销），R = T。保守上限 8000（Phase 1 守门/聚类在此规模验证过）。例如：
- Claude 3.5：min(8000, (200000 - 2000) // 2) = 8000
- DeepSeek：min(8000, (128000 - 2000) // 2) = 8000
- Ollama（num_ctx=8192）：min(8000, (8192 - 2000) // 2) = **3096** ⚠️ 行为变更
- 用户显式配置 `token_budget` 时覆盖自动值（手动优先）

> **⚠️ Ollama 行为变更**：旧版 `knowledge_graph(write_llm="ollama")` 固定 T=8000，但
> T+R=16000 > num_ctx 默认 8192，活跃视图本就可能被 Ollama 静默截断（破坏不变量）。
> 现按 num_ctx 自动算 T=3096，是正确性修复。需要更大 T 的用户请显式设 `token_budget`
> 并相应调大 Ollama 的 `num_ctx`。

## Capabilities

### New Capabilities
- `model-aware-token-estimation`: LLM 插件提供模型感知的 token 计数，TokenBudget 使用 LLM 的计数器替代统一经验式

### Modified Capabilities
- `llm-interaction`: `LLMInterface` 新增 `count_tokens()` 方法和 `context_window_size` 属性
- `token-budget-traverse`: `TokenBudget` 的 counter 来源从"可选注入"变为"从 write_llm 获取"
- `phase1-defaults`: `MCSConfig.knowledge_graph()` 根据模型自动设置 T 默认值

## Impact

### 代码变更
- `mcs/interfaces/llm.py`: `LLMInterface` 新增 `count_tokens()` + `context_window_size`
- `mcs/core/token_budget.py`: 无接口变更；counter 异常兜底从旧 1:1 经验式改为 `CalibratedEstimator("unknown")` 保守校准式
- `mcs/core/calibrated_estimator.py`: **新增**，校准经验式实现
- `mcs/plugins/llm/claude_llm.py`: **不 override** `count_tokens`（走默认校准式）；`context_window_size`（映射表，移除无效的前缀匹配）
- `mcs/plugins/llm/deepseek_llm.py`: 实现 `count_tokens()`（tiktoken）+ `context_window_size`
- `mcs/plugins/llm/ollama_llm.py`: 实现 `count_tokens()`（tiktoken）+ `context_window_size`；override `_detect_model_family→"ollama"`（兜底走 ollama 族系数）
- `mcs/core/builder.py`: 调整构建顺序——先实例化 LLM → 用 write_llm.count_tokens 构造 TokenBudget
- `mcs/entities/config.py`: `knowledge_graph()` 工厂根据 LLM 自动设置 `token_budget`

### API 变更
- `LLMInterface` 新增两个非抽象方法（有默认实现），**非 breaking**
- `MCSConfig.knowledge_graph()` 的 `token_budget` 默认值可能变化（从固定 8000 变为按模型调整），但用户显式配置时不变

### 依赖
- **新增 `tiktoken`**：加入 `pyproject.toml` 的 `dependencies`（必选依赖；DeepSeek/Ollama 本地精确计数；~1MB + 词表缓存，轻量）
- `anthropic` SDK 已在 `claude` optional dependency 中，`count_tokens` 方法随 SDK 提供，无需额外依赖
- 前置：无（独立变更）

### 风险
- **Claude count_tokens API 速率限制（已规避）**：原方案以 API 作运行时 counter，查询 bounding/trim 链逐节点 `estimate_node` 会产生 O(邻域) 次调用（远超"单次 1-3 次"的初判），易触发 Tier1 100RPM 限制，且 429 降级破坏口径一致性。现运行时改用校准经验式、API 仅离线校准，此风险消除
- **tiktoken 对非 OpenAI 模型的近似误差**：DeepSeek/Qwen 的 tokenizer 与 cl100k_base 有差异，实测误差约 5-15%。对守门场景足够安全（误差方向不确定时，校准经验式兜底仍保守高估）
- **校准系数需实测验证（待办）**：上表系数为文献/经验值，尚未跑实测。`bench/calibration/calibrate_token_estimator.py` 提供校准工具（取 100 条中英混合文本对照精确计数拟合），需执行后更新系数表
- **构建顺序调整**：`builder.py` 需先实例化 LLM 再构造 TokenBudget，当前流程中 LLM 实例化在 TokenBudget 之后——需调整步骤顺序，确保不破坏插件初始化依赖链。经分析，LLM 构造只依赖 config，提前安全；`initialize(context)` 仍在原位
- **T 默认值变化**：`knowledge_graph()` 的 T 从固定 8000 变为按模型自动计算（上限 8000）。DeepSeek/Claude 仍为 8000；**Ollama 因 num_ctx=8192 降为 3096**（正确性修复，见 §6）。用户显式配置 `token_budget` 时不变
