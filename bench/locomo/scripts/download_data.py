"""LoCoMo 数据拉取：探测复用本机既有 clone，否则从 GitHub 克隆。

**探测复用优先**（D2）：当前两个仓库历史性地 clone 在 ``bench/longmemeval/data/``
下（``locomo_repo`` V1 + ``locomo_v2`` V2 社区修正版）。本脚本探测该位置，存在且校验
通过则 **copy** 到规范位置 ``bench/locomo/data/``（LoCoMo 数据归 locomo bench 管）。

**copy 而非 move**：``longmemeval-bench`` 是另一个未 apply 的活跃 change，可能仍引用
该位置——copy 不破坏姊妹 change。若已 copy 过则跳过。

否则从 GitHub 克隆：
- V1 官方：``snap-research/locomo``
- V2 社区修正版：``BrianV1981/locomo-v2``（含 Windows Zone.Identifier 文件，需 restore）

数据**不入 git**（``.gitignore`` 排除 ``bench/locomo/data/locomo_*/``）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parent.parent  # bench/locomo
_ROOT = _BENCH.parents[1]  # repo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

DATA_DIR = _BENCH / "data"

# 本机既有 clone 的历史位置（longmemeval-bench change 留下）。
LEGACY_LOCORO_V1 = _ROOT / "bench" / "longmemeval" / "data" / "locomo_repo"
LEGACY_LOCORO_V2 = _ROOT / "bench" / "longmemeval" / "data" / "locomo_v2"

DEST_LOCORO_V1 = DATA_DIR / "locomo_repo"
DEST_LOCORO_V2 = DATA_DIR / "locomo_v2"

GITHUB_V1 = "https://github.com/snap-research/locomo.git"
GITHUB_V2 = "https://github.com/BrianV1981/locomo-v2.git"

# 期望产出文件 + 最小字节数（校验 clone/copy 完整性）。
EXPECTED_FILES: dict[Path, int] = {
    DEST_LOCORO_V1 / "data" / "locomo10.json": 1_000_000,
    DEST_LOCORO_V2 / "data" / "locomo_v2_base.json": 1_000_000,
    DEST_LOCORO_V2 / "data" / "locomo_v1_source.json": 1_000_000,
    DEST_LOCORO_V2 / "data" / "locomo_v2_moondream.json": 500_000,
    DEST_LOCORO_V2 / "data" / "locomo_v2_qwen.json": 500_000,
    DEST_LOCORO_V2 / "data" / "locomo_v2_minicpm.json": 500_000,
}


def _dir_ok(path: Path) -> bool:
    return path.exists() and path.is_dir()


def _validate(min_bytes: bool = True) -> list[str]:
    """返回缺失/过小文件的人话列表（空 = 全齐）。"""
    problems: list[str] = []
    for f, min_sz in EXPECTED_FILES.items():
        if not f.exists():
            problems.append(f"缺失：{f.relative_to(_ROOT)}")
        elif min_bytes and f.stat().st_size < min_sz:
            problems.append(f"过小（{f.stat().st_size}B < {min_sz}）：{f.relative_to(_ROOT)}")
    return problems


def _copy_tree(src: Path, dst: Path) -> None:
    """copytree，跳过 ``.git`` 与 ``__pycache__``，已存在则先清目标。"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
    )


def _git_clone(url: str, dest: Path) -> None:
    """``git clone --depth 1``；dest 已存在则跳过。"""
    if dest.exists():
        print(f"  已存在，跳过克隆：{dest}")
        return
    print(f"  git clone {url} -> {dest}")
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        check=True,
    )


def _restore_v2_zone_identifier(repo: Path) -> None:
    """locomo-v2 仓库含 Windows Zone.Identifier 文件，checkout 可能失败——手动 restore。

    见 design D2。失败非致命（``|| true`` 语义）。
    """
    if not (repo / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "restore", "--source=HEAD", ":/"],
            cwd=str(repo), check=False, capture_output=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  git restore 警告（非致命）：{e}")


def download_data(*, force: bool = False) -> Path:
    """拉取 LoCoMo 数据到 ``bench/locomo/data/``，返回 DATA_DIR。

    优先探测复用 ``bench/longmemeval/data/`` 下的既有 clone（copy）；否则从 GitHub
    克隆。``force=True`` 强制重拉。数据齐备即通过校验。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not force and not _validate():
        print(f"LoCoMo 数据已齐备：{DATA_DIR}")
        return DATA_DIR

    # ① 探测复用：copy 本机既有 clone（不影响 longmemeval-bench 姊妹 change）。
    copied: list[str] = []
    if _dir_ok(LEGACY_LOCORO_V1) and (force or not _dir_ok(DEST_LOCORO_V1)):
        print(f"复用本机 V1 clone（copy）：{LEGACY_LOCORO_V1} -> {DEST_LOCORO_V1}")
        _copy_tree(LEGACY_LOCORO_V1, DEST_LOCORO_V1)
        copied.append("V1")
    if _dir_ok(LEGACY_LOCORO_V2) and (force or not _dir_ok(DEST_LOCORO_V2)):
        print(f"复用本机 V2 clone（copy）：{LEGACY_LOCORO_V2} -> {DEST_LOCORO_V2}")
        _copy_tree(LEGACY_LOCORO_V2, DEST_LOCORO_V2)
        copied.append("V2")

    # ② 否则从 GitHub 克隆缺失的仓库。
    if not _dir_ok(DEST_LOCORO_V1):
        print("本机无 V1 clone，从 GitHub 克隆…")
        _git_clone(GITHUB_V1, DEST_LOCORO_V1)
    if not _dir_ok(DEST_LOCORO_V2):
        print("本机无 V2 clone，从 GitHub 克隆…")
        _git_clone(GITHUB_V2, DEST_LOCORO_V2)
        _restore_v2_zone_identifier(DEST_LOCORO_V2)

    problems = _validate()
    if problems:
        print("数据校验失败：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)
    print(f"LoCoMo 数据齐备（copy={copied or 'clone'}）：{DATA_DIR}")
    return DATA_DIR


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.locomo.scripts.download_data")
    ap.add_argument("--force", action="store_true", help="强制重拉（覆盖既有）")
    args = ap.parse_args()
    download_data(force=args.force)


if __name__ == "__main__":
    main()
