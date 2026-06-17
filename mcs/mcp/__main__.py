"""支持 ``python -m mcs.mcp`` 启动（等价于 ``mcs-mcp`` console 入口）。"""

from __future__ import annotations

from mcs.mcp.server import main

if __name__ == "__main__":
    raise SystemExit(main())
