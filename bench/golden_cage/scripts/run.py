# -*- coding: utf-8 -*-
"""启动脚本：agent 查询评测（全部 150 题，断点续跑）+ 报告。

等价于 ``python -m bench.golden_cage run``。无命令行参数（bench 脚本规范）；
输出目录 / LLM / 预算取 ``config/default.json``。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "run"]
    from bench.golden_cage.__main__ import main

    main()
