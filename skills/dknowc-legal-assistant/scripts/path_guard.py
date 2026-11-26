#!/usr/bin/env python3
"""会话 run 目录读写守卫（1.0.3）。

运行产物（检索 JSON、画像、结论台账、校验结果、报告 HTML）一律写入
**会话工作区的独立 run 目录**，不再写入 Skill 安装目录，也不再默认创建
official-docs/：

- run 目录来源：`--run <目录>` 参数，或环境变量 `DKNOWC_RUN_DIR`；
- run 目录必须位于 Skill 目录之外（拒绝 Skill 根目录及其子目录）；
- 未指定 run 目录时报错并给出用法提示，不落任何文件；
- 输出：相对路径落到 run 目录内；绝对路径必须在 run 目录内；
- 输入：允许 Skill 目录（读自带 reference）与 run 目录（读本次运行产物），
  其余路径拒绝（仍阻断 /etc/passwd 这类系统路径）。
"""

from __future__ import annotations

import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
RUN_ENV = "DKNOWC_RUN_DIR"
RUN_HINT = (
    "请指定会话 run 目录：--run <目录>，或设置环境变量 DKNOWC_RUN_DIR，"
    "例如 --run ./runs/20261120-legal-01（当前会话工作区内的独立目录）。"
)


def resolve_run_dir(value: str | os.PathLike | None = None) -> Path:
    """解析 run 目录：显式参数 > DKNOWC_RUN_DIR；必须在 Skill 目录之外。"""
    raw = str(value or "").strip() or os.environ.get(RUN_ENV, "").strip()
    if not raw:
        raise ValueError(f"未指定会话 run 目录。{RUN_HINT}")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if path == SKILL_ROOT or SKILL_ROOT in path.parents:
        raise ValueError(
            f"输出目录不能放在 Skill 安装目录内：{path}\n"
            "请使用当前会话工作区的独立目录，例如 --run ./runs/20261120-legal-01，"
            "避免污染安装目录、并让每次运行互不覆盖。"
        )
    return path


def _resolve_write(value: str, run_dir: Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raw = run_dir / raw
    return raw.resolve()


def safe_write_path(value: str, run_dir: str | os.PathLike | None = None) -> Path:
    """输出路径必须位于 run 目录内；相对路径落到 run 目录。"""
    run = resolve_run_dir(run_dir)
    path = _resolve_write(value, run)
    if not (path == run or run in path.parents):
        raise ValueError(f"输出路径必须位于会话 run 目录内：{value}\n（run 目录：{run}）")
    if path == SKILL_ROOT or SKILL_ROOT in path.parents:
        raise ValueError(f"输出目录不能放在 Skill 安装目录内：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_read_path(value: str, run_dir: str | os.PathLike | None = None) -> Path:
    """输入路径：Skill 目录（自带文件）或 run 目录（本次运行产物）内，且必须存在。"""
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        run = resolve_run_dir(run_dir)
        path = (run / raw).resolve()
    else:
        path = raw.resolve()
    in_skill = path == SKILL_ROOT or SKILL_ROOT in path.parents
    if not in_skill:
        run = resolve_run_dir(run_dir)
        if not (path == run or run in path.parents):
            raise ValueError(
                f"输入路径必须位于 Skill 目录或会话 run 目录内：{value}\n（run 目录：{run}）"
            )
    if not path.is_file():
        raise ValueError(f"输入文件不存在：{path}")
    return path


def refuse_existing(path: Path, kind: str = "输出") -> None:
    """同一 run 目录重复运行时，不覆盖已有的检索产物（换 run 目录或换文件名）。"""
    if path.exists():
        raise ValueError(
            f"{kind}文件已存在，拒绝覆盖：{path}\n"
            "并行/重复运行请为本次运行使用独立的 --run 目录，或换一个 --output 文件名。"
        )
