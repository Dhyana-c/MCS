# model-aware-token-estimation 实现任务

## 1. 基础设施

- [x] 1.1 `pyproject.toml` 添加 `tiktoken` 到 `dependencies`
- [x] 1.2 新增 `mcs/core/calibrated_estimator.py`：`CalibratedEstimator` 类（模型族系数表 + estimate 方法）
- [x] 1.3 新增 `bench/calibration/calibrate_token_estimator.py`：校准脚本骨架（样本集生成 + 精确计数 + 系数拟合）

## 2. LLMInterface 扩展

- [x] 2.1 `mcs/interfaces/llm.py`：新增 `count_tokens(text: str) -> int` 方法（默认实现用 CalibratedEstimator）
- [x] 2.2 `mcs/interfaces/llm.py`：新增 `_detect_model_family() -> str` 辅助方法
- [x] 2.3 `mcs/interfaces/llm.py`：新增 `context_window_size` 属性（默认返回 16000）

## 3. LLM 插件实现

- [x] 3.1 `mcs/plugins/llm/claude_llm.py`：运行时不 override `count_tokens`，走父类校准经验式（claude 族 ×1.7/÷3）；Anthropic API 仅用于 bench/calibration 离线校准
- [x] 3.2 `mcs/plugins/llm/claude_llm.py`：实现 `context_window_size`（插件内映射表，精确匹配 + 默认回退）
- [x] 3.3 `mcs/plugins/llm/deepseek_llm.py`：实现 `count_tokens()`（tiktoken cl100k_base + 校准经验式兜底）
- [x] 3.4 `mcs/plugins/llm/deepseek_llm.py`：实现 `context_window_size`（插件内映射表）
- [x] 3.5 `mcs/plugins/llm/ollama_llm.py`：实现 `count_tokens()`（tiktoken cl100k_base + 校准经验式兜底）
- [x] 3.6 `mcs/plugins/llm/ollama_llm.py`：实现 `context_window_size`（默认 8192 = num_ctx）

## 4. 构建器调整

- [x] 4.1 `mcs/core/builder.py`：调整 `build()` 步骤顺序——先注册插件获取 write_llm，再用 write_llm.count_tokens 构造 TokenBudget
- [x] 4.2 验证调整后全量测试通过

## 5. 配置自动建议

- [x] 5.1 `mcs/entities/config.py`：新增 `_LLM_CONTEXT_WINDOWS` 静态映射表
- [x] 5.2 `mcs/entities/config.py`：`knowledge_graph()` 根据 write_llm 自动计算 T 默认值（保守上限 8000）

## 6. 测试

- [x] 6.1 新增 `tests/test_calibrated_estimator.py`：校准经验式单测（各模型族系数、空值、边界）
- [x] 6.2 新增 `tests/test_llm_count_tokens.py`：LLMInterface.count_tokens 默认实现单测
- [x] 6.3 扩展 `tests/test_token_budget.py`：验证注入 counter 后估算行为（精确计数 vs 经验式）
- [x] 6.4 新增 ClaudeLLMPlugin.count_tokens 单测（验证走 claude 族校准经验式、运行时不调 API）
- [x] 6.5 新增 DeepSeekLLMPlugin.count_tokens 单测（tiktoken + 降级场景）
- [x] 6.6 新增 OllamaLLMPlugin.count_tokens 单测（tiktoken + 降级场景）
- [x] 6.7 新增 context_window_size 单测（各插件映射表 + 未知模型回退）
- [x] 6.8 新增 builder 构建顺序单测（验证 TokenBudget 使用 write_llm 的 counter）
- [x] 6.9 新增 config.knowledge_graph() T 默认值单测（各 LLM 选择 + 用户显式覆盖）
- [x] 6.10 运行全量测试确认无回归

## 7. 文档与规范

- [x] 7.1 更新 `openspec/specs/llm-interaction/spec.md`：新增 count_tokens / context_window_size 需求
- [x] 7.2 更新 `openspec/specs/token-budget-traverse/spec.md`：counter 来源变更
- [x] 7.3 更新 `openspec/specs/phase1-defaults/spec.md`：T 默认值按模型自动计算
- [ ] 7.4 校准系数实测验证（bench/calibration 工具就绪；系数当前为文献/经验值，待跑实测对照精确计数并更新系数表）
