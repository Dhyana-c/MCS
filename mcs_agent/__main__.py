"""支持 ``python -m mcs.agent`` 启动记忆 agent 对话服务（FastAPI + 前端）。

启动前需设置环境变量：``MCS_CONFIG``（MCS yaml 路径）、``AGENT_LLM_API_KEY``、
``AGENT_LLM_MODEL``、（可选）``AGENT_LLM_BASE_URL``。详见 ``mcs.agent.app.run``。
"""

from mcs.agent.app import run

if __name__ == "__main__":
    run()
