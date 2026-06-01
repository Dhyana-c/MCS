## Context

MCS 的 LLM 后端是配置驱动的插件：厂商插件只实现 `_raw_call(system, user) -> str`，`LLMInterface.call` 负责 prompt 查找/渲染/组装/解析。已有 `deepseek_llm`（openai SDK）与 `claude_llm`（anthropic SDK）。本 change 平行新增 `ollama_llm`，让 MCS 能跑本地模型（计划 Qwen ~9B），把按 token 计费的 build/eval 变成本地零成本实验路径。

## Goals / Non-Goals

**Goals:**
- 新增 `OllamaLLMPlugin`，行为/契约与现有 adapter 一致，零侵入
- 复用现有 `openai` 依赖（Ollama OpenAI 兼容端点），不引新包
- opt-in：默认后端仍 deepseek

**Non-Goals:**
- 不改 `LLMInterface` / `mcs/core/` / `mcs/prompts/` / 其它后端 / 默认后端
- 不绑定具体模型、不做重试或质量调优
- 不在本 change 跑云端 vs 本地的评测对比（留 build-cost-reduction）

## Decisions

### D1: 走 Ollama 的 OpenAI 兼容端点，复用 openai SDK

Ollama 在 `http://localhost:11434/v1` 暴露 OpenAI 兼容的 `chat/completions`。直接复用现有 `openai` 客户端（与 `deepseek_llm` 同写法），**零新依赖、最小代码、最一致**。

**备选**：原生 `/api/chat`（httpx/requests）——更贴近 Ollama 专有选项（keep_alive/num_ctx 等），但要新代码/依赖。先不做，必要时再加。

### D2: 本地无需凭证 → 默认就构造 client

与 deepseek/claude 不同（它们要 key 才构造 client），Ollama 本地无鉴权：`initialize` 默认就构造 client（`api_key` 用 dummy 占位 `"ollama"`，因 openai SDK 要求非空）。惰性导入 `openai`，缺失时安全置 `client=None`。

### D3: 调用期错误清晰化

调用时若 Ollama 未运行（连不上）或**模型未 pull**（404/错误），`_raw_call` MUST 抛 `LLMCallError`，提示"启动 `ollama serve` 且 `ollama pull <model>`"。对齐 Phase 1 错误基线：失败抛 `LLMCallError`、**不自动重试**。

### D4: 配置默认值贴合本地特性

- `base_url` 默认 `http://localhost:11434/v1`
- `model` 可配置（如 `qwen2.5:7b`/`qwen3:8b`），**需先 pull**；无内置厂商默认或给明显占位
- `timeout` 默认更长（如 120s，本地推理慢）
- `max_tokens` 默认 4096；OpenAI 兼容下 Ollama 将其映射为 `num_predict`

### D5: `_raw_call` 映射

把 `system`/`user` 映射为 chat messages（system 非空才加 system 消息），返回 `choices[0].message.content`。与 deepseek 一致。

## Risks / Trade-offs

- **[小模型结构化输出弱]** 7–9B 本地模型的 JSON 可靠性低于云端 → extract_concepts/judge_relations 解析失败更多 → 缓解：已落地的 lenient parser（容忍单对象等）；必要时后续给本地模型加更稳的输出约束
- **[慢]** 本地推理比云端慢 → 缓解：timeout 调长；build 变成 time-bound 而非 cost-bound
- **[需本地环境]** 要装 Ollama + `ollama pull` 模型 → 缓解：文档写清；调用期给清晰报错
- **[质量低于云端]** 适合便宜实验/迭代，最终质量评估仍建议云端对照 → 与 build-cost-reduction 协同：本地零成本探索 + 云端定稿验证

## 与其它 change 的协同

- **build-cost-reduction**：本地后端 = 零 token 成本的实验路径；可在那里做"云端 vs 本地"的成本/质量对照（不在本 change）。
- 与 `query-rerank-and-persistence` / `graph-construction-quality` 正交（只换 LLM 后端，不动检索/持久化/建图逻辑）。