"""支持 ``python -m mcs_mem`` 启动个人记忆应用（基础 + 碎片/整合/日记/召回/管理看板）。

记忆应用经 ``mcs_mem.create_app`` 组装（复用 ``mcs_agent.register_base_routes`` + 记忆路由），
挂同一 FastAPI app。启动前环境变量同 ``mcs_agent``（``MCS_CONFIG`` / ``AGENT_LLM_*``）；
定时整合可经 ``MCS_CONSOLIDATION_CRON`` / ``MCS_CONSOLIDATION_ENABLED`` 配置。详见 ``mcs_mem.app.run``。
"""

from mcs_mem.app import run

if __name__ == "__main__":
    run()
