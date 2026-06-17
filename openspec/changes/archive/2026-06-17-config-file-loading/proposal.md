## Why

MCS 要打包给用户用、并做成 MCP server。这两个场景都需要**从文件配置 MCS**，而不是写 Python。当前现状（已核实）：

- `MCSConfig` 是 Python dataclass（[config.py](mcs/entities/config.py)）；构造走 `create_mcs(...)` 或 `Phase1Builder(config).build()`。
- 插件按**名字字符串**引用（`shared_plugins` / `write_plugins` / `read_plugins`），`plugin_configs` 已是数据；插件解析的**活实现**是 `Phase1Builder.get_plugin_class`（[phase1.py:99](mcs/presets/phase1.py:99)，现仅查写死的 `get_phase1_plugin_registry()` dict），`MCSBuilder.get_plugin_class` 是抽象方法、无默认实现。
- **无任何文件配置加载**（全仓 grep 无 yaml/from_file/load_config）。
- `prompt_overrides` 的 `parser` 是 `Callable`（[config.py:60](mcs/entities/config.py:60)）——进不了配置文件（那堵"声明式天花板"）。
- 秘密（API key）现靠用户在代码里填（`config.py` 预设里 `api_key=""`），文件化后绝不能硬编码进文件。

这是 **MCP server 的地基**：MCP = 读配置 build 出 MCS + 暴露工具。本期只做配置化加载，MCP 是下一个 change、直接踩在它上面。

经确认的选型：**YAML 格式 + import-path 字符串解析第三方插件**。

## What Changes

- **新增 `MCSConfig.from_file(path)`**：读 YAML → 若有 `preset` 键则先跑对应 preset 工厂（如 `knowledge_graph()`）铺底 → 叠加**其余**字段 → 返回与手写**形状完全一致**的 `MCSConfig`。复用已测的 preset 逻辑，不让用户手列全部 9 个插件。
- **preset 参数键不二次叠加（避免短名覆盖插件名）**：`write_llm` / `read_llm` / `relation_model` 在**有 preset 时**作 preset 工厂参数消费（短名，如 `deepseek`，工厂内部映射为插件名 `deepseek_llm`），MUST NOT 再作字段叠加回去——否则把 `deepseek_llm` 覆盖回 `deepseek`、builder 找不到 LLM 插件。**无 preset 时**这三个是 `MCSConfig` 原始字段（`write_llm` 写插件名）。注意 `knowledge_graph()` 校验 LLM ∈ {deepseek, claude, ollama}，故**用 import-path 自定义 LLM 必须走无 preset 路径**。
- **环境变量插值**：加载时把所有字符串值里的 `${VAR}` 从 `os.environ` 展开（秘密走环境、不进文件）；变量缺失 **fail-fast**（清晰报错，不静默用空值）。
- **import-path 解析（共享工具）**：`"my_pkg.mod:MyPlugin"` 经 importlib 加载。**`Phase1Builder.get_plugin_class`**（非抽象基类）改为：先查内置 dict → 查不到且形如 `module:attr` 则 import-path 解析（须 `Plugin` 子类）→ 无 `:` 的未知名仍 `None`、`:` 形解析失败则抛。同一工具用于**插件类、prompt parser、(未来) scorer**。
- **prompt_overrides 文本 + parser import-path**：`system` / `template` 文本直接进文件；`parser` 写 import-path 字符串，`from_file` 阶段解析为 `Callable` 放进 `MCSConfig.prompt_overrides`——`MCSConfig` 内存形状不变、builder 的 `_apply_prompt_overrides` 不改。
- **PyYAML 作可选依赖**（`[yaml]` extra）：`from_file` 惰性 `import yaml`，缺失给清晰报错（`pip install mcs[yaml]`）。
- **provenance 白捡**：`from_file` build 出的库，开库自动走已有出处校验（`relation_model` 对不上即拒）。

**OUT OF SCOPE（明确不做）**：

- **MCP server 本体**——下一个 change。
- **entry-points 插件发现**（pip 包自动发现）——本期只做 import-path（更低摩擦、两场景都够用）；entry-points 留后续按需。
- **配置热重载 / JSON-Schema 校验 / 多格式（JSON/TOML）**——留后续。
- **改 `MCSConfig` 内存形状 / 改 `create_mcs` 代码路径**——本期纯**新增** `from_file`，既有构造方式逐字不变。
- **`${VAR:-default}` 默认值语法**——本期只 `${VAR}`，缺失即错；默认值语法留后续。

**安全须知（写进文档）**：配置文件经 import-path 可加载任意代码 = **受信输入**，MUST NOT 接受不受信来源的配置文件。

## Capabilities

### New Capabilities

- `config-file-loading`：`MCSConfig.from_file(YAML)` —— preset 叠加、环境变量插值、import-path 解析（插件 / parser）、可选 PyYAML 依赖与惰性报错。

### Modified Capabilities

- `mcs-builder`：**`Phase1Builder.get_plugin_class`**（基类 `MCSBuilder.get_plugin_class` 仍是抽象方法、无默认实现）在内置 dict 未命中时支持 `module:attr` import-path 回退；无 `:` 的未知名仍返回 `None`、不抛异常（既有契约逐字保留），`:` 形解析失败则抛。

## Impact

- **配置** (`mcs/entities/config.py`)：新增 `from_file` classmethod + 环境变量插值 + preset 叠加 + plugin_configs 深合并。
- **import-path 工具**（新增，置于 `mcs/utils/` 或 `mcs/core/builder.py`）：`import_from_path("mod:attr")`，插件类与 parser 共用。
- **构建** (`mcs/core/builder.py`、`mcs/presets/phase1.py`)：`get_plugin_class` 内置未命中走 import-path 回退。
- **打包** (`pyproject.toml`)：新增 `[project.optional-dependencies] yaml = ["pyyaml>=6"]`。
- **文档** (`docs/`、`README.md`)：YAML 配置示例、import-path 用法、环境变量插值、受信输入安全须知。
- **测试** (`tests/`)：from_file（preset 叠加 / 字段覆盖 / plugin_configs 深合并）、环境变量插值（命中 / 缺失报错）、import-path（内置仍可 / import-path 命中 / unknown 返回 None / 解析失败报错）、parser import-path → callable、PyYAML 缺失报错（mock）、`property_graph` 基线行为不受影响（代码构造路径逐字不变）。
