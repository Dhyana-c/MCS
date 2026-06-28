"""个人记忆系统（mcs_mem）——捕获 / 整合 / 日记 / 召回 / 管理看板。

独立顶层包，单向依赖 ``mcs_agent``（agent / MemoryStore / 工具）与 ``mcs``（图谱引擎）：

    mcs_mem  →  mcs_agent  →  mcs

``mcs_agent`` **不** import ``mcs_mem``（无循环依赖）。记忆模块（fragments / consolidation /
scheduler / diary）用 Protocol 解耦、不直接 import ``mcs_agent``；``app`` 层把 agent.memory /
agent.llm 注入它们。

- ``fragments``：当天 MD 碎片捕获层（保真原始层、零 LLM）。
- ``consolidation``：碎片去噪后逐条 ingest 入图（一碎片一事件、单日锁定、failed 可重试去重）。
- ``scheduler``：APScheduler 定时整合（默认凌晨整合昨天）。
- ``diary``：当天碎片概括成日记 MD（人读、不进图）。
- ``app``：FastAPI app（基础路由复用 ``mcs_agent.register_base_routes`` + 记忆路由 + 管理看板）。

> design 演进：早期 ``personal-memory-system`` 的 D1（独立顶层包 ``mcs_mem``）曾作废、
> 改为"代码放 mcs_agent 内"。现 change ``mcs-mem-package-extract`` 推翻之、重新拆为独立
> ``mcs_mem`` 包——但运行时仍挂同一 FastAPI app、依赖 ``mcs_agent`` 的 agent，未回到"独立
> app / 独立端口"的旧路。
"""

from mcs_mem.fragments import FragmentStore
from mcs_mem.consolidation import ConsolidationTracker, Consolidator
from mcs_mem.scheduler import ConsolidationScheduler
from mcs_mem.diary import DiaryGenerator, DiaryStore

__all__ = [
    "FragmentStore",
    "ConsolidationTracker",
    "Consolidator",
    "ConsolidationScheduler",
    "DiaryGenerator",
    "DiaryStore",
]
