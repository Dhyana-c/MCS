## MODIFIED Requirements

### Requirement: README 精简

根目录 `README.md` SHALL 仅包含项目定位、核心定位、快速开始、文档导航、评测导航、贡献指南链接、许可证链接。

#### Scenario: README 结构符合开源惯例

- **WHEN** 检查 `README.md` 内容
- **THEN** 包含以下章节：项目定位、核心定位、快速开始、文档、评测、贡献、许可证
- **AND** 不包含架构详解、管线段定义、插件列表等架构详解内容
- **AND** 不包含评测 CLI 参数、评测架构、输出文件等评测详解内容
- **AND** 不包含项目结构树、模式配置表、开发状态、依赖列表等

#### Scenario: README 包含文档导航

- **WHEN** 检查 `README.md` "文档"章节
- **THEN** 链接到 `docs/INDEX.md`

#### Scenario: README 包含开源文档导航

- **WHEN** 检查 `README.md`
- **THEN** "贡献"章节链接到 `CONTRIBUTING.md`
- **AND** "许可证"章节链接到 `LICENSE`
