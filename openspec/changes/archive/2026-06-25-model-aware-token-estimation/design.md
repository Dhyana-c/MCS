# model-aware-token-estimation 设计文档

## 背景与约束

### 当前状况

`TokenBudget.estimate()` 使用统一字符经验式（CJK ≈ 1 字符/token、非 CJK ≈ 4 字符/token）。该经验式对 DeepSeek/Qwen 中文场景尚可（略高估），但对 Claude/GPT 中文场景严重低估（50-100%），直接威胁核心不变量。

`TokenBudget` 已预留 `counter: Callable[[str], int] | None` 注入点（`token_budget.py:34`），但当前无任何代码注入真实 tokenizer。

### 约束

1. **铁律一**：估算口径 == 渲染口径——估算必须与 `context_renderer` 实际渲染逐字一致
2. **核心不变量**：任意节点的活跃双向视图 ≤ T——低估 token 数会直接破坏此不变量
3. **TokenBudget 接口不可 breaking**：已有大量代码依赖 `estimate()` / `estimate_node()` / `estimate_active_view()`
4. **构建顺序**：`builder.py` 的 14 步流程有隐式依赖链，不可随意调换

## 目标

1. `TokenBudget` 使用模型感知的 token 计数，替代统一字符经验式
2. 估算精度：对中文场景误差 <15%（当前 50-100%）
3. 估算方向：宁可高估（保守）不可低估（破坏不变量）
4. `MCSConfig.knowledge_graph()` 根据模型自动建议合理的 T 默认值
5. 零 breaking API 变更

## 非目标

1. 不追求 100% 精确——Claude API 本身也返回估算值（"should be considered an estimate"）
2. 不实现运行时动态切换 tokenizer——TokenBudget 在构造时绑定一次
3. 不实现 per-purpose 不同的 token 计数策略——全局统一 counter
4. 不实现缓存层——`TokenBudget.estimate()` 已有节点级缓存（`estimate_node` 的 cache 参数），文本级缓存不在本 scope

## 决策

### D1：TokenBudget 使用 write_llm 的 counter

**选择**：使用 write_llm 的 `count_tokens` 作为 `TokenBudget` 的 counter。

**理由**：
- 写入侧的守门是核心不变量的主要守护者——改图操作后检查邻域是否超 T
- 读路径的 token 估算同样需要准确，但读路径的安全阀（max_rounds / max_accumulated_nodes）更丰富
- 全局统一口径避免同一图在不同路径下对"是否超 T"判断不一致

**替代方案**：
- ❌ **分离双 counter**：TokenBudget 分别用 write_llm 和 read_llm 的 counter。更精确但需要改 TokenBudget 接口（breaking），且增加复杂度——守门检查需要知道当前是写路径还是读路径来选 counter
- ❌ **用保守者**：取两者中更高估的计数。保证安全但可能过度触发裂变，且语义不明确

### D2：tiktoken 作为必选依赖

**选择**：tiktoken 加入 `pyproject.toml` 的 `dependencies`。

**理由**：
- DeepSeek/Ollama 依赖 tiktoken 做本地精确计数，是核心功能不是锦上添花
- 包体积 ~1MB + 词表缓存，轻量
- 消除运行时 "tiktoken 未安装" 的分支，简化代码和测试

**替代方案**：
- ❌ **可选依赖**：tiktoken 加入 `pip install mcs[tiktoken]`。运行时按需导入。增加了代码复杂度（每处都需要 try/except），且用户容易遗漏安装
- ❌ **不用 tiktoken**：DeepSeek/Ollama 直接用校准经验式。避免依赖但精度不够——校准经验式本身就是本 change 要淘汰的方案

### D3：context_window_size 使用插件内映射表

**选择**：各 LLM 插件内部维护模型名→窗口大小的映射表，未知模型回退默认值。

**理由**：
- 窗口大小是模型固有属性，跟随模型名配置最自然
- 映射表简单可靠，无需额外配置项
- 已知模型数量有限（<20），映射表维护成本低

**替代方案**：
- ❌ **配置项**：用户在 plugin_configs 中指定 context_window_size。灵活但增加配置复杂度，且用户通常不知道该填什么值
- ❌ **API 查询**：运行时查询模型信息。Claude/DeepSeek 无此端点，Ollama 有但增加网络延迟

