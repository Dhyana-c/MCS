## ADDED Requirements

### Requirement: 从 YAML 文件加载 MCSConfig

系统 SHALL 提供 `MCSConfig.from_file(path)`，从 YAML 文件加载并返回与手写**形状一致**的 `MCSConfig`。若文件含 `preset` 键，MUST 先调用对应 preset 工厂（`knowledge_graph` / `memory_system`，传 `write_llm` / `read_llm` / `relation_model`）铺底，再用**其余**键叠加；无 `preset` 则以 `MCSConfig()` 默认为底。有 `preset` 时 `write_llm` / `read_llm` / `relation_model` MUST 仅作工厂参数消费、MUST NOT 再作字段二次叠加（否则把工厂产出的插件名如 `deepseek_llm` 覆盖回短名 `deepseek`，导致 builder 找不到 LLM 插件）。叠加规则：标量字段覆盖；`shared_plugins` / `write_plugins` / `read_plugins` 显式给出则替换、否则保留底；`plugin_configs` 按插件名**两层深合并**（preset 的 `model` 与文件的 `api_key` 共存）；`prompt_overrides` 按 purpose 合并。既有代码构造路径（`create_mcs` / `Phase1Builder(config).build()`）MUST 逐字不变——`from_file` 为纯新增。

#### Scenario: preset 叠加产出等价手写

- **WHEN** YAML 含 `preset: knowledge_graph` 与若干字段覆盖
- **THEN** `from_file` 返回的 `MCSConfig` MUST 等价于"调 `MCSConfig.knowledge_graph(...)` 再手工改这些字段"的结果

#### Scenario: plugin_configs 深合并

- **WHEN** preset 为某 LLM 插件预置 `{model: ...}`，YAML 的 `plugin_configs` 为同插件给 `{api_key: ...}`
- **THEN** 合并结果 MUST 同时含 `model` 与 `api_key`（按插件名深合并，非整体替换）

#### Scenario: 插件列表显式替换

- **WHEN** YAML 显式给出 `read_plugins: [...]`
- **THEN** 结果的 `read_plugins` MUST 为 YAML 所列；未给出的 `*_plugins` MUST 保留 preset 的

---

### Requirement: 配置环境变量插值

`from_file` SHALL 在构造 `MCSConfig` 前，递归地把所有字符串值里的 `${VAR}`（`VAR` 匹配 `[A-Za-z_][A-Za-z0-9_]*`）用 `os.environ` 展开。变量缺失 MUST 抛清晰错误并指出缺哪个变量，MUST NOT 静默以空值代入。仅 `${VAR}` 形被展开；单花括号 `{...}`（框架 prompt 模板风格）MUST 不受影响。

#### Scenario: 命中环境变量展开

- **WHEN** YAML 含 `api_key: "${DEEPSEEK_API_KEY}"` 且环境已设该变量
- **THEN** 加载后该值 MUST 为环境变量的实际内容

#### Scenario: 缺失变量 fail-fast

- **WHEN** YAML 引用 `${MISSING_VAR}` 而环境未设
- **THEN** `from_file` MUST 抛错且错误信息含 `MISSING_VAR`；MUST NOT 用空串代入

#### Scenario: 单花括号不受影响

- **WHEN** prompt 模板文本含 `{material}` 等单花括号占位
- **THEN** 环境插值 MUST 原样保留它（不视为变量）

---

### Requirement: import-path 解析插件与可调用

系统 SHALL 提供 `import_from_path("module:attr")`，经 importlib 加载模块并取属性。配置中引用内置注册表之外的插件 / parser 时以此解析。格式非法、模块不存在或属性不存在 MUST 抛清晰错误（含原始 path）。

#### Scenario: 解析外部对象

- **WHEN** `import_from_path("my_pkg.exts:MyEdgeExt")` 且该类存在
- **THEN** MUST 返回该类对象

#### Scenario: 解析失败报错

- **WHEN** path 形如 `module:attr` 但模块或属性不存在
- **THEN** MUST 抛错且含原始 path；MUST NOT 静默返回 None

---

### Requirement: prompt parser 经 import-path 解析为 Callable

`from_file` SHALL 把 `prompt_overrides.<purpose>.parser` 的 import-path 字符串解析为 `Callable` 放进 `MCSConfig.prompt_overrides`；`system` / `template` 保持文本。`MCSConfig` 内存形状（`parser` 为 `Callable`）与 builder 的 `_apply_prompt_overrides` MUST 不变。

#### Scenario: parser 字符串转 Callable

- **WHEN** YAML 的某 purpose 下 `parser: "my_pkg.prompts:my_parse"`
- **THEN** 加载后 `config.prompt_overrides[purpose]["parser"]` MUST 是可调用对象；`system` / `template` MUST 保持原文本

#### Scenario: 省略 parser 用默认

- **WHEN** 某 prompt_overrides 只给 `system` / `template`、不给 `parser`
- **THEN** 加载 MUST 成功；该 purpose 的解析回退到默认（与现有 `register_prompt` 语义一致）

---

### Requirement: PyYAML 为可选依赖、缺失惰性报错

YAML 加载所需的 PyYAML SHALL 为可选依赖（`[yaml]` extra），核心库 MUST NOT 强制依赖它。`from_file` MUST 惰性 import；PyYAML 缺失时 MUST 抛含安装指引（`pip install mcs[yaml]`）的清晰错误。

#### Scenario: 缺 PyYAML 给安装指引

- **WHEN** 未安装 PyYAML 时调用 `MCSConfig.from_file(...)`
- **THEN** MUST 抛错且提示安装 `mcs[yaml]`；MUST NOT 是裸 `ModuleNotFoundError` 无指引
