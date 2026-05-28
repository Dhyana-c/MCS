## Context

MCS 的架构设计已稳定到 v2.0（见 `openspec/specs/architecture.md`），Phase 1 范围已对齐到"知识图谱模式 / 教科书与 Wiki 场景"（见 `openspec/changes/phase1-knowledge-graph/proposal.md`）。架构定义了：
- 最小核心 `Node` + extensions 字典挂载点
- 写入 9 个 / 查询 7 个状态点的状态机流程
- 8 个接口 + 5 个 Phase 1 插件 + 6 个 Phase 2 预留插件

本 change 是从"纸面设计"到"可工作 Python 项目"的桥梁——**只搭骨架，不实现任何业务逻辑**。后续 `phase1-knowledge-graph` change 在此骨架上填充各模块实现。

**关键约束**：
- 严格遵守 `architecture.md` §8 的目录结构
- 严格按 `architecture.md` §2-3 提供所有接口和核心类的占位
- 严格按 `architecture.md` §6 提供 5 个 Phase 1 插件占位
- 不引入任何架构未声明的模块或文件

## Goals / Non-Goals

**Goals:**
- 提供完整的、可 `pip install -e .` 的 Python 包骨架
- 所有架构定义的接口、核心类、插件都有对应占位文件
- 测试框架就绪，可立即开始写测试
- 代码风格工具就绪，避免后续返工
- 项目能从仓库 clone 后 3 行命令跑通骨架自检（install、pytest、import）

**Non-Goals:**
- **不实现任何业务逻辑**（所有方法体 `pass` 或 `raise NotImplementedError`）
- 不写示例代码（`examples/` 留空，仅 README 占位）
- 不配置 CI/CD（GitHub Actions 等）
- 不生成 API 文档（Sphinx 等）
- 不引入 Docker / 部署相关配置
- 不实现 Phase 2 插件内容（仅留空文件 + docstring）

## Decisions

### D1: 使用 PEP 517/518 `pyproject.toml`，不用 `setup.py`

**Decision:** 用 `pyproject.toml` 单文件描述包元数据、依赖、工具配置。

**Rationale:**
- 现代 Python 标准，PEP 621 后元数据声明完整
- 一份配置承载 build / pytest / ruff 三者
- 工具链（pip / uv / poetry）普遍支持

**Alternatives considered:**
- `setup.py + setup.cfg`：legacy，不推荐
- Poetry / PDM：增加额外工具依赖，本项目复杂度不需要

### D2: 采用 flat layout（`mcs/` 在根），不用 src layout

**Decision:** 包目录 `mcs/` 直接位于项目根，与 `architecture.md` §8 完全一致。

**Rationale:**
- 架构文档明确画出 flat layout
- 项目规模可控（< 50 模块），不需要 src layout 的隔离
- 开发调试时 import 路径更直观

**Trade-off:** flat layout 在 `pip install -e .` 时可能让顶层 markdown 文件被工具误识别，需在 pyproject.toml 显式指定 `packages = ["mcs"]`

### D3: 所有 8 个接口用 `abc.ABC + @abstractmethod`，方法体 `pass`

**Decision:** 接口类标准化为 ABC 模式，方法体仅 `pass`（被 `@abstractmethod` 装饰器覆盖，正常情况下不执行）。

**Rationale:**
- 强类型约束，子类未实现抽象方法时 `__init__` 失败
- 与 `architecture.md` §3 文档化的设计直接对应
- IDE 自动补全友好

**Alternative considered:** `Protocol`（structural typing）——更灵活，但在 spec 文档明确"contract"的场景下 ABC 更严

### D4: 数据对象统一用 `@dataclass`

**Decision:** `Source`, `HookContext`, `QueryContext`, `MCSConfig`, `Node`, `Edge` 全部用 dataclass。

**Rationale:**
- 自动生成 `__init__` / `__repr__` / `__eq__`，避免样板代码
- 字段类型即文档
- `asdict()` / `astuple()` 便于序列化

**Trade-off:** dataclass 不强制运行时类型检查；如需要可后续上 Pydantic（Phase 1 不需要）

### D5: 方法体占位策略：ABC 用 `pass`，具体类用 `NotImplementedError`

