## 1. 依赖与脚手架

- [x] 1.1 `pyproject.toml`：新增可选依赖 `[project.optional-dependencies] claude = ["anthropic>=0.40,<1.0"]`
- [x] 1.2 在 `.venv` 中安装 `anthropic`（`pip install -e ".[dev,claude]"`），确认可导入

## 2. 厂商适配插件实现

- [x] 2.1 新建 `mcs/plugins/phase1/claude_llm.py`：`ClaudeLLMPlugin(Plugin, LLMInterface)`，`name="claude_llm"`、`interfaces=[LLMInterface]`、`version`
- [x] 2.2 `__init__` 读取配置键：`auth_token` / `api_key` / `model` / `base_url`(默认 `https://api.anthropic.com`) / `timeout`(默认 60) / `max_tokens`(默认 4096)
- [x] 2.3 `initialize(context)`：`attach_renderer(context.context_renderer)`；惰性 `from anthropic import Anthropic`，凭证齐备时构造 client（`auth_token` 优先于 `api_key`），缺包/缺凭证则 `client=None`（不抛）
- [x] 2.4 `_raw_call(system, user) -> str`：`system` 非空才作顶层 `system` 参数；`user` 进 `messages=[{"role":"user","content":user}]`；传 `max_tokens`；防御式拼接响应中带 `.text` 的内容块
- [x] 2.5 错误处理：`client is None` 抛 `LLMCallError`（提示装 anthropic 或配 token）；调用异常 `except Exception → raise LLMCallError(...)`，不重试
- [x] 2.6 `shutdown()`：释放 client
- [x] 2.7 自检：源码不含任何 prompt 关键短语或模板 placeholder（零 prompt 模板）

## 3. 注册与配置接线

- [x] 3.1 `mcs/__init__.py` `_default_plugin_registry()`：登记 `"claude_llm": ClaudeLLMPlugin`（惰性 import）
- [x] 3.2 `mcs/core/config.py` `knowledge_graph(llm: str = "deepseek")`：默认 `"deepseek"` 时返回与现状逐字节一致的 11 插件；`"claude"` 时把清单中 `deepseek_llm` 等量替换为 `claude_llm`，并预置 `plugin_configs["claude_llm"]`（`base_url`/`model` 占位，`auth_token` 留空）
- [x] 3.3 验证 `MCS(MCSConfig.knowledge_graph(llm="claude")).initialize()` 能据名实例化并解析为 `LLMInterface` 后端（用 mock 或空 client 路径，不真实联网）

## 4. 示例与环境变量

- [x] 4.1 `.env.example`：新增 `ANTHROPIC_AUTH_TOKEN=` / `ANTHROPIC_BASE_URL=` / `ANTHROPIC_MODEL=` / `API_TIMEOUT_MS=` 占位（不含真实 token）与 `MCS_LLM_PROVIDER=deepseek` 说明
- [x] 4.2 `examples/basic_usage.py`：real 路径按 `MCS_LLM_PROVIDER`(`deepseek` 默认 / `claude`) 选后端；Claude 分支读 `ANTHROPIC_*` 与 `API_TIMEOUT_MS`(毫秒→秒) 注入 `plugin_configs["claude_llm"]`，`sqlite_storage.path=":memory:"`

## 5. 测试

- [x] 5.1 新建 `tests/test_claude_llm.py`：`name=="claude_llm"`、`interfaces` 含 `LLMInterface`、未重写 `call`
- [x] 5.2 源码扫描用例：`claude_llm.py` 不含 "你是"/"extract"/"判断"/`{name}`/`{content}` 等
- [x] 5.3 `_raw_call` 映射用例：注入 fake client，断言 `system`→顶层参数、空 `system` 省略、`user`→user 消息、多 text 块拼接
- [x] 5.4 错误用例：`client is None` 时 `_raw_call` 抛 `LLMCallError`
- [x] 5.5 惰性导入用例：未安装/未配置时仍能 import 类并读 `name`/`interfaces`
- [x] 5.6 注册表与默认后端用例：`claude_llm` 在 `_default_plugin_registry()` 中；`knowledge_graph()`（无参）默认 LLM 仍是 `deepseek_llm`；`knowledge_graph(llm="claude")` 用 `claude_llm`
- [x] 5.7 更新 `tests/test_skeleton.py` 模块/插件清单：加入 `mcs.plugins.phase1.claude_llm` 与 `ClaudeLLMPlugin`

## 6. 文档

- [x] 6.1 `README.md`：依赖段加可选 `anthropic`；插件/模式段说明 Claude 后端与 `knowledge_graph(llm="claude")` 用法；架构图插件层补 `ClaudeLLM`
- [x] 6.2 安全提示：文档明确 token 仅经 env/.env 注入，建议轮换已暴露的 token

## 7. 验收

- [x] 7.1 `.venv` 中 `pytest` 全过（含新增用例）
- [x] 7.2 `.venv` 中 `ruff check .` 零错
- [x] 7.3 `examples/basic_usage.py` mock 模式仍跑通、返回 `List[Node]`
- [x] 7.4 `openspec validate add-claude-llm-adapter --strict` 通过
- [x] 7.5 （可选，需真实凭证）`MCS_LLM_MODE=real MCS_LLM_PROVIDER=claude` 跑通 `basic_usage.py`，3 ingest + 1 query 返回语义相关节点
