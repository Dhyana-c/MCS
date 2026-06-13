## 1. 共享 LLM 重试基类（B2）

- [x] 1.1 `interfaces/llm.py`：`LLMInterface` 基类新增 `_call_with_retry(fn, *args, **kwargs)` 方法，封装指数退避 + jitter 重试逻辑。可重试条件：`LLMCallError` 的 `__cause__` 是网络错误或 429。参数 `max_retries=3`, `base_delay=1.0`，通过 `self.config` 读取可覆盖。退避公式：`delay = base_delay * (2 ** attempt) + random.uniform(0, base_delay)`
- [x] 1.2 `plugins/llm/deepseek_llm.py`：`_raw_call` 内部改调 `self._call_with_retry(self._do_raw_call, system, user)`，将原有 SDK 调用逻辑移入 `_do_raw_call` 私有方法
- [x] 1.3 `plugins/llm/claude_llm.py`：同 1.2，`_raw_call` 改走 `_call_with_retry`
- [x] 1.4 `plugins/llm/ollama_llm.py`：同 1.2，`_raw_call` 改走 `_call_with_retry`。额外：将 HTTP 429/5xx 错误包装为 `LLMCallError`（带 `retryable=True` 属性），使基类能识别可重试错误
- [x] 1.5 验证：运行 `pytest -q` 确保基线测试通过

## 2. rerank token 缓存 key 修正（B1）

- [x] 2.1 `plugins/postprocess/rerank.py`：`LexicalScorer` 新增 `_token_cache: dict[tuple[str, int], tuple[set[str], set[str]]]` 属性（key 为 `(node_id, content_hash)`）
- [x] 2.2 `plugins/postprocess/rerank.py`：`score` 方法中构建 cache key `key = (node.id, hash(node.content or ""))`，优先查 `_token_cache`，未命中时 `_tokenize` 后写入缓存
- [x] 2.3 验证：运行 `pytest -q` 确保基线测试通过

## 3. merge content 压缩（A1）

- [x] 3.1 `core/write_pipeline.py`：`WritePipeline.__init__` 新增 `merge_content_threshold: int = 500` 参数（从 config 读取 `merge_content_threshold`）
- [x] 3.2 `core/write_pipeline.py`：`_dispatch_merge` 在 content 追加后检查 `len(node.content) > self.merge_content_threshold`，超阈值则调用 `self.llm.call(purpose="gen_summary", nodes_in=[node], free_args={"max_tokens": 200})` 压缩 content。压缩结果替换 `node.content`。异常时 log warning 并保留原始 content
- [x] 3.3 验证：运行 `pytest -q` 确保基线测试通过

## 4. 别名富集恢复（A2）

- [x] 4.1 `prompts/judge_relations.py`：`SYSTEM_PROMPT` 加一句关于 merge 时提供别名的指引："merge 时如果该概念有同义词、缩写、变体写法，在 aliases_to_add 中列出。"
- [x] 4.2 `prompts/judge_relations.py`：`USER_TEMPLATE` 的 JSON 示例加 `"aliases_to_add": ["别名1", "别名2"]` 字段（仅 merge 行出现）
- [x] 4.3 `core/decisions.py`：`Decision.aliases_to_add` 字段 docstring 去掉 `# DEPRECATED: 不再使用` 标记
- [x] 4.4 验证：运行 `pytest -q` 确保基线测试通过

## 5. perf-optimization-overhaul 提案修正

- [x] 5.1 `openspec/changes/perf-optimization-overhaul/tasks.md`：任务 5（LLM 重试）改为引用 `LLMInterface` 基类共享方法，而非仅 deepseek 适配器。删除原 5.1/5.2 的 deepseek-only 描述
- [x] 5.2 `openspec/changes/perf-optimization-overhaul/tasks.md`：任务 7（rerank 缓存）修正路径 `plugins/index/rerank.py` → `plugins/postprocess/rerank.py`，缓存 key 改为 `(node_id, content_hash)`
- [x] 5.3 `openspec/changes/perf-optimization-overhaul/design.md`：D3 决策更新为"共享基类 `_call_with_retry`"，D5 决策更新缓存 key 方案

## 6. 全量验证

- [x] 6.1 运行完整测试套件 `pytest -q` 确认所有测试通过
- [ ] 6.2 200 篇子集 A/B 验证：对比 ef2384d 前后的 hit@10、alias 索引规模、候选召回率（A3）
