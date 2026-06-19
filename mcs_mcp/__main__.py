"""支持 ``python -m mcs_mcp`` 启动（等价于 ``mcs-mcp`` console 入口）。"""

from __future__ import annotations

from mcs_mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