**映射表设计**：

```python
# ClaudeLLMPlugin 内
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-3-5-sonnet-latest": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-opus-latest": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # ... 更多模型
}
_DEFAULT_CONTEXT_WINDOW = 200_000  # Claude 族默认

# DeepSeekLLMPlugin 内
_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
}
_DEFAULT_CONTEXT_WINDOW = 128_000

# OllamaLLMPlugin 内
_CONTEXT_WINDOWS: dict[str, int] = {
    # Ollama 模型名由用户自定义，无法穷举
}
_DEFAULT_CONTEXT_WINDOW = 8_192  # Ollama 默认 num_ctx
```

**匹配策略**：精确匹配 `_CONTEXT_WINDOWS`；无匹配则回退 `_DEFAULT_CONTEXT_WINDOW`。不做前缀匹配——Claude 3.x 全族窗口均为 200000、默认值也是 200000，前缀匹配恒等于默认值、纯属无效复杂度，故省略（Ollama 则以配置的 `num_ctx` 作回退）。

### D4：构建顺序调整方案

**选择**：将 LLM 插件注册提前到 TokenBudget 构造之前，LLM 的 `initialize(context)` 仍留在原位。

**当前顺序**（`builder.py`）：
1. 实例化 Store
2. 实例化 TokenBudget ← 需要 counter
3. 实例化双 PluginManager
4. 注册插件（获取 write_llm / read_llm）← counter 在这里
5. 初始化 SQLiteStore
6. 创建 ContextRenderer
7. 构建 PluginContext + 初始化插件 ← LLM.initialize() 在这里
8-14. 其余步骤

**调整后**：
1. 实例化 Store
2. 实例化双 PluginManager
3. 注册插件（获取 write_llm / read_llm）
4. **用 write_llm.count_tokens 构造 TokenBudget**
5. 初始化 SQLiteStore
6. 创建 ContextRenderer
7. 构建 PluginContext + 初始化插件
8-14. 其余步骤

**依赖分析**：
- `LLM.__init__(config)` 只需要 `config`（构造时传入），不依赖 Store / TokenBudget / ContextRenderer ✅
- `LLM.count_tokens()` 只依赖 `self.model` 和 tiktoken/anthropic SDK，不依赖 ContextRenderer ✅
- `LLM.initialize(context)` 需要 ContextRenderer（调用 `attach_renderer`）——仍在 step 7 ✅
- `_register_plugins()` 不依赖 TokenBudget ✅

**风险**：`_register_plugins()` 内部会实例化所有插件（不只是 LLM），部分非 LLM 插件的 `__init__` 可能隐式依赖 TokenBudget——但当前代码中所有插件的 `__init__` 只接受 `config`，无此依赖 ✅

### D5：Claude 运行时用校准经验式，API 仅离线校准

**选择**：ClaudeLLMPlugin 运行时不 override `count_tokens`，走 `LLMInterface` 默认实现（`CalibratedEstimator` claude 族 ×1.7/÷3）。Anthropic count_tokens API 仅用于 `bench/calibration` 离线校准，不作运行时 counter。

**理由**（推翻"API 作首选 counter"的初版方案）：
- **频率**：API 作为 TokenBudget 全域 counter 时，查询 bounding/trim 链逐节点 `estimate_node` 产生 O(邻域) 次同步网络调用——单次 `get_subgraph` 即可能数十至数百次，触及 Tier1 100RPM 限制（初版"单次 ingest 1-3 次"的频率判断低估了 bounding 路径）。
- **口径一致性（致命）**：API 成功返回 API 值，429/网络失败降级到 ×1.7 校准式——同一文本在不同调用返回不同值，单次 bounding 循环内 API 值与降级值混算，破坏铁律一"口径一致性"。初版以"API 对同一文本始终返回相同值，满足口径一致性"为论证前提——该前提被自己的降级机制推翻。
- **守门本体无此问题**：`fanout_reducer._neighborhood_tokens`（注入 renderer 时）把邻域拼成单一渲染串、只调 1 次 estimate；但 bounding/trim/seed/dedup 是逐节点路径，用本地校准式才能零网络且口径一致。
- 校准式虽精度略低于 API（×1.7 vs <5%），但确定性、本地、保守高估（不破坏不变量）。

