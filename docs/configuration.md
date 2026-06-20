# 配置文件（YAML）

> 把 MCS 从 **YAML 文件**配置，而不是写 Python。`MCSConfig.from_file(path)` 读 YAML →
> （可选）preset 铺底 → 字段叠加 → 返回与手写**形状一致**的 `MCSConfig`。
> 需可选依赖：`pip install -e ".[yaml]"`（PyYAML）。

```python
from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder

config = MCSConfig.from_file("mcs.yaml")
mcs = Phase1Builder(config).build()
```

> 配置文件是**受信输入**：YAML 经 import-path 可加载任意第三方代码（插件 / parser）。
> **MUST NOT** 接受陌生 / 不受信来源的配置文件（详见末尾「安全须知」）。

## 最小示例：preset 铺底

`preset: knowledge_graph` 复用默认 Phase1 插件集 + LLM 配置，只覆盖你要改的字段
（不必手列全部 9 个插件）：

```yaml
preset: knowledge_graph

# preset 工厂参数（短名：deepseek / claude / ollama）；工厂内部映射为插件名（如 deepseek_llm）
write_llm: deepseek
read_llm: deepseek

# 秘密走环境变量插值（${VAR}），不进文件
plugin_configs:
  deepseek_llm:
    api_key: ${DEEPSEEK_API_KEY}
  sqlite_storage:
    path: mcs.db

# 标量字段直接覆盖
token_budget: 8000
max_rounds: 5
```

> **陷阱一（preset 参数键不二次叠加）**：有 `preset` 时 `write_llm` / `read_llm`
> **仅作工厂参数消费**。工厂产出插件名（如 `deepseek_llm`），文件里写的
> 短名（`deepseek`）**不会**再覆盖回去——否则 builder 找不到名为 `deepseek` 的 LLM 插件。
> 故此处写 `deepseek` 是给工厂的短名，最终 `config.write_llm == "deepseek_llm"`。

## 字段叠加规则

| 字段类型 | 规则 |
|---------|------|
| 标量（`token_budget` / `max_rounds` / `max_accumulated_nodes` / `auto_persist` / `mode`） | 直接覆盖 |
| `shared_plugins` / `write_plugins` / `read_plugins` | **显式给出则替换**；未给出则保留 preset 的 |
| `plugin_configs` | 按插件名**两层深合并**（preset 的 `model` 与文件的 `api_key` 共存，非整体替换） |
| `prompt_overrides` | 按 purpose 合并；`parser` 为 import-path 串时解析为 `Callable` |
| `write_llm` / `read_llm` | 有 preset 时已被工厂消费、不再叠加；**无 preset** 时是原始字段 |

### plugin_configs 深合并示例

```yaml
preset: knowledge_graph          # 预置 deepseek_llm: {api_key: "", model: "deepseek-chat"}
plugin_configs:
  deepseek_llm:
    api_key: ${DEEPSEEK_API_KEY} # 只补 api_key；preset 的 model 被保留
```

合并后 `deepseek_llm = {api_key: <env>, model: "deepseek-chat"}`。

### 插件列表替换示例

```yaml
preset: knowledge_graph
read_plugins:                     # 显式给出 → 整体替换 preset 的 read 链
  - alias_index
  - alias_entry
# shared_plugins / write_plugins 未写 → 保留 preset 的
```

## 环境变量插值

加载时，所有字符串值里的 `${VAR}`（`VAR` 匹配 `[A-Za-z_]\w*`）会从 `os.environ` 展开。
**缺失变量 fail-fast**（报错并指出缺哪个变量，不会静默用空值代入）。秘密走环境、不进文件：

```yaml
plugin_configs:
  deepseek_llm:
    api_key: ${DEEPSEEK_API_KEY}
```

- 仅 `${VAR}` 形被展开；prompt 模板的单花括号 `{material}` **不受影响**（`${` 才是 env 专用）。
- 本期**不支持** `${VAR:-default}` 默认值语法与 `$` 转义；配置值 MUST NOT 含需字面保留的 `${...}`。

## import-path 第三方插件

引用内置注册表之外的插件 / parser，用 `"module:attr"` 字符串：

```yaml
preset: knowledge_graph
shared_plugins:
  - my_pkg.exts:MyEdgeExtension    # 第三方边扩展插件
plugin_configs:
  # 易踩点一：import-path 插件的 plugin_configs key 用【整条 import-path 字符串】
  "my_pkg.exts:MyEdgeExtension":
    some_option: 1
```

> **易踩点二（import-path 插件的配置键 = 整条 import-path）**：`plugin_configs` 里该插件的
> 键用整条 `"module:attr"` 字符串（与 `*_plugins` 里写的完全一致）。运行期注册名是其
> `get_name()` 返回值，与 import-path 字符串不同——构建时 builder 按 import-path 取配置、
> 实例化后按 `get_name()` 登记。

`Phase1Builder.get_plugin_class` 查找顺序：
1. 内置注册表命中 → 返回；
2. 无 `:` 的未知名 → 返回 `None`（被跳过，不抛异常）；
3. 含 `:` 的 `module:attr` → `importlib` 解析；解析失败或结果非 `Plugin` 子类 **MUST 抛**（用户配置错误）。

## prompt_overrides

`system` / `template` 保持文本；`parser` 写 import-path 串、加载时解析为 `Callable`：

```yaml
preset: knowledge_graph
prompt_overrides:
  extract_concepts:
    system: "你是概念抽取器……"
    template: "文本：{material}\n……"
    parser: "my_pkg.prompts:parse_concepts"   # → Callable
```

省略 `parser` 时该 purpose 的解析回退到默认（与 `register_prompt` 语义一致）。

## 无 preset 路径：自定义 LLM

> **易踩点三（自定义 LLM 必须走无 preset 路径）**：`knowledge_graph()` 校验
> `write_llm` ∈ {deepseek, claude, ollama}，**不**认 import-path 自定义 LLM。
> 用自定义 LLM **必须去掉 `preset`**、写 raw 字段（`write_llm` 直接写插件名 / import-path）：

```yaml
# 无 preset：write_llm / read_llm 是原始字段
write_llm: my_pkg.llms:MyLLM
read_llm: my_pkg.llms:MyLLM
shared_plugins:
  - my_pkg.llms:MyLLM          # 需在插件列表登记，builder 才会实例化
  - summary
write_plugins: []
read_plugins:
  - alias_index
  - alias_entry
  - hub_fallback
  - priority_trim
token_budget: 8000
plugin_configs:
  "my_pkg.llms:MyLLM":
    api_key: ${MY_LLM_KEY}
```

## 安全须知（受信输入）

配置文件经 import-path 可加载**任意代码**（插件类、parser）。因此：

- 配置文件 = **受信输入**。只接受你自己 / 可信运维编写的配置；
- **MUST NOT** 接受陌生来源、用户上传、网络抓取的配置文件；
- 本期**不做**沙箱 / 白名单（声明边界即可）；如需不可信输入，自行隔离（容器 / 沙箱）。

## provenance 白捡

`from_file` build 出的库，开库自动走出处校验。统一图模型为**单一模型**，已删除
`relation_model` 维度——**无硬拒条件**：出处仅跟踪 `schema_version` 与已挂扩展名集。

- 旧库 / 空库无出处 → 按当前配置补写 provenance 放行（真旧库另记 WARNING）；
- 扩展名集变化 → 记 WARNING、刷新为当前集、放行（合法迁移：新字段取默认、旧 orphan 字段忽略）。
