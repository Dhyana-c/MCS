## 1. 插件实现

- [x] 1.1 新增 `mcs/plugins/phase1/ollama_llm.py`：`OllamaLLMPlugin(Plugin, LLMInterface)`，`name="ollama_llm"`、`interfaces=[LLMInterface]`
- [x] 1.2 `__init__` 读配置：`base_url`(默认 `http://localhost:11434/v1`)、`model`、`timeout`(默认较长)、`max_tokens`(默认 32768)、`num_ctx`(默认 8192)、`think`(默认 `False`)、`api_key`(dummy 占位)
- [x] 1.3 `initialize`：`attach_renderer`；惰性导入 `httpx`；默认构造 client（缺 SDK 时安全置 `client=None`；`api_key` 非占位时附 `Bearer` 头）
- [x] 1.4 `_raw_call`：原生 `/api/chat`（system 非空才加 system 消息；携带 `think`、`options.num_predict`/`num_ctx`），返回 `message.content`（空内容时从 `message.thinking` 兜底）；失败抛 `LLMCallError`（含"未运行/模型未 pull"清晰提示）；不重试
- [x] 1.5 源码零 prompt 模板

## 2. 注册与配置工厂

- [x] 2.1 在 `mcs/__init__.py` 的 `_default_plugin_registry` 注册 `"ollama_llm" -> OllamaLLMPlugin`
- [x] 2.2 `MCSConfig.knowledge_graph(llm="ollama")` 分支：把清单里的 `deepseek_llm` 换成 `ollama_llm`，预置默认 `plugin_configs["ollama_llm"]`
- [x] 2.3 确认默认 `knowledge_graph()`（无参）仍是 deepseek

## 3. 测试

- [x] 3.1 接口契约：`name`/`interfaces`/实现 `_raw_call`、未 override `call`
- [x] 3.2 `_raw_call` 映射：system 非空→system 消息；空 system 不传；返回 `message.content`；`think`/`options` 入请求体（mock `client.post`）
- [x] 3.3 默认值：base_url/timeout/max_tokens/num_ctx/think 回退；`chat_url` 由 base_url 归一推导；默认构造 client
- [x] 3.4 错误：调用失败/连不上/模型未 pull → `LLMCallError` 且不重试
- [x] 3.5 工厂：`knowledge_graph(llm="ollama")` 用 ollama_llm；默认仍 deepseek
- [x] 3.6 惰性导入：缺 `httpx` 时仍能 import 类、读 name/interfaces

## 4. 文档

- [x] 4.1 用法说明：装 Ollama、`ollama serve`、`ollama pull <model>`（如 qwen2.5/qwen3）、`MCSConfig.knowledge_graph(llm="ollama")` 配置示例
- [x] 4.2 注明风险：小模型结构化输出弱/更慢；与 build-cost-reduction 的协同（本地=零 token 成本实验路径）
