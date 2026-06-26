## Context

`mcs_agent` 现状（见 explore 结论）：

- 构造只有 `build_agent_from_env()`（`app.py`）一条 env-bound 路径；无 config / builder / 工厂。
- LLM 只有 `make_openai_llm_call`（`llm.py`）；`llm_call(messages, tools) -> dict` callable 抽象已存在（可注入），但无后端注册表，trace 靠往 dict 偷塞 `_trace` 键。
- 工具：`MEMORY_TOOLS`（`loop.py`）硬编码 list + `_dispatch` 硬编码 if/elif；不可配置。
- 图谱：`MemoryStore(build_fn)`，`build_fn` 永远 `Phase1Builder(config).build()`；指向已有 db 无干净 API（`SQLiteStore` build 时本就加载已有数据）。

**统一 LLM（本轮决策）**：agent 的 chat LLM 与 MCS 自有的 write/read LLM（`learn`/`associate` 用）**共用一份 `LLMConfig`**（provider 键）——配一次，两侧用同一 provider/model/key。**运行时仍是两个对象**（agent 的 `AgentLLMInterface` 与 MCS 的 `LLMInterface` 插件，因 chat+tools 与抽取两接口形状不同，无法合一），但同源一份配置。`mcs_config`（完整 MCSConfig）留作逃逸口——想给 MCS 配不同 LLM 时用它（此时 agent 仍用 `llm`）。

另一约束：MCS 核心的 `LLMInterface` 是 `(system,user)->raw_str` 单次补全，**无 tool-calling**，否决"并入 MCS LLM 插件体系"。

`memory-agent` spec 现有 ~20 条 Requirement；本次 MODIFIED 2 条、ADDED 2 条，全部并入该 capability。

## Goals / Non-Goals

**Goals:**

- 构造层：`AgentConfig` + `AgentBuilder.build()->MemoryAgent` + `create_agent()` + `from_file(yaml)`，编程式与 YAML 双路径。
- 可插拔 LLM（A2）：`AgentLLMInterface` ABC + provider 键注册表，openai-compat + anthropic-native。
- **统一 LLM 配置**：一份 `LLMConfig` 喂 agent + MCS（`mcs_config` 逃逸口）。
- 工具配置（窄）：`ToolSpec` 注册表 + `ToolsetConfig`；删硬编码。
- 已有图谱：`db_path` 一等旋钮（加载已有数据白送）。
- 兼容：`build_agent_from_env` 降级为预设；`CallableAgentLLM` 适配器保 callable 注入测试零改动。

**Non-Goals:**

- 自定义工具注册（将来；registry 形状已留口）。
- 注入 / 共享 MCS 实例、并发（将来另一个 change）。
- 并入 MCS `LLMInterface`（已否决：接口不兼容）。
- agent 与 MCS 用**不同** LLM 的便捷性（要不同则走 `mcs_config` 逃逸口；默认统一）。
- 多模态 LLM（首版仅 text + tool_calls 子集）。
- 战略转型（查询统一走 agent / 弃 query 管线 / mcp agent 化 / 批量建图）——本轮不做，associate 仍走 `mcs.query`。

## Decisions

### D1：LLM 走 A2（agent 自有 `AgentLLMInterface`），不并入 MCS

MCS `LLMInterface` 无 tool-calling，并入需新增接口 + 三后端全重写。A2 代价最小。（备选 A1 纯函数工厂 rejected；B 并入 rejected。）

### D2：openai chat-completions 作内部 lingua franca

内部消息 / 工具格式用 openai chat-completions；ABC 只标准化"返回值"（`AssistantMessage`）。deepseek / ollama 原生兼容，仅 anthropic-native 需双向翻译。`MemoryAgent` 消息历史不动。

### D3：`AssistantMessage` 一等 trace

