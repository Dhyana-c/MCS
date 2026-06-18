## ADDED Requirements

### Requirement: bench 公共 .env 加载函数

`bench/_env.py` SHALL 提供 `load_dotenv()` 函数，从指定路径或项目根目录加载 `.env` 文件到环境变量。

#### Scenario: 默认从项目根加载

- **WHEN** 调用 `load_dotenv()` 不指定路径
- **THEN** MUST 从项目根目录（`bench/` 的父目录，由 `__file__` 推导）查找 `.env` 文件
- **AND** 若文件存在，MUST 解析并设置环境变量

#### Scenario: 自定义路径加载

- **WHEN** 调用 `load_dotenv(env_file=Path("/custom/.env"))`
- **THEN** MUST 从指定路径加载 `.env` 文件

#### Scenario: 文件不存在时静默跳过

- **WHEN** `.env` 文件不存在
- **THEN** 函数 MUST 返回 `False` 且不抛出异常

#### Scenario: 环境变量不覆盖已有值

- **WHEN** `.env` 文件包含 `FOO=bar`，但 `os.environ["FOO"]` 已存在
- **THEN** MUST NOT 覆盖已有值（使用 `os.environ.setdefault`）

#### Scenario: 忽略注释和空行

- **WHEN** `.env` 文件包含 `# comment` 和空行
- **THEN** MUST 忽略这些行，不尝试解析

#### Scenario: value 含等号

- **WHEN** `.env` 文件包含 `URL=http://x?a=b`
- **THEN** MUST 按首个 `=` 切分，value 为 `http://x?a=b`

---

### Requirement: bench 脚本复用公共 .env 加载

`scripts/_common.setup_env` 与 `runner._maybe_load_dotenv` SHALL 通过 `bench._env.load_dotenv()` 加载环境变量，MUST NOT 包含重复的内联解析代码，MUST NOT 硬编码开发者本机路径。

#### Scenario: setup_env 复用 load_dotenv

- **WHEN** 检查 `bench/multihop_rag/scripts/_common.py`
- **THEN** `setup_env` MUST 调用 `load_dotenv(PROJECT_ROOT / ".env")`
- **AND** MUST NOT 包含手动逐行解析 `.env` 的代码块

#### Scenario: runner 不再硬编码本机路径

- **WHEN** 检查 `bench/multihop_rag/runner.py`
- **THEN** `_maybe_load_dotenv` MUST 调用 `load_dotenv()`
- **AND** MUST NOT 包含 `D:/code/mcs/.env` 等硬编码本机绝对路径
- **AND** 项目根 `.env` 缺失时 MUST 兜底当前目录 `Path(".env")`

---

### Requirement: 删除过期脚本 `_run_eval_variants.py`

项目根目录下的 `_run_eval_variants.py` SHALL 不存在；其功能由 `bench/multihop_rag/scripts/` 下脚本覆盖。

> 该文件已于 `236bd58`（统一 bench 目录）删除，本 change 登记该删除契约。

#### Scenario: 文件不存在

- **WHEN** 检查项目根目录
- **THEN** `_run_eval_variants.py` MUST NOT 存在

#### Scenario: 功能替代

- **WHEN** 需要运行评测变体对比
- **THEN** MUST 使用 `bench/multihop_rag/scripts/` 下的脚本（如 `eval.py`）或 `MultiHopEvalRunner`
