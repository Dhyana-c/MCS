## Why

MCS 目前只有一个厂商 LLM 适配器（`DeepSeekLLMPlugin`，走 OpenAI 兼容 SDK）。用户需要使用 Anthropic Claude（Messages 协议）的后端——包括兼容网关（如 `https://api.0ki.cn/api/anthropic` 反代的 GLM-5.1 等模型）。`llm-interaction` 契约本就要求"换厂商只需新增适配插件、不动业务流程与 prompt"，但至今没有第二个适配器来兑现并验证这一点。

## What Changes

- 新增 `ClaudeLLMPlugin`（`mcs/plugins/phase1/claude_llm.py`）：实现 `LLMInterface._raw_call(system, user) -> str`，通过 Anthropic Messages API 发起调用。**零 prompt 模板**——渲染、组装、解析全部复用框架 9 个 purpose 的既有实现。
- 在 `mcs/__init__.py` 的默认插件注册表新增名称 `claude_llm`，使配置可按名引用、与 `deepseek_llm` 互换。
- 配置键：支持 `auth_token`(优先) / `api_key`、`model`、`base_url`、`timeout`、`max_tokens`；可从环境变量 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `API_TIMEOUT_MS` 读取。
- 依赖：新增**可选** extra `claude = ["anthropic>=0.40,<1.0"]`；插件惰性导入 `anthropic`，未安装时抛清晰错误（对齐 `deepseek_llm` 对 `openai` 的惰性导入处理）。
- 默认配置 `MCSConfig.knowledge_graph()` **保持以 DeepSeek 为默认 LLM**（不破坏现状）；Claude 作为可选替换，并提供便捷选择方式。
- `.env.example` 增加 Anthropic 占位变量；`examples/basic_usage.py` 的 real 模式支持按 provider（deepseek / claude）选择后端。
- 测试：新增 `tests/test_claude_llm.py`（name/interfaces、源码无 prompt 字符串、`_raw_call` 消息映射、缺 client/SDK 抛 `LLMCallError`）；skeleton 模块清单加入 `claude_llm`。
- 非 BREAKING：纯增量，不改既有 LLMInterface 签名、读写流程、prompt 与默认插件清单。

## Capabilities

### New Capabilities
- `claude-llm-adapter`: Anthropic Claude/Messages 协议的厂商 LLM 适配插件——定义其单一职责（调用与解析）、配置键与环境变量映射、零 prompt 模板约束、错误处理基线，以及与统一 `LLMInterface` / `ContextRenderer` 的接线方式。

### Modified Capabilities
<!-- 无：本变更为纯增量，不修改任何既有 capability 的 requirement。
     现有 llm-interaction「厂商适配层只做调用与解析 / 换厂商不动业务」场景由本变更兑现，但其 requirement 文本不变。 -->

## Impact

- **新增代码**：`mcs/plugins/phase1/claude_llm.py`；`tests/test_claude_llm.py`。
- **修改代码**：`mcs/__init__.py`（注册表）、`mcs/core/config.py`（可选的 LLM 选择便捷方法）、`pyproject.toml`（可选依赖 extra）、`.env.example`、`examples/basic_usage.py`、`README.md`（依赖与厂商说明）。
- **依赖**：可选 `anthropic` Python SDK（不装则仅 Claude 后端不可用，其余功能不受影响）。
- **契约**：兑现 `llm-interaction` 的「换厂商不动业务」场景；不改任何既有 spec 的 requirement。
- **安全**：API token 仅经环境变量 / `.env`（已被 `.gitignore` 忽略）注入，**不写入仓库**任何文件。