```python
@dataclass
class AssistantMessage:
    content: str
    tool_calls: list[dict]
    trace: LLMCallTrace | None        # 一等 trace，替掉 dict["_trace"] hack
```
`MemoryAgent` 从 `assistant.pop("_trace")` 改读 `msg.trace`（仅 `loop.py` 一处）。loop 再把 `AssistantMessage` 重建为 openai 格式 `{"role": "assistant", "content": content, "tool_calls": tool_calls}` 后 `append` 进 messages：`tool_calls` 保留完整结构（id / type / function），供后续 tool 消息按 id 配对、openai 多轮回放校验通过；无工具调用时省略 `tool_calls`，`content` 为 None 按协议保留 None。

### D4：后端注册表（**provider 键**，与 MCS 插件名对齐）

```python
class AgentLLMInterface(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage: ...

# provider → agent adapter（openai-compat 走 OpenAIAgentLLM，原生 claude 走 AnthropicAgentLLM）
AGENT_LLM_REGISTRY: dict[str, type[AgentLLMInterface]] = {
    "deepseek": OpenAIAgentLLM,   # base_url 默认 https://api.deepseek.com
    "ollama":   OpenAIAgentLLM,   # base_url 默认 http://localhost:11434/v1
    "claude":   AnthropicAgentLLM, # 原生；整段 history openai↔anthropic 翻译
}
# provider → MCS 插件短名（**仅**作 create_mcs(llm=...) / knowledge_graph 的 write_llm/read_llm 参数用；
# ⚠️ plugin_configs 的 key 必须是完整插件名 f"{provider}_llm"——非此短名，见 D6 警告）
PROVIDER_TO_MCS_LLM: dict[str, str] = {"deepseek": "deepseek", "ollama": "ollama", "claude": "claude"}
```
provider 键同时映射 agent adapter 与 MCS 插件——**这正是"统一"的落点**：一份 provider/model/key 配置，两侧各取所需。未知名早失败。

**统一 provider 集 = agent adapter ∩ MCS 插件 = `{deepseek, ollama, claude}`**：官方 openai 有 `OpenAIAgentLLM` 但**无 MCS 插件**（`MCSConfig.knowledge_graph` 仅认 deepseek/claude/ollama），故 openai **不作统一 provider 键**（落入"未知名早失败"）。agent 要连任意 openai 兼容端点：用 `deepseek`/`ollama` 键 + 自定义 `base_url`（MCS 侧种同一 `base_url` 同源生效）；想给 MCS 配独立 LLM 走 `mcs_config` 逃逸口。

### D5：`ToolSpec` 注册表（窄档）

```python
@dataclass
class ToolSpec:
    name: str
    schema: dict
    handler: Callable[["MemoryStore", dict], str]  # (memory, args) -> 文本（纯，不做 trace/异常）

BUILTIN_TOOLS: dict[str, ToolSpec] = {learn, search, associate, reason, recall}

@dataclass
class ToolsetConfig:
    enabled: list[str] | None = None   # None = 全部 5 个
    params: dict[str, dict] = field(default_factory=dict)  # {"reason": {"max_hops": 8}}  # key = 工具名
```
`build_toolset(...) -> (schemas_for_llm, dispatch_table)`；`MemoryAgent` 删硬编码 `MEMORY_TOOLS`/`_dispatch` if/elif。**不**做自定义工具注册。

**`params` 覆盖语义**：`build_toolset` 按 `ToolsetConfig.enabled` 过滤后，`dispatch_table[name]` 为 `(handler, params)`（`name` = **工具名**；`params = ToolsetConfig.params.get(name, {})`，故 `ToolsetConfig.params` 的 key 也是工具名、非原语名）。`MemoryAgent` 包装层调用时合并为 `handler(memory, {**llm_args, **params})`——**`params` 覆盖 LLM 同名入参**（这类参数如 `reason` 工具的 `max_hops` 多不在 LLM schema 内、属服务端默认/覆盖，LLM 通常传不到；显式同名时以 `params` 为准）。

> **trace / 异常隔离归属（🟡#3）**：`handler` 纯；现 `_dispatch` 的 timing + `try/except` + `ToolCallTrace` **保留在 `MemoryAgent`** 作包装层，调 `self.dispatch.get(name)`，缺省 → `[error] 未知工具：{name}`。

