## Context

MCS 的 LLM 层已是统一的：`LLMInterface.call(purpose, nodes_in, free_args)` 在基类里完成「查 prompt → 渲染 → 组装 → `_raw_call` → parse」5 步，厂商插件只需实现 `_raw_call(system, user) -> str`。现有唯一适配器 `DeepSeekLLMPlugin` 走 OpenAI 兼容 SDK（惰性导入 `openai`，`initialize` 里 `attach_renderer`，失败抛 `LLMCallError`）。

用户给出的目标后端是 Anthropic Messages 协议（含第三方网关 `https://api.0ki.cn/api/anthropic` 反代的 GLM-5.1），认证用 `ANTHROPIC_AUTH_TOKEN`（Bearer）。本设计在不动核心与 prompt 的前提下，新增一个对称的 Claude 适配器。

约束：
- 不改 `LLMInterface` 签名、读写流程、9 个 purpose 的 prompt/parser。
- 不改 `MCSConfig.knowledge_graph()` 的默认行为（默认仍是 DeepSeek）。
- API token 只经环境变量 / `.env`（已 gitignore），不入库。

## Goals / Non-Goals

**Goals:**
- 新增 `ClaudeLLMPlugin`，作为可与 `deepseek_llm` 互换的厂商后端，零 prompt 模板。
- 支持 `auth_token`(Bearer，优先) / `api_key`、`base_url`、`model`、`timeout`、`max_tokens` 配置。
- 提供「把默认 LLM 切成 Claude」的便捷方式与可跑通的示例（real 模式）。
- 兑现并用测试守护 `llm-interaction` 的「换厂商不动业务」场景。

**Non-Goals:**
- 不实现流式（streaming）、工具调用（tool use）、多模态、缓存等高级特性（Phase 1 只要文本进出）。
- 不把 Claude 设为默认后端，不改既有默认插件清单的数量与内容（DeepSeek 仍默认）。
- 不为网关做 OpenAI↔Anthropic 协议转换；直接走 Anthropic Messages。

## Decisions

### D1. 用官方 `anthropic` SDK（惰性导入），而非裸 HTTP
对齐 `DeepSeekLLMPlugin` 用 `openai` SDK 的既有风格：SDK 处理鉴权头、`base_url` 覆盖、超时；代码量小。`initialize` 中 `try: from anthropic import Anthropic`，缺包则 `client=None`，调用时抛 `LLMCallError`。
- 备选：裸 `httpx` 直接打 `/v1/messages`——更可控、无新依赖，但要自己拼鉴权与解析，且与 DeepSeek 风格不一致。**否决**（仅在 SDK 与网关不兼容时回退）。

### D2. `anthropic` 作为**可选** extra，而非硬依赖
`pyproject.toml` 增 `[project.optional-dependencies] claude = ["anthropic>=0.40,<1.0"]`。多数用户用 DeepSeek，不应被迫装 anthropic。惰性导入 + 清晰报错保证「不装也能 import 插件类」（满足 skeleton 测试只检查 name/interfaces 的用例）。
- 备选：加进主 `dependencies`——简单但让默认安装变重。**否决**。

### D3. 凭证优先级：`auth_token` > `api_key`
网关用 `ANTHROPIC_AUTH_TOKEN`（Bearer）。`anthropic` SDK 支持 `Anthropic(auth_token=...)`（设 `Authorization: Bearer`）与 `Anthropic(api_key=...)`（设 `x-api-key`）。两者都给时用 `auth_token`。两者都缺则 `client=None`。

### D4. `_raw_call` 的请求/响应映射
- `system` → 顶层 `system` 参数，以 text-block 数组 `[{"type":"text","text":system}]` 形式传递（官方 Anthropic 与兼容网关均接受；实测部分网关拒绝顶层 system **字符串**形式，返回 400 invalid_request_error）；空串时**省略**该参数。
- `user` → `messages=[{"role":"user","content": user}]`。
- `max_tokens` → 必传（Anthropic 强制），取配置或默认 `4096`。
- 响应 → 防御式提取：把 `resp.content` 中带 `.text` 的块按序拼接（兼容网关返回多块/单块）。
- 异常 → 统一 `except Exception as e: raise LLMCallError(...)`，不重试。

### D5. 切换后端的便捷方式：`knowledge_graph(llm=...)` 参数
给 `MCSConfig.knowledge_graph` 增可选参数 `llm: str = "deepseek"`，取值 `"deepseek"|"claude"`：
- 默认 `"deepseek"` → 返回与现状**完全一致**的 11 插件（含 `deepseek_llm`），不破坏 `phase1-defaults` 的「默认清单」场景与既有测试。
- `"claude"` → 把清单中的 `deepseek_llm` 替换为 `claude_llm`（仍 11 个），并预置 `plugin_configs["claude_llm"]` 默认。
- 始终保底：用户也可手动在 `config.plugins` 里改名 + 填 `plugin_configs`，无需此便捷参数。
- 备选：新增独立工厂 `MCSConfig.claude_graph()`——更多重复。**否决**，参数法更省。

### D6. 示例与环境变量
`examples/basic_usage.py` 的 real 路径按 `MCS_LLM_PROVIDER`（`deepseek` 默认 / `claude`）选择后端；Claude 分支从 `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`/`ANTHROPIC_MODEL`/`API_TIMEOUT_MS` 读取（`API_TIMEOUT_MS` 毫秒 → 秒）。`.env.example` 增 Anthropic 占位（不含真实 token）。

## Risks / Trade-offs

- **网关协议兼容性**（api.0ki.cn 反代 GLM-5.1 可能与官方 Messages 响应结构有细微差异）→ 防御式文本提取（遍历 content 块取 `.text`）+ `base_url` 可配 + 失败抛带原因的 `LLMCallError`；必要时按 D1 备选回退裸 HTTP。
- **`anthropic` SDK 版本漂移**（`auth_token` 等参数跨版本变化）→ 版本范围收窄（`>=0.40,<1.0`），惰性导入并 try/except 包裹构造。
- **`max_tokens` 默认过小截断 JSON** 导致 `LLMParseError` → 默认给到 `4096` 且可配；GLM 输出 ```json fence 已由现有 `strip_json_fence` 兜底。
- **凭证泄露**（用户已在对话中贴出真实 token）→ 仅经 env/.env 注入、`.env` 已 gitignore；文档与回执提示**轮换该 token**。
- **便捷参数与默认清单约束**（`phase1-defaults` 要求默认「不多不少」11 个）→ `llm` 默认值保证零参数调用与现状逐字节一致；切换仅做等量替换。

## Migration Plan

1. 加可选依赖 extra（`pyproject.toml`）。
2. 实现 `ClaudeLLMPlugin` + 注册表登记 `claude_llm`。
3. `knowledge_graph(llm=...)` 便捷参数 + `claude_llm` 默认 `plugin_configs`。
4. `.env.example` / `examples` / `README` 文档接线。
5. 加测试，`pytest` + `ruff` 双绿。

回滚：删 `claude_llm.py`、注册表条目与可选依赖即可；无数据/schema 迁移，默认行为不变，零副作用。

## Open Questions

- 网关期望 Bearer（`auth_token`）还是 `x-api-key`？按所给 env 默认走 `auth_token`，`api_key` 作为回退已覆盖；联调时若 401 再调整。
- 是否需要为 Claude 单独加 `examples/` 脚本？当前决定**复用** `basic_usage.py` 的 provider 开关，避免重复；后续如需再拆。
