# 贡献指南

感谢你对 MCS 项目的关注！本文档说明如何参与开发。

## 环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/<your-org>/mcs.git
cd mcs

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

# 3. 安装开发依赖
pip install -e ".[dev]"

# 4. 验证环境
pytest                          # 跑全部测试
ruff check .                    # 代码风格检查
python examples/basic_usage.py  # mock 模式跑通示例
```

## 开发流程

1. **创建分支**：从 `main` 创建功能分支，命名格式 `feat/<描述>` 或 `fix/<描述>`
2. **开发**：在功能分支上开发和测试
3. **提交**：遵循提交规范（见下方）
4. **测试**：确保所有测试通过，必要时补充新测试
5. **发起 PR**：描述变更内容和原因

## 提交规范

提交信息使用中文，格式：

```
<type>: <简要描述>
```

类型：
- `feat`: 新功能
- `fix`: 修复 bug
- `docs`: 文档变更
- `refactor`: 重构（不改变功能）
- `test`: 测试相关
- `chore`: 构建/工具/杂项

## 代码规范

- 使用 `ruff` 做代码风格检查和格式化
- 所有 import 放到文件开头，按标准库 / 第三方库 / 项目内模块分组
- 遵循最小改动原则
- 编写测试，尽量测出边界情况

## 项目结构

```
mcs/
├── core/           # 核心引擎（GraphStore, WritePipeline, QueryEngine...）
├── interfaces/     # 插件接口（ABC）
├── plugins/        # 插件实现
├── presets/        # 预设配置（create_mcs, Phase1Builder）
├── prompts/        # LLM prompt 模板
└── utils/          # 工具函数

docs/               # 理解性文档
openspec/specs/     # Capability spec（契约性文档）
openspec/changes/   # 变更管理
bench/              # 评测框架
tests/              # 测试套件
examples/           # 使用示例
```

## 文档

- [文档索引](docs/INDEX.md) — 所有文档的统一导航入口
- [架构总览](docs/architecture.md) — 系统设计
- [图模型设计](docs/graph-model-design.md) — 完整、权威的图模型与核心算法设计
- [Spec 索引](openspec/specs/INDEX.md) — 契约规范

## 问题反馈

- 提交 [Issue](https://github.com/<your-org>/mcs/issues) 报告 bug 或建议功能
- 提交前请搜索已有 Issue，避免重复
