"""LoCoMo 对话式记忆评测。

端到端对话记忆评测框架（基于 LoCoMo ACL 2024）：

- 数据三源合成（``data.py``）：V2 base conversation + QA 主体；V2 caption 变体按
  ``dia_id`` 移植 VLM caption；V1 ``evidence`` 按换名映射移植到 V2 题。
- 对话式 ingest 建图（``builder.py``）：每会话一次 ``mcs.ingest``，``work_id`` 启用
  ③b 双轨事件（当下事件落 ``__reality__``、谈话中的事件落对话 universe 叙事时间轴）。
- 评测指标（``metrics.py``）：QA 轨主指标 LLM-judge 正确率（5 类分项）+ 副指标 F1 /
  时间容忍；检索轨 session 级 Recall@k（any / all-evidence hit）。
- 评测脚本（``scripts/``）：``download_data.py`` / ``agent_eval.py`` / ``analyze.py``。

设计依据见 ``openspec/changes/conversational-memory-bench/``。
"""

__all__: list[str] = []
