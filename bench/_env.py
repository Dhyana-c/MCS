"""bench 公共 .env 加载。

消除 ``scripts/_common.setup_env`` 与 ``runner._maybe_load_dotenv`` 的重复解析逻辑，
并去掉 runner 中硬编码的本机路径 ``D:/code/mcs/.env``（改由 ``__file__`` 推导项目根，
与 ``scripts/_common.PROJECT_ROOT`` 同口径）。

加载语义：``os.environ.setdefault``（不覆盖已有值）、忽略 ``#`` 注释与空行、
``split("=", 1)`` 保留 value 中的 ``=``；文件不存在时静默返回 False。
"""

from __future__ import annotations

import os
from pathlib import Path

# bench/ 的父目录即项目根（与 scripts/_common.PROJECT_ROOT 同口径）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(env_file: Path | str | None = None) -> bool:
    """从 .env 加载键值到环境变量。

    Args:
        env_file: 指定文件路径；``None`` 时默认项目根的 ``.env``。

    Returns:
        文件存在并完成解析返回 True，文件不存在返回 False（静默，不抛异常）。

    Notes:
        - 已存在的环境变量不会被覆盖（``os.environ.setdefault``）；
        - ``#`` 开头的行与空行被忽略；
        - 行内按首个 ``=`` 切分，value 中可含 ``=``。
    """
    path = Path(env_file) if env_file is not None else _PROJECT_ROOT / ".env"
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    return True