### D6：`db_path` 一等旋钮 + **统一 LLM 喂 MCS**

MCS LLM 来源（统一口径）：
1. `config.mcs_config`（完整 MCSConfig，**逃逸口**，自带 MCS LLM）优先；若同时给 `db_path`，**在 `Phase1Builder.build()` 之前**覆盖 sqlite path 得 mcs_config'，再 `build_fn = lambda: Phase1Builder(mcs_config').build()`——改晚了无效。**勿就地改 / 勿 `deepcopy`**（mcs_config 含 Callable parser 字段，deepcopy 会炸）：用 `dataclasses.replace(mcs_config, plugin_configs={**pc, "sqlite_storage": {**pc.get("sqlite_storage", {}), "path": db_path}})` 重建——不污染调用方对象、`setdefault` 语义防空 key。
2. 否则用**统一的 `config.llm`** 复用既有工厂 `create_mcs`（见 `mcs/presets/phase1.py:166`，避免重写 MCSConfig 组装）：`build_fn = lambda: create_mcs(llm=PROVIDER_TO_MCS_LLM[llm.provider], db_path=db_path, plugin_configs={f"{PROVIDER_TO_MCS_LLM[llm.provider]}_llm": seed})`，`seed = {model, api_key, base_url}`，**provider=claude 时另注入 `auth_token`**（claude_llm 自身 auth_token 优先、回退 api_key 的逻辑不变）。`create_mcs` 在 `build_fn` 内（worker 线程）调用，SQLite 线程亲和不破。

> **⚠️ plugin_configs key 易错点（曾差点漏判的 bug）**：key 必须是**完整插件名** `f"{PROVIDER_TO_MCS_LLM[llm.provider]}_llm"`（`deepseek_llm` / `claude_llm` / `ollama_llm`）——即 `create_mcs(llm=...)` 内部 `write_llm_name = f"{write_llm}_llm"`（`mcs/entities/config.py:108`）那个名字，**不是** agent provider 键 `deepseek` 本身。原因：`create_mcs` 经 `config.plugin_configs.setdefault(name, {}).update(cfg)` 合并（`mcs/presets/phase1.py:216-218`），LLM 插件按 `deepseek_llm` 注册（`config.py:115` `_add_llm_config` 以该名为 key）。**写错（如直接用 provider 键）会建出无插件认领的死 key、真正的 `deepseek_llm` 保持 `knowledge_graph` 默认空 api_key**（`config.py:311`）→ agent 构建成功但 `learn`/`associate` 运行时 401、**无构建期报错**。key 必须走 `PROVIDER_TO_MCS_LLM` **同一短名映射**（与 `create_mcs(llm=)` 一致），未来 agent provider 名与 MCS 短名分叉才不破。测试必须断言插件 config 实际收到入参（见 task 6.2）。

加载已有数据由 `SQLiteStore` build 时自动完成（**白送**）。不注入实例、agent 自管生命周期。`build()` 前置校验**两条独立判据**：① 缺 `llm`（`config.llm is None`）→ 报错"agent chat 无 LLM 后端"（与 `mcs_config` 有无**无关**——mcs_config 的 LLM 无 tool-calling、救不了 agent chat）；② 无 `mcs_config` 且无 `db_path` → 报错"无图谱来源"。见 resolve 步骤 0。

### D7：构造体系形状（**单一 `LLMConfig`**）

```python
@dataclass
class LLMConfig:                 # 统一：喂 agent adapter + MCS 插件
    provider: str                # "deepseek" | "ollama" | "claude"（openai 无 MCS 插件，不可用）
    model: str
    api_key: str = ""
    base_url: str | None = None  # None → provider 默认
    auth_token: str | None = None  # 仅 claude：Bearer 授权（claude_llm 优先于 api_key）；非 claude 忽略

