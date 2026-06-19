## 1. 抽取共享渲染纯函数（先斩断私有耦合）

- [x] 1.1 新建 `mcs/rendering.py`，定义公开纯函数：
  - `render_query_result(result, relation_model, plugin_manager) -> str`（逻辑同原 `_render_query_result`：str 透传 / Subgraph 经 `ContextRenderer.render_facts` / 兜底 `str()`）
  - `format_ingest_status(wctx) -> str`（逻辑同原 `_format_ingest_status`：concepts/changed 计数 + persisted，不报边计数）
- [x] 1.2 `mcs/mcp/server.py`：删除内联 `_render_query_result` / `_format_ingest_status`，改 `from mcs.rendering import render_query_result, format_ingest_status` 并更新调用点
- [x] 1.3 `mcs_agent/memory.py`：把 `from mcs.mcp.server import _format_ingest_status, _render_query_result` 改为 `from mcs.rendering import format_ingest_status, render_query_result`，更新调用点与模块 docstring 中"复用 mcp-server 纯函数"的措辞
- [x] 1.4 新增 `tests/test_rendering.py` 覆盖边界（str 透传、Subgraph 渲染含关系边、非 str/非 Subgraph 兜底、空 wctx 字段、persisted yes/no、不含边计数）
- [x] 1.5 运行 `pytest tests/ -q`，确认渲染抽取后行为不变

## 2. MCP server 迁为顶层包 `mcs_mcp/`

- [x] 2.1 把 `mcs/mcp/__init__.py`、`__main__.py`、`server.py` 整体移到 `mcs_mcp/`，更新内部 import（`mcs.mcp.*` 自引用 → `mcs_mcp.*`；docstring 中 `python -m mcs.mcp` → `python -m mcs_mcp`、`import mcs.mcp.server` → `import mcs_mcp.server`）
- [x] 2.2 `pyproject.toml`：`[project.scripts]` 的 `mcs-mcp` 目标改 `mcs_mcp.server:main`；`[tool.setuptools.packages.find].include` 追加 `mcs_mcp*`
- [x] 2.3 `tests/test_mcp_server.py`：`from mcs.mcp.server import (...)` → `from mcs_mcp.server import (...)`；`import mcs.mcp.server` → `import mcs_mcp.server`；任何 `python -m mcs.mcp` 调用更新
- [x] 2.4 `README.md`（约 L154）与 `docs/mcp-server.md`（约 L41 / L74）：`python -m mcs.mcp` → `python -m mcs_mcp`（`mcs-mcp` console 名不变）
- [x] 2.5 确认核心库无残留 `mcs.mcp` 引用（全仓 grep `mcs\.mcp` / `mcs/mcp` 应只剩 archive 文档历史记录）

## 3. 插件归位（符合 plugin-directory-by-type 契约）

- [x] 3.1 把 `mcs/plugins/seed_selector/llm_seed_selector.py`（`SemanticTrimPlugin`）移到 `mcs/plugins/trim/llm_seed_selector.py`
- [x] 3.2 `mcs/presets/phase1.py`：`from mcs.plugins.seed_selector.llm_seed_selector import SemanticTrimPlugin` → `from mcs.plugins.trim.llm_seed_selector import SemanticTrimPlugin`
- [x] 3.3 删除空目录 `mcs/plugins/seed_selector/`
- [x] 3.4 全仓 grep 确认无残留 `plugins.seed_selector` 引用；运行相关测试确认 `semantic_trim` 仍可注册

## 4. 文档同步

- [x] 4.1 修正 `docs/architecture.md` "目录结构"段：删除不存在的 `plugins/base.py`/`plugins/phase1/`/`plugins/phase2/`/`interfaces/storage.py`；改为反映 by-type plugins、`core/plugin.py`（Plugin 基类）、`core/store.py`（StoreInterface）、`mcs_mcp/` 与 `mcs_agent/` 顶层应用包
- [x] 4.2 housekeeping：处理仓库根游离的 `_graph_demo.py`（未跟踪文件——删除或纳入 `examples/`）

## 5. 验证

- [x] 5.1 `pytest tests/ -q` 全绿
- [x] 5.2 冒烟：装 `[mcp]` 后 `python -m mcs_mcp --help` 与 `mcs-mcp` console 入口可启动
- [x] 5.3 冒烟：`mcs_agent` 启动/运行其测试，确认渲染输出与迁移前一致
