# mcp-via-agent

把 mcs_mcp 后端从 MCS 框架管线改为全部经 mcs_agent：query 走 agent.chat、ingest 走 memory.learn，LLM 复用 MCS yaml 已配的（反推 LLMConfig），不新增配置文件。