@dataclass
class AgentConfig:
    llm: LLMConfig | None = None           # 统一 LLM（agent + MCS 共用）；缺则 build() 报错（见 resolve 步骤 0）
    mcs_config: MCSConfig | None = None    # 逃逸口：完整 MCS 配置（优先，自带 MCS LLM）
    db_path: str | None = None             # 存储路径（与 mcs_config 同给则覆盖其 sqlite path）
    tools: ToolsetConfig = field(default_factory=ToolsetConfig)
    max_turns: int = 8
    summary_budget: int = 1000
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    on_trace: Callable[[ChatTrace], None] | None = None  # 运行期 trace 回调（🟡#2）

class AgentBuilder:
    def __init__(self, config: AgentConfig): ...
    def build(self) -> MemoryAgent: ...   # 出 agent，不出 app

def create_agent(*, db_path=..., llm_provider=..., llm_api_key=..., llm_model=..., llm_base_url=...,
                 llm_auth_token=None, mcs_config=None, **kw) -> MemoryAgent: ...
# AgentConfig.from_file(path) -> AgentConfig  （YAML 路径）
```
`create_app(agent)` 仍独立一层。

### D8：兼容（最小改动落地）

- `build_agent_from_env()` → 薄预设：`AGENT_LLM_*` → `LLMConfig`（agent + MCS 共用）；`MCS_CONFIG` → `mcs_config`（逃逸口，MCS LLM 由 yaml 决定，覆盖统一 `llm`）。env 契约与早失败逐字保留（spec「环境变量构建生产 agent」无需改）。
- `CallableAgentLLM(AgentLLMInterface)`：包裸 callable，`chat()` 调它并把 `dict["_trace"]` 提到 `AssistantMessage.trace`；`MemoryAgent` 传 callable 自动包——既有测试零改动。
- `MEMORY_TOOLS` 保留为**已废弃别名**，后续 change 移除。
- `make_openai_llm_call` 保留为**已废弃别名**：内部 `OpenAIAgentLLM(model, api_key, base_url).chat` 包回 `llm_call(messages, tools) -> dict`（回填 `_trace` 键，保持旧 callable 形状）；`__init__.py` 仍导出。与 `MEMORY_TOOLS` 对称（防 import 断裂），后续 change 移除。

### builder.build() resolve 顺序

```
0. 前置校验（两条独立判据，任一命中即 build() 清晰报错，不再往下）：
   - config.llm is None → 报错"agent chat 无 LLM 后端"（mcs_config 的 LLM 无 tool-calling，救不了 agent chat；与 mcs_config 有无无关）
   - config.mcs_config is None and config.db_path is None → 报错"无图谱来源：需 db_path 或 mcs_config"
