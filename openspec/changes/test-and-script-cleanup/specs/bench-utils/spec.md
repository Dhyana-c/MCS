## ADDED Requirements

### Requirement: bench 公共 .env 加载函数

`bench/_env.py` SHALL 提供 `load_dotenv()` 函数，从项目根目录加载 `.env` 文件到环境变量。

#### Scenario: 默认从项目根目录加载

- **WHEN** 调用 `load_dotenv()` 不指定路径
- **THEN** MUST 从项目根目录（`bench/` 的父目录）查找 `.env` 文件
- **AND** 若文件存在，MUST 解析并设置环境变量

#### Scenario: 自定义路径加载

- **WHEN** 调用 `load_dotenv(env_file=Path("/custom/.env"))`
- **THEN** MUST 从指定路径加载 `.env` 文件

#### Scenario: 文件不存在时静默跳过

- **WHEN** `.env` 文件不存在
- **THEN** 函数 MUST 静默返回，不抛出异常

#### Scenario: 环境变量不覆盖已有值

- **WHEN** `.env` 文件包含 `FOO=bar`，但 `os.environ["FOO"]` 已存在
- **THEN** MUST NOT 覆盖已有值（使用 `os.environ.setdefault`）

#### Scenario: 忽略注释和空行

- **WHEN** `.env` 文件包含 `# comment` 和空行
- **THEN** MUST 忽略这些行，不尝试解析

---

### Requirement: bench 脚本使用公共 .env 加载

`bench/multihop_rag/scripts/` 下的所有启动脚本 SHALL 使用 `bench._env.load_dotenv()` 加载环境变量，MUST NOT 包含重复的 .env 加载代码。

#### Scenario: 脚本使用 load_dotenv

- **WHEN** 检查 `run_baseline.py`、`run_node_rerank.py`、`run_doc_rerank.py`、`run_whole_doc.py`、`run_whole_doc_20.py`、`run_whole_doc_200.py`
- **THEN** 每个脚本 MUST 包含 `from bench._env import load_dotenv` 和 `load_dotenv()` 调用
- **AND** MUST NOT 包含手动解析 `.env` 文件的代码块

---

### Requirement: MultiHop 数据路径可配置

`bench/multihop_rag/data.py` 中的默认数据路径 SHALL 通过环境变量配置，MUST NOT 硬编码开发者本机绝对路径。

#### Scenario: 环境变量覆盖默认路径

- **WHEN** 设置环境变量 `MULTIHOP_CORPUS_PATH=/data/corpus.json`
- **THEN** `DEFAULT_CORPUS` MUST 使用 `/data/corpus.json`

#### Scenario: 环境变量未设置时使用相对路径

- **WHEN** 环境变量 `MULTIHOP_CORPUS_PATH` 未设置
- **THEN** `DEFAULT_CORPUS` MUST 默认为 `<项目根>/data/multihoprag_corpus.json`

#### Scenario: QA 路径同样可配置

- **WHEN** 设置环境变量 `MULTIHOP_QA_PATH=/data/qa.json`
- **THEN** `DEFAULT_QA` MUST 使用 `/data/qa.json`

---

### Requirement: 删除过期脚本 `_run_eval_variants.py`

项目根目录下的 `_run_eval_variants.py` SHALL 被删除，其功能已被 `bench/multihop_rag/scripts/` 下脚本覆盖。

#### Scenario: 文件不存在

- **WHEN** 检查项目根目录
- **THEN** `_run_eval_variants.py` MUST NOT 存在

#### Scenario: 功能替代

- **WHEN** 需要运行评测变体对比
- **THEN** MUST 使用 `bench/multihop-rag/scripts/run_node_rerank.py` 或 `run_doc_rerank.py`
