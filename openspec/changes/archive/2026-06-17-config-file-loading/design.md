## Context

MCS 要打包 / 做 MCP，需从文件配置而非写 Python。现状：`MCSConfig` 是 dataclass；构造走 `create_mcs` / `Phase1Builder(config).build()`；插件按名引用、`get_plugin_class` 单一解析点（只查写死 dict）；无文件加载；`prompt_overrides.parser` 是 `Callable`（进不了文件）；秘密靠代码填。

选型已定：**YAML + import-path**。本变更是 MCP 的地基，本身不含 MCP。关键约束：**既有代码构造路径逐字不变**——`from_file` 是纯新增，产出与手写一致的 `MCSConfig`。

关键模块：`MCSConfig`（`entities/config.py`）、`MCSBuilder.get_plugin_class`（`core/builder.py`）、`Phase1Builder`（`presets/phase1.py`）、新增 import-path 工具、`pyproject.toml`。

## Goals / Non-Goals

**Goals**
- `MCSConfig.from_file(yaml)` 产出与手写一致的 `MCSConfig`，复用 preset 铺底 + 字段叠加。
- 秘密走环境变量插值（`${VAR}`），缺失 fail-fast。
- 配置可引用内置之外的插件 / parser（import-path），统一一个解析机制。
- PyYAML 可选依赖、惰性报错；纯 Python 用户零负担。

**Non-Goals（本期不做）**
- MCP server；entry-points 发现；热重载 / schema 校验；JSON/TOML；`${VAR:-default}`。
- 改 `MCSConfig` 内存形状 / 改 `create_mcs`。

## Decisions

### D1：YAML 复用 preset 铺底 + 字段叠加（非 raw 全字段）

- `from_file` 算法：解析 YAML → 环境变量插值 → 若有 `preset` 键则调对应工厂（`knowledge_graph` / `memory_system`，传 `write_llm` / `read_llm` / `relation_model`）得 base，否则 base = `MCSConfig()` → 用**其余**（除 preset 参数键外的）YAML 键叠加 base → 返回。
- **preset 参数键不二次叠加（关键陷阱）**：有 `preset` 时 `write_llm` / `read_llm` / `relation_model` 仅作工厂参数消费（短名 `deepseek`，工厂产出插件名 `deepseek_llm`），MUST NOT 再当字段叠加——否则把 `deepseek_llm` 覆盖回短名、builder 找不到 LLM 插件。无 `preset` 时这三个是原始字段（写插件名）。
- **preset 与自定义 LLM 的冲突**：`knowledge_graph()` 校验 `write_llm` ∈ {deepseek, claude, ollama}（[config.py:98](mcs/entities/config.py:98)），未知名 raise。故**用 import-path 自定义 LLM 必须走无 `preset` 路径**（raw 字段，`write_llm` 写 import-path 名 + 在 plugin 列表登记），spec 与文档须写明。
- 叠加规则：标量字段（`token_budget` 等）覆盖；`shared_plugins` / `write_plugins` / `read_plugins` 若显式给出则**替换**（用户明确意图）、否则留 preset 的；`plugin_configs` 按插件名**两层深合并**（外层按插件名、内层合并该插件 dict 的键，使 preset 的 `model` 与文件的 `api_key` 共存）；`prompt_overrides` 按 purpose 合并。
- **备选**：raw 全字段 YAML（无 preset）。**否决**——逼用户手列全部 9 个插件 + LLM 插件名 + 默认 plugin_configs，啰嗦且与 preset 逻辑重复、易漂移。preset 叠加复用已测代码。

### D2：环境变量插值，缺失 fail-fast

- 加载后、构造 config 前，递归把所有字符串叶子里的 `${VAR}` 用 `os.environ` 展开；`VAR`（`[A-Za-z_][A-Za-z0-9_]*`）不在环境 → 抛清晰错误（列出缺哪个）。
- 仅 `${VAR}` 被展开；框架 prompt 模板用单花括号 `{material}` 风格、不受影响（`${` 是 env 专用）。**本期无 `$` 转义、无 `${VAR:-default}`**——配置值 MUST NOT 含需字面保留的 `${...}`；转义 / 默认值语法留后续，文档须注明此限制。
- **备选**：缺失静默留空 / 空串。**否决**——会用空 `api_key` 跑起来、运行期才炸、难排查；秘密类配置 fail-fast 才安全。

### D3：import-path 解析（共享工具）+ get_plugin_class 回退

- 新增 `import_from_path("module:attr")`：`importlib.import_module(module)` + `getattr(attr)`；格式非法 / 模块或属性不存在 → 抛清晰错误。
- **`Phase1Builder.get_plugin_class(name)`**（基类 `MCSBuilder.get_plugin_class` 仍是 `@abstractmethod`、无默认实现，回退落在唯一活实现 `Phase1Builder` 上）：内置 dict 命中 → 返回；未命中且 name 含 `":"` → `import_from_path`（须 `Plugin` 子类）；否则 `None`（"未知名跳过、不抛异常"逐字保留——注意：**`":"` 形且解析失败是用户配置错误、SHALL 抛**，与"无 `:` 的未知名静默 None"区分）。
- 同一 `import_from_path` 用于插件类与 prompt parser（及未来 scorer）。
- **备选**：本期就上 entry-points 发现。**否决**——entry-points 要求插件是正规安装包、更重；import-path 零打包仪式、库 / MCP 两场景都够用；entry-points 留后续按需叠加（同一 `get_plugin_class` 再加一层）。

### D4：prompt parser 在 from_file 阶段解析为 Callable

- YAML 里 `prompt_overrides.<purpose>.parser` 是 import-path 字符串；`from_file` 用 `import_from_path` 解析为 `Callable` 放进 `MCSConfig.prompt_overrides`。
- 这样 `MCSConfig` 内存形状（parser 是 Callable）与 builder 的 `_apply_prompt_overrides` **均不变**——文件层做字符串→callable 的转换，下游零改动。
- **备选**：把字符串塞进 config、builder 里再解析。**否决**——把文件细节泄漏进 builder，更绕；from_file 一处转换最干净。

### D5：PyYAML 可选依赖 + 惰性 import

- `pyproject.toml` 加 `[project.optional-dependencies] yaml = ["pyyaml>=6"]`；`from_file` 内惰性 `import yaml`，`ImportError` 时报 `pip install mcs[yaml]`。
- **备选**：PyYAML 设为核心依赖。**否决**——把 MCS 当依赖库、用 Python 配置的用户不需要 YAML；保持核心依赖精简。

### D6：配置文件是受信输入（不做沙箱）

- import-path 能加载任意代码，文档 SHALL 声明"配置文件 = 受信输入，勿接受陌生来源"。
- **备选**：沙箱 / 白名单模块。**否决**——配置本就由运维 / 开发者编写，沙箱过度工程且挡正常用法；声明边界即可。
