# bench-utils Specification

## MODIFIED Requirements

### Requirement: bench 脚本复用公共 .env 加载

`scripts/_common.setup_env` SHALL 通过 `bench._env.load_dotenv()` 加载环境变量，MUST NOT 包含重复的内联解析代码，MUST NOT 硬编码开发者本机路径。

> 框架 `mcs.query` runner（`bench/multihop_rag/runner.py`）随 retire-framework-query-pipeline 退役删除——其 `_maybe_load_dotenv` 场景一并移除；env 加载契约收敛到存活的 `_common.setup_env`。

#### Scenario: setup_env 复用 load_dotenv

- **WHEN** 检查 `bench/multihop_rag/scripts/_common.py`
- **THEN** `setup_env` MUST 调用 `load_dotenv(PROJECT_ROOT / ".env")`
- **AND** MUST NOT 包含手动逐行解析 `.env` 的代码块

---

### Requirement: 删除过期脚本 `_run_eval_variants.py`

项目根目录下的 `_run_eval_variants.py` SHALL 不存在；其功能由 `bench/multihop_rag/scripts/` 下脚本覆盖。

> 该文件已于 `236bd58`（统一 bench 目录）删除，本 change 登记该删除契约。
> 框架 `mcs.query` runner（`MultiHopEvalRunner` / `scripts/eval.py` 等）随 retire-framework-query-pipeline 退役删除——「功能替代」场景改指向 agent 评测轨 `scripts/agent_full_run.py`。

#### Scenario: 文件不存在

- **WHEN** 检查项目根目录
- **THEN** `_run_eval_variants.py` MUST NOT 存在

#### Scenario: 功能替代

- **WHEN** 需要运行评测变体对比
- **THEN** MUST 使用 `bench/multihop_rag/scripts/agent_full_run.py`（agent ReAct 检索轨）
- **AND** 框架 `mcs.query` 基线 runner / `MultiHopEvalRunner` MUST NOT 存在（已退役）
