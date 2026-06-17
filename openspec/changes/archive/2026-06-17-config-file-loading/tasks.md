## 1. import-path 解析工具（D3）

- [x] 1.1 新增 `import_from_path(path: str) -> Any`（`"module:attr"` → importlib 加载）：格式非法 / 模块或属性不存在 MUST 抛清晰错误（含原始 path）。置于 `mcs/utils/`（如 `mcs/utils/imports.py`）
- [x] 1.2 单测：合法 path 解析到对象；非法格式 / 模块缺失 / 属性缺失各自报错

## 2. get_plugin_class import-path 回退（mcs-builder MODIFIED，D3）

- [x] 2.1 `Phase1Builder.get_plugin_class`（及共享解析点）：内置 dict 未命中 **且** name 含 `":"` → `import_from_path`；解析结果非 `Plugin` 子类 MUST 报错（`mcs/presets/phase1.py` / `mcs/core/builder.py`）
- [x] 2.2 无 `":"` 的未知名 MUST 仍返回 `None`（"未知名跳过、不抛异常"逐字保留）；`":"` 形且解析失败 MUST 抛（用户配置错误，不静默）
- [x] 2.3 单测：内置名仍解析到内置类；`"mod:Cls"` 解析到外部类；`"nonexistent"`（无 `:`）→ None；`"bad.mod:X"`（有 `:` 解析失败）→ 抛

## 3. 环境变量插值（D2）

- [x] 3.1 `_expand_env(obj)`：递归遍历 dict / list / str，把字符串里的 `${VAR}`（`[A-Za-z_]\w*`）用 `os.environ` 展开；缺失变量 MUST 抛清晰错误（列出缺哪个 key）（`mcs/entities/config.py` 或 `mcs/utils/`）
- [x] 3.2 仅 `${VAR}` 展开；单花括号 `{...}`（prompt 模板风格）不受影响
- [x] 3.3 单测：`${VAR}` 命中展开；缺失抛错且含变量名；含 `{material}` 的字符串原样保留

## 4. MCSConfig.from_file（D1 / D4）

- [x] 4.1 `MCSConfig.from_file(path) -> MCSConfig`：惰性 `import yaml`（缺失报 `pip install mcs[yaml]`）→ 解析 → `_expand_env` → 见下叠加（`mcs/entities/config.py`）
- [x] 4.2 `preset` 键：调对应工厂（`knowledge_graph` / `memory_system`，传 `write_llm` / `read_llm` / `relation_model`）得 base；无 `preset` 则 base = `MCSConfig()`
- [x] 4.3 字段叠加：标量覆盖；`*_plugins` 显式给出则替换、否则留 base；`plugin_configs` 按插件名**深合并**；`prompt_overrides` 合并
- [x] 4.4 `prompt_overrides.<purpose>.parser` 为 import-path 字符串时，用 `import_from_path` 解析为 `Callable` 放进 config（`system` / `template` 保持文本）
- [x] 4.5 单测：preset 叠加产出 == 等价手写 config；标量覆盖；plugin_configs 深合并（preset 的 model 留、文件的 api_key 叠加）；plugin 列表替换；parser import-path → callable

## 5. 打包（D5）

- [x] 5.1 `pyproject.toml` 加 `[project.optional-dependencies] yaml = ["pyyaml>=6"]`
- [x] 5.2 `from_file` 惰性 import yaml；缺失时 `ImportError`/`RuntimeError` 提示 `pip install mcs[yaml]`
- [x] 5.3 单测：mock yaml 缺失 → 报含安装提示的错误

## 6. 文档

- [x] 6.1 `README.md` / `docs/`：YAML 配置示例（preset + plugin_configs + 环境变量 + import-path 第三方插件 + prompt_overrides）——并注明两个易踩点：① import-path 插件的 `plugin_configs` key 用整条 import-path 字符串、运行期注册名是其 `get_name()`；② 自定义 LLM 必须走无 `preset` 路径（`knowledge_graph()` 只认 deepseek/claude/ollama）
- [x] 6.2 **安全须知**：配置文件经 import-path 可加载任意代码 = 受信输入，勿接受陌生来源（D6）

## 7. 测试与回归

- [x] 7.1 集成：写一个 YAML（preset=knowledge_graph + sqlite path + 一个 import-path 边扩展）→ `from_file` → `Phase1Builder(config).build()` 成功、可 ingest/query（mock LLM）
- [x] 7.2 集成：YAML 指定 `relation_model` 与已建库不符 → 开库走 provenance 拒绝（复用 edge-extension-model 的出处校验，验证不回归）
- [x] 7.3 基线回归：既有 `create_mcs` / `Phase1Builder(config).build()` 代码路径**逐字不变**；全仓 `.venv\Scripts\python.exe -m pytest -q` 全绿