**Decision:**
- ABC 接口的抽象方法 → `pass`（被 `@abstractmethod` 装饰器覆盖，体内容不会执行）
- 具体类的待实现方法 → `raise NotImplementedError("Phase 1 implementation pending")`

**Rationale:**
- 区分"接口契约"与"待填实现"
- 误调用具体类未实现方法时立即报错，不静默通过
- 验收测试可基于 NotImplementedError 检查"骨架完整无遗漏"

### D6: 工具链选用 ruff（单工具替代 black + isort + flake8）

**Decision:** 用 `ruff` 一个工具承担 lint + import 排序 + 格式化（`ruff format`）。

**Rationale:**
- 速度快 10-100 倍
- 配置集中在 pyproject.toml
- 规则覆盖完整

**Alternative considered:** `black + isort + flake8` 组合——工具更成熟但配置碎片化

### D7: 测试框架 pytest，配置内嵌 pyproject.toml

**Decision:** pytest 为基础，加 `pytest-asyncio` 为 Phase 2 异步调用预留。

**Rationale:**
- 行业标准
- fixtures 模式与 plugin manager 测试天然契合
- 异步预留避免后续重新配置

### D8: Phase 2 占位文件仅含 docstring，不含类定义

**Decision:** `mcs/plugins/phase2/<plugin>.py` 仅写：

```python
"""<PluginName>Plugin - Phase 2，本期不实现。

见 architecture.md §7。
"""
```

**Rationale:**
- 避免被误识别为"已实现但有 bug"
- 占领文件路径（防止 Phase 2 时变更 import 路径）
- 显式声明边界

### D9: `Source` 数据类放在 `plugins/phase1/source_tracking.py`，不在 core

**Decision:** `Source` dataclass 定义于 `mcs.plugins.phase1.source_tracking`，与 `SourceTrackingPlugin` 同模块。

**Rationale:**
- 严格遵守"核心稳定 / 数据可扩展"原则（见 `architecture.md` §1.1）
- 核心 `Node` 不引用 `Source`（通过 `extensions` 字典间接关联）
- Phase 2 升级到事件层时，Source 演进为 fact_id 引用，不影响核心

## Risks / Trade-offs

- **[骨架与架构发散]** 实现 change 时可能偏离架构定义
  → Mitigation: `specs/project-skeleton/spec.md` 要求"接口签名与 architecture.md §3 一致"；Code Review 阶段对照检查

- **[依赖版本未来不兼容]** `openai`、`jieba` 等依赖升级可能破坏
  → Mitigation: pyproject.toml 使用宽松版本约束（如 `openai>=1.0,<2.0`），README 写明兼容范围

- **[Phase 2 占位混淆]** 阅读者可能误以为 Phase 2 已实现
  → Mitigation: 文件顶部 docstring 显式标注"Phase 2，本期不实现"

- **[flat layout 安装陷阱]** `pip install -e .` 可能误打包根目录 markdown 文件
  → Mitigation: pyproject.toml 显式 `[tool.setuptools.packages.find] include = ["mcs*"]`

- **[骨架过度细化]** 过早在骨架里写实现细节，导致 Phase 1 实现被框死
  → Mitigation: 严格执行 D5（方法体只 pass/raise），不在骨架预设算法

## Migration Plan

不适用——这是首次初始化，无现有代码需要迁移。

后续约束：
- `phase1-knowledge-graph` change 基于此骨架填充
- 对骨架结构的任何修改（新增 / 删除模块）必须通过新 change 走 propose 流程

## Open Questions

1. **DeepSeek 客户端 SDK 选择**：直接用 `openai` SDK（DeepSeek 兼容 OpenAI 接口）还是 DeepSeek 官方 SDK？
   - 当前倾向 `openai`（生态更广），最终决定推迟到 `phase1-knowledge-graph` 实现阶段

2. **中文分词依赖**：jieba 还是 pkuseg？
   - jieba 更轻量、维护活跃，pkuseg 准确率高但更重
   - 当前倾向 jieba，可在实现时切换

3. **顶层 `mcs/__init__.py` 是否暴露常用类**？
   - 例如 `from mcs import MCS, MCSConfig` 一行可用
   - 骨架阶段：留空（避免空类骨架的导入污染）；实现阶段补