**API 的去向**：`bench/calibration/calibrate_token_estimator.py` 直接调 `Anthropic.messages.count_tokens` 作离线定标 oracle（不经 plugin.count_tokens），用于给 claude 族系数实测校准；plugin 运行时不依赖 API。

### D6：T 默认值策略

**选择**：`knowledge_graph()` 根据模型自动计算 T 默认值，但设上限为 8000（Phase 1 保守值）。

**理由**：
- 自动计算值可能非常大（如 Claude 的 ~99000），但 Phase 1 的守门/聚类算法未在此规模下测试
- 保守上限 8000 确保现有行为不变，同时为 Phase 2 留出上调空间
- 用户可显式设更大的 T 来利用更大的上下文窗口

**计算公式**：`T = min(8000, (context_window_size - 2000) // 2)`

**替代方案**：
- ❌ **不设上限**：T 直接用计算值。风险——Phase 1 守门/聚类在超大 T 下可能产生意外行为
- ❌ **保持固定 8000**：不自动计算。简单但浪费大窗口模型的能力
- ❌ **设上限为 16000**：比 8000 更积极但仍保守。可考虑，但 Phase 1 先用 8000 安全落地

## 校准方法论

### 经验式系数校准

校准经验式的系数当前为文献/经验值（尚未实测，见 §实现细节 CalibratedEstimator 注释）。以下为待执行的校准方法：

1. **样本集**：100 条中英混合文本（50 条纯中文、30 条中英混合、20 条纯英文），覆盖不同长度（50-2000 字符）
2. **基准**：对每条文本，用对应模型的精确计数（API / tiktoken）得到真实 token 数
3. **校准**：用最小二乘法拟合 CJK 系数和非 CJK 系数，使经验式估计值 ≥ 真实值的 95% 分位（保守高估）
4. **验收**：经验式估计值 ≥ 真实值的比例 ≥ 95%（允许 5% 低估，但低估幅度 <10%）

### 校准代码位置

校准脚本放在 `bench/calibration/` 目录下，不在主代码中。运行命令：

```bash
python -m bench.calibration.calibrate_token_estimator --model claude-3-5-sonnet-latest --samples 100
```

### 校准结果更新

校准完成后，更新 `CalibratedEstimator` 的系数表。校准是**一次性工作**，不需要在运行时执行。

## 实现细节

### CalibratedEstimator 设计

```python
class CalibratedEstimator:
    """校准经验式 token 估算器——精确方案的兜底。"""

    # 模型族 → (CJK 系数, 非CJK 字符/token)
    COEFFICIENTS: dict[str, tuple[float, int]] = {
        "claude":    (1.7, 3),
        "gpt":       (1.7, 3),
        "deepseek":  (1.3, 4),
        "ollama":    (1.3, 4),
        "unknown":   (1.7, 3),  # 保守
    }

    def __init__(self, model_family: str = "unknown"):
        cjk_coeff, non_cjk_divisor = self.COEFFICIENTS.get(
            model_family, self.COEFFICIENTS["unknown"]
        )
        self._cjk_coeff = cjk_coeff
        self._non_cjk_divisor = non_cjk_divisor

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        non_cjk = len(text) - cjk
        return max(1, int(cjk * self._cjk_coeff + non_cjk // self._non_cjk_divisor))
```

### LLMInterface.count_tokens 默认实现

```python
class LLMInterface(Plugin):
    # ...

    def count_tokens(self, text: str) -> int:
        """估算 text 的 token 数量。

        默认实现使用 CalibratedEstimator（按模型族调整系数）。
        子类应覆盖为精确计数（API 端点或 tiktoken）。
        """
        if not hasattr(self, "_calibrated_estimator"):
            from mcs.core.calibrated_estimator import CalibratedEstimator
            family = self._detect_model_family()
            self._calibrated_estimator = CalibratedEstimator(family)
        return self._calibrated_estimator.estimate(text)

    def _detect_model_family(self) -> str:
        """从 self.model 推断模型族（用于校准经验式系数选择）。"""
        model = getattr(self, "model", "").lower()
        if "claude" in model:
            return "claude"
        if "gpt" in model:
            return "gpt"
        if "deepseek" in model:
            return "deepseek"
        return "unknown"

    @property
    def context_window_size(self) -> int:
        """返回模型上下文窗口 token 数。

        默认实现返回 16000（保守值）。
        子类应覆盖为已知模型的实际窗口大小。
        """
        return 16_000
```

