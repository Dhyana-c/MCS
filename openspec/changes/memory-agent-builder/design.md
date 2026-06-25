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
`MemoryAgent` 从 `assistant.pop("_trace")` 改读 `msg.trace`（仅 `loop.py` 一处）。

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
# provider → MCS 插件短名（供 write_llm/read_llm + plugin_config）
PROVIDER_TO_MCS_LLM: dict[str, str] = {"deepseek": "deepseek", "ollama": "ollama", "claude": "claude"}
```
provider 键同时映射 agent adapter 与 MCS 插件——**这正是"统一"的落点**：一份 provider/model/key 配置，两侧各取所需。未知名早失败。

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
    params: dict[str, dict] = field(default_factory=dict)  # {"find_path": {"max_hops": 8}}
```
`build_toolset(...) -> (schemas_for_llm, dispatch_table)`；`MemoryAgent` 删硬编码 `MEMORY_TOOLS`/`_dispatch` if/elif。**不**做自定义工具注册。

> **trace / 异常隔离归属（🟡#3）**：`handler` 纯；现 `_dispatch` 的 timing + `try/except` + `ToolCallTrace` **保留在 `MemoryAgent`** 作包装层，调 `self.dispatch.get(name)`，缺省 → `[error] 未知工具：{name}`。

### D6：`db_path` 一等旋钮 + **统一 LLM 喂 MCS**

MCS LLM 来源（统一口径）：
1. `config.mcs_config`（完整 MCSConfig，**逃逸口**，自带 MCS LLM）优先；若同时给 `db_path`，覆盖其 `sqlite_storage.path`。
2. 否则用**统一的 `config.llm`** 构造 MCSConfig：`knowledge_graph(write_llm=read_llm=PROVIDER_TO_MCS_LLM[llm.provider])` + 种该插件 `{model, api_key, base_url}` + 设 `sqlite_storage.path`（`db_path`）。

加载已有数据由 `SQLiteStore` build 时自动完成（**白送**）。不注入实例、agent 自管生命周期。缺 `llm` 且无 `mcs_config` → builder 清晰报错（无 LLM，learn/associate 不可用）。

### D7：构造体系形状（**单一 `LLMConfig`**）

```python
@dataclass
class LLMConfig:                 # 统一：喂 agent adapter + MCS 插件
    provider: str                # "deepseek" | "ollama" | "claude"
    model: str
    api_key: str = ""
    base_url: str | None = None  # None → provider 默认

@dataclass
class AgentConfig:
    llm: LLMConfig                         # 统一 LLM（agent + MCS 共用）
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
                 mcs_config=None, **kw) -> MemoryAgent: ...
# AgentConfig.from_file(path) -> AgentConfig  （YAML 路径）
```
`create_app(agent)` 仍独立一层。

### D8：兼容（最小改动落地）

- `build_agent_from_env()` → 薄预设：`AGENT_LLM_*` → `LLMConfig`（agent + MCS 共用）；`MCS_CONFIG` → `mcs_config`（逃逸口，MCS LLM 由 yaml 决定，覆盖统一 `llm`）。env 契约与早失败逐字保留（spec「环境变量构建生产 agent」无需改）。
- `CallableAgentLLM(AgentLLMInterface)`：包裸 callable，`chat()` 调它并把 `dict["_trace"]` 提到 `AssistantMessage.trace`；`MemoryAgent` 传 callable 自动包——既有测试零改动。
- `MEMORY_TOOLS` 保留为**已废弃别名**，后续 change 移除。

### builder.build() resolve 顺序

```
1. resolve MCSConfig：mcs_config 优先（db_path 覆盖其 sqlite path）；否则用统一 llm 构造
   （write_llm=read_llm=PROVIDER_TO_MCS_LLM[llm.provider] + 种插件凭证 + sqlite path）；缺 llm 且无 mcs_config 报错
2. memory = MemoryStore(lambda: Phase1Builder(mcs_config).build())
3. llm_backend = CallableAgentLLM(callable) if isinstance(callable) else AGENT_LLM_REGISTRY[llm.provider](model, api_key, base_url)
4. (schemas, dispatch) = build_toolset(BUILTIN_TOOLS, config.tools)
5. return MemoryAgent(memory, llm_backend, schemas, dispatch, max_turns, summary_budget, system_prompt, config.on_trace)
```

## Risks / Trade-offs

- **[统一 LLM 的代价]** agent 与 MCS **共用同一 provider/model/key**——失去"agent 用贵模型、MCS 抽取用便宜模型"的灵活。→ `mcs_config` 逃逸口保留（想分开设 MCS LLM 即可）；默认统一换配置简单、零漏配（自查 🔴#1 由统一彻底消除）。
- **[运行时仍两对象]** agent `AgentLLMInterface` 与 MCS `LLMInterface` 接口形状不同，不能合一（除非重启搁置的 query 管线转型）。→ 同源一份 `LLMConfig`，配置层面统一即可。
- **[`MemoryAgent` 构造签名 BREAKING]** → `CallableAgentLLM` 适配器 + 缺省全工具集，callable 注入测试与 env 路径不破。
- **[trace/异常隔离归属（🟡#3，已解）]** → `_dispatch` 包装层保留在 `MemoryAgent`。
- **[anthropic 翻译边界]** → 首版 text + tool_calls 子集，整段 history 翻译封在 adapter；多模态留 TODO。
- **[`MEMORY_TOOLS` 废弃别名残留]** → 临时一个版本，后续 change 移除。
- **[线程模型]** 不引入并发 → 无新风险。

## Migration Plan

分阶段提交，每阶段测试绿（适配器桥接）：

1. **LLM 抽象**：`AgentLLMInterface` + `OpenAIAgentLLM`（搬现逻辑）+ `CallableAgentLLM` + `AssistantMessage`；`loop.py` 改读 `msg.trace`。
2. **工具注册表**：`ToolSpec` / `BUILTIN_TOOLS` / `ToolsetConfig` / `build_toolset`；`MemoryAgent` 接 `(schemas, dispatch)`，`_dispatch` 改包装层，删硬编码 if/elif；`MEMORY_TOOLS` 降级别名。
3. **构造体系**：`LLMConfig`（统一）/ `AgentConfig`（含 `on_trace`）/ `AgentBuilder`（D6 统一 LLM resolve + provider→MCS 插件映射）/ `create_agent` / `from_file`。
4. **env 预设**：`build_agent_from_env` 改走 builder。
5. **anthropic 后端**：`AnthropicAgentLLM`（optional `anthropic`）。
6. **收尾**：迁移 / 补测试（统一 LLM 喂两侧、mcs_config 逃逸、缺 LLM 报错、工具配置、后端选择、callable 适配、anthropic 翻译）、`__init__.py`、`docs/memory-agent.md`。

回滚：按阶段 commit，可逐段 revert。

## Open Questions

无——统一 LLM（单一 `LLMConfig`，provider 键）已落 D4/D6/D7；自查 🔴#1 由统一彻底消除；战略转型按用户指示搁置。
