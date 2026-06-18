"""bench/_env.load_dotenv 单元测试。

覆盖：默认/自定义路径、setdefault 不覆盖、文件不存在静默、忽略注释与空行、
value 含 ``=``、value 带空格、空 value、默认路径用 monkeypatch 避免依赖真实项目根。
"""

from __future__ import annotations

import os
from pathlib import Path

from bench._env import load_dotenv


def test_load_custom_path(tmp_path: Path, monkeypatch) -> None:
    envf = tmp_path / ".env"
    envf.write_text("FOO=bar\nBAZ=qux\n", encoding="utf-8")
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAZ", raising=False)

    assert load_dotenv(envf) is True
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_does_not_overwrite_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EXISTING", "preset")
    envf = tmp_path / ".env"
    envf.write_text("EXISTING=should_not_apply\n", encoding="utf-8")

    assert load_dotenv(envf) is True
    assert os.environ["EXISTING"] == "preset"


def test_missing_file_returns_false_silent(tmp_path: Path) -> None:
    missing = tmp_path / "nope.env"
    # 文件不存在：不抛异常，返回 False
    assert load_dotenv(missing) is False


def test_ignores_comments_and_blank_lines(tmp_path: Path, monkeypatch) -> None:
    envf = tmp_path / ".env"
    envf.write_text(
        "# a comment\n"
        "\n"
        "   \n"
        "KEY=val\n"
        "#ANOTHER=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("KEY", raising=False)
    monkeypatch.delenv("ANOTHER", raising=False)

    assert load_dotenv(envf) is True
    assert os.environ["KEY"] == "val"
    assert "ANOTHER" not in os.environ


def test_value_with_equals_sign(tmp_path: Path, monkeypatch) -> None:
    """value 含 '=' 时只按首个 '=' 切分。"""
    envf = tmp_path / ".env"
    envf.write_text("URL=http://x?a=b&c=d\n", encoding="utf-8")
    monkeypatch.delenv("URL", raising=False)

    assert load_dotenv(envf) is True
    assert os.environ["URL"] == "http://x?a=b&c=d"


def test_value_with_spaces_and_empty_value(tmp_path: Path, monkeypatch) -> None:
    """key/value 两侧空格被 strip；空 value 合法。"""
    envf = tmp_path / ".env"
    envf.write_text("SPACED = hello world \nEMPTY=\n", encoding="utf-8")
    monkeypatch.delenv("SPACED", raising=False)
    monkeypatch.delenv("EMPTY", raising=False)

    assert load_dotenv(envf) is True
    assert os.environ["SPACED"] == "hello world"
    assert os.environ["EMPTY"] == ""


def test_default_path_uses_project_root(tmp_path: Path, monkeypatch) -> None:
    """不传 env_file 时从项目根加载；monkeypatch 项目根到 tmp 隔离真实环境。"""
    envf = tmp_path / ".env"
    envf.write_text("DEFAULTED=1\n", encoding="utf-8")
    monkeypatch.setattr("bench._env._PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("DEFAULTED", raising=False)

    assert load_dotenv() is True
    assert os.environ["DEFAULTED"] == "1"


def test_default_path_missing_returns_false(tmp_path: Path, monkeypatch) -> None:
    """默认路径下不存在 .env 时静默返回 False。"""
    empty_root = tmp_path / "no_env_here"
    empty_root.mkdir()
    monkeypatch.setattr("bench._env._PROJECT_ROOT", empty_root)

    assert load_dotenv() is False