1. 定 build_fn（决定 MCS 来源；llm / 图谱来源已由步骤 0 保证）：
   - mcs_config 给定 → build_fn = lambda: Phase1Builder(mcs_config').build()
     # mcs_config' = dataclasses.replace 重建 plugin_configs、覆盖 sqlite path（勿就地改 / deepcopy，见 D6 第1点）
   - 否则（必有 llm）→ build_fn = lambda: create_mcs(llm=PROVIDER_TO_MCS_LLM[llm.provider], db_path=db_path,
                        plugin_configs={f"{PROVIDER_TO_MCS_LLM[llm.provider]}_llm": {model, api_key, base_url[, auth_token if claude]}})
                        # ⚠️ key = 完整插件名，走同一 PROVIDER_TO_MCS_LLM 短名映射（deepseek_llm/...），非 llm.provider——见 D6 警告
2. memory = MemoryStore(build_fn)            # build_fn 在单 worker 线程内执行，SQLite 线程亲和不破
3. llm_backend = AGENT_LLM_REGISTRY[llm.provider](llm.model, api_key=llm.api_key, base_url=llm.base_url, auth_token=llm.auth_token)
                 # llm 已由步骤 0 校验非 None；OpenAIAgentLLM 忽略 auth_token；AnthropicAgentLLM 用 auth_token/api_key
                 # callable→CallableAgentLLM 适配不在 builder（此分支 llm 恒为 LLMConfig），在 MemoryAgent.__init__（供不经 builder 的测试）
4. return MemoryAgent(memory, llm_backend, tools=config.tools, system_prompt=config.system_prompt,
                      max_turns=config.max_turns, summary_budget=config.summary_budget, on_trace=config.on_trace)
                      # MemoryAgent 内部 build_toolset(BUILTIN_TOOLS, config.tools)；tools=None → 全 5 工具
```

## Risks / Trade-offs

- **[统一 LLM 的代价]** agent 与 MCS **共用同一 provider/model/key**——失去"agent 用贵模型、MCS 抽取用便宜模型"的灵活。→ `mcs_config` 逃逸口保留（想分开设 MCS LLM 即可）；默认统一换配置简单、零漏配（自查 🔴#1 由统一彻底消除）。
- **[运行时仍两对象]** agent `AgentLLMInterface` 与 MCS `LLMInterface` 接口形状不同，不能合一（除非重启搁置的 query 管线转型）。→ 同源一份 `LLMConfig`，配置层面统一即可。
- **[`MemoryAgent` 构造签名 BREAKING]** → `CallableAgentLLM` 适配器 + 缺省全工具集，callable 注入测试与 env 路径不破。
- **[trace/异常隔离归属（🟡#3，已解）]** → `_dispatch` 包装层保留在 `MemoryAgent`。
- **[anthropic 翻译边界]** → 首版 text + tool_calls 子集，整段 history 翻译封在 adapter；多模态留 TODO。
- **[claude Bearer 授权]** claude_llm 优先 auth_token、回退 api_key → `LLMConfig.auth_token` 可选字段（仅 claude 用）；agent 侧 `AnthropicAgentLLM` 与 MCS 侧 `claude_llm` 同源种入，统一模式覆盖 Bearer 网关。
- **[provider 集收窄]** 统一 = provider 须双映射 → 可用集 `{deepseek, ollama, claude}`；openai 无 MCS 插件不可作统一键（既定代价），agent 连任意 openai 端点用 deepseek/ollama 键 + base_url。
- **[`MEMORY_TOOLS` 废弃别名残留]** → 临时一个版本，后续 change 移除。
- **[线程模型]** 不引入并发 → 无新风险。

## Migration Plan

分阶段提交，每阶段测试绿（适配器桥接）：

1. **LLM 抽象**：`AgentLLMInterface` + `OpenAIAgentLLM`（搬现逻辑）+ `CallableAgentLLM` + `AssistantMessage`；`loop.py` 改读 `msg.trace`、并把 `AssistantMessage` 重建为 openai assistant dict 后 append。
2. **工具注册表**：`ToolSpec` / `BUILTIN_TOOLS` / `ToolsetConfig` / `build_toolset`；`MemoryAgent` 接 `tools: ToolsetConfig`（内部 `build_toolset` 产 schemas/dispatch），`_dispatch` 改包装层，删硬编码 if/elif；`MEMORY_TOOLS` 降级别名。
3. **构造体系**：`LLMConfig`（统一，含可选 `auth_token`）/ `AgentConfig`（含 `on_trace`）/ `AgentBuilder`（D6 统一 LLM resolve，复用 `create_mcs` + provider→MCS 插件映射）/ `create_agent`（含 `llm_auth_token`）/ `from_file`。
4. **env 预设**：`build_agent_from_env` 改走 builder。
5. **anthropic 后端**：`AnthropicAgentLLM`（optional `anthropic`，构造接 `auth_token`/`api_key`）。
6. **收尾**：迁移 / 补测试（统一 LLM 喂两侧、mcs_config 逃逸、缺 LLM 报错、工具配置、后端选择、callable 适配、anthropic 翻译）、`__init__.py`、`docs/memory-agent.md`。

回滚：按阶段 commit，可逐段 revert。

## Open Questions

无——统一 LLM（单一 `LLMConfig`，provider 键）已落 D4/D6/D7；provider 集收窄（openai 不作统一键）与 claude Bearer（`LLMConfig.auth_token`）已定；自查 🔴#1 由统一彻底消除；战略转型按用户指示搁置。
