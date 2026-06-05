## Why

MCS 目前只有云端 LLM 后端（DeepSeek / Claude），每次 build/eval 都按 token 计费（本次评测烧了 ¥110，大头在 build）。新增一个**本地 Ollama 后端**让 MCS 能跑本地模型（计划用 Qwen ~9B 等）：

- **本地推理零 token 费用** —— 昂贵的 build/实验变成只花 compute/time、不花钱，正好接上 build-cost-reduction 的省钱主题，适合大量便宜迭代；
- 离线 / 隐私 / 灵活换模型。

MCS 已有 DeepSeek/Claude 两个 LLM adapter 的成熟模式（厂商插件只实现 `_raw_call`、其余继承 `LLMInterface`），Ollama 照此平行新增即可，零侵入。

## What Changes

> **实现修正**：原计划走 OpenAI 兼容 `/v1` + 复用 `openai` SDK，实际改为走 **原生 `/api/chat` + `httpx`**，并新增 `think`（默认关闭思维模型 chain-of-thought）与 `num_ctx` 配置。原因：OpenAI 兼容端点无法关闭思维模型的 thinking，会让每次调用耗费数千 token、整图 build 跑不完。详见 `design.md` D1 的更新注记。下文带删除线语义的 `/v1` / `openai` 表述以此为准。

- 新增 `OllamaLLMPlugin` 实现统一 `LLMInterface`：唯一厂商特定的是 `_raw_call(system, user) -> str`，**不 override `call`**，渲染/组装/解析全继承基类；源码**零 prompt 模板**
- 实现走 Ollama 的 **OpenAI 兼容端点**（`http://localhost:11434/v1`），**复用现有 `openai` SDK**（零新依赖，与 `deepseek_llm` 同一套写法）
- 注册为 `"ollama_llm"`；加进 `MCSConfig.knowledge_graph(llm="ollama")` 选择器；**默认后端仍是 deepseek**（Ollama 为 opt-in）
- 配置键：`base_url`（默认 `http://localhost:11434/v1`）、`model`（如 `qwen2.5:7b`/`qwen3:8b`，需先 `ollama pull`）、`timeout`（默认更长）、`max_tokens`、`api_key`（dummy 占位，本地无需鉴权）
- 文档：装 Ollama、`ollama serve`、`ollama pull <model>`、配置示例

## Capabilities

### New Capabilities
- `ollama-llm-adapter`: 本地 Ollama LLM 后端——通过 OpenAI 兼容端点实现 `LLMInterface`，配置驱动、零 prompt、可选依赖、默认后端不变；结构平行 `claude-llm-adapter`

### Modified Capabilities

（无——工厂选择器与注册表纳入本能力，对齐 claude-llm-adapter 的做法；不改其它后端、不改默认）

## Impact

- 新增 `mcs/plugins/phase1/ollama_llm.py`；注册进 plugin registry；`MCSConfig` 加 `llm="ollama"` 分支
- 复用现有 `openai` 依赖，**无新增第三方包**
- 不改 `mcs/core/`、`mcs/prompts/`、不改 deepseek/claude 后端、不改默认后端
- **与 build-cost-reduction 协同**：本地后端 = 零 token 成本的实验路径
- **风险（诚实）**：小本地模型（7–9B）的质量与**结构化 JSON 输出可靠性弱于云端** → extract_concepts/judge_relations 解析失败可能更多（已落地的 lenient parser 缓解）；推理更慢；需本地装 Ollama + pull 模型