### ClaudeLLMPlugin.count_tokens 实现（不 override）

ClaudeLLMPlugin 运行时不 override `count_tokens`，继承 `LLMInterface` 默认实现（`CalibratedEstimator` via `_detect_model_family→"claude"`）。API 仅离线校准用（见 D5），故运行时无 override 代码。

```python
# ClaudeLLMPlugin 不定义 count_tokens —— 继承 LLMInterface 默认实现：
#   def count_tokens(self, text):
#       ... CalibratedEstimator(self._detect_model_family()).estimate(text)
# _detect_model_family 对含 "claude" 的 model 名返回 "claude" → ×1.7/÷3
```

### DeepSeekLLMPlugin.count_tokens 实现

```python
def count_tokens(self, text: str) -> int:
    """使用 tiktoken cl100k_base 计数，失败时降级到校准经验式。"""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        pass  # tiktoken 不可用 → 降级
    return super().count_tokens(text)
```

### OllamaLLMPlugin.count_tokens 实现

与 DeepSeekLLMPlugin 相同，使用 tiktoken cl100k_base。

### builder.py 调整

```python
def build(self) -> "MCS":
    # 1. 实例化 Store
    store = self._init_store()

    # 2. 实例化双 PluginManager
    write_manager = PluginManager()
    read_manager = PluginManager()

    # 3. 按配置实例化并注册插件（获取 write_llm / read_llm）
    write_llm, read_llm = self._register_plugins(write_manager, read_manager)

    # 4. 用 write_llm.count_tokens 构造 TokenBudget
    token_budget = TokenBudget(
        self.config.token_budget,
        counter=write_llm.count_tokens,
    )

    # 5-14. 其余步骤不变
    # ...
```

### config.py 调整

`knowledge_graph()` 工厂方法需要知道 LLM 的 `context_window_size` 来自动设置 T。但工厂方法返回 `MCSConfig`，不构建 LLM 实例——因此使用**静态映射**（与插件内映射表保持同步）：

```python
# 在 config.py 中
_LLM_CONTEXT_WINDOWS: dict[str, int] = {
    "deepseek": 128_000,
    "claude": 200_000,
    "ollama": 8_192,
}

@classmethod
def knowledge_graph(cls, write_llm="deepseek", read_llm=None) -> MCSConfig:
    # ...
    # 根据模型自动计算 T 默认值（保守上限 8000）
    window = _LLM_CONTEXT_WINDOWS.get(write_llm, 16_000)
    auto_T = min(8000, (window - 2000) // 2)
    # auto_T 当前总是 8000（所有模型的窗口都远大于 8000）
    # 但为未来 Phase 2 放宽 T 上限留出空间
    return cls(
        token_budget=auto_T,
        # ...
    )
```

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|:----:|:----:|------|
| Claude count_tokens API 速率限制 / 口径割裂 | 已规避 | — | 运行时不用 API 作 counter（改校准式），API 仅离线校准（见 D5） |
| tiktoken 对 DeepSeek/Qwen 近似误差 5-15% | 确定 | 低 | cl100k_base 对中文相对 DeepSeek/Qwen 实际 tokenizer 偏保守高估，方向安全 |
| 构建顺序调整破坏隐式依赖 | 低 | 高 | 逐步骤验证，全量测试绿 |
| Ollama T 默认值 8000→3096 | 确定 | 低 | 正确性修复（旧 T+R>num_ctx 不安全）；用户可显式覆盖 + 调 num_ctx |
| tiktoken 安装失败 / 离线首跑下载词表 | 低 | 中 | 必选依赖 + CI 验证；失败降级校准式（安全高估） |
