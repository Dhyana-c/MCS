"""LoCoMo 评测启动脚本（download / agent_eval / analyze）。

按 bench/README.md 约定：脚本无命令行参数（配置从 ``config/default.json`` 读），
但 LoCoMo 额外暴露 ``--max-conversations`` / ``--limit`` 控制成本。各脚本同时
**可 import**（``from bench.locomo.scripts.agent_eval import run_agent_eval``），
便于 ``__main__.py`` 派发与单测。
"""
