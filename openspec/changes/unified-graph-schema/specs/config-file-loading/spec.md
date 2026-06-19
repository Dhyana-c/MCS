# config-file-loading（delta）

> `relation_model` 删除后，preset 工厂不再接收该参数。叠加规则其余不变。

## MODIFIED Requirements

### Requirement: 从 YAML 文件加载 MCSConfig

系统 SHALL 提供 `MCSConfig.from_file(path)`，从 YAML 文件加载并返回与手写**形状一致**的 `MCSConfig`。若文件含 `preset` 键，MUST 先调用对应 preset 工厂（`knowledge_graph` / `memory_system`，传 `write_llm` / `read_llm`）铺底，再用**其余**键叠加；无 `preset` 则以 `MCSConfig()` 默认为底。有 `preset` 时 `write_llm` / `read_llm` MUST 仅作工厂参数消费、MUST NOT 再作字段二次叠加（否则把工厂产出的插件名如 `deepseek_llm` 覆盖回短名 `deepseek`）。**MUST NOT 再接收 / 叠加 `relation_model`（已删除）。** 叠加规则：标量字段覆盖；`shared_plugins` / `write_plugins` / `read_plugins` 显式给出则替换、否则保留底；`plugin_configs` 按插件名**两层深合并**；`prompt_overrides` 按 purpose 合并。既有构造路径（`create_mcs` / `Phase1Builder(config).build()`）MUST 逐字不变。

#### Scenario: preset 叠加产出等价手写

- **WHEN** YAML 含 `preset: knowledge_graph` 与若干字段覆盖
- **THEN** `from_file` 返回的 `MCSConfig` MUST 等价于"调 `MCSConfig.knowledge_graph(...)` 再手工改这些字段"的结果

#### Scenario: plugin_configs 深合并

- **WHEN** preset 为某 LLM 插件预置 `{model: ...}`，YAML 的 `plugin_configs` 为同插件给 `{api_key: ...}`
- **THEN** 合并结果 MUST 同时含 `model` 与 `api_key`（按插件名深合并）

#### Scenario: 插件列表显式替换

- **WHEN** YAML 显式给出 `read_plugins: [...]`
- **THEN** 结果的 `read_plugins` MUST 为 YAML 所列；未给出的 `*_plugins` MUST 保留 preset 的
