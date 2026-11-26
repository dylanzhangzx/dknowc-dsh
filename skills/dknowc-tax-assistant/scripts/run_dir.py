#!/usr/bin/env python3
"""运行目录（run dir）管理：所有业务产物只写会话工作区里的独立运行目录。

口径（对齐可信多引擎搜索 1.0.1）：
- 检索 JSON、答案、报告、补查/重渲染产物统一写到 `--out` / `--run` 指定的运行目录；
- 任何输出都拒绝落在 Skill 安装目录内（含 official-docs/），不默认创建
  official-docs/search-results、official-docs/output；
- 首次检索用 new_run_dir()：目录已存在且非空即报错，避免并行/重复运行互相覆盖；
- 下游（合并、渲染、补查、画像/校验）用 open_run_dir()：必须是已存在的运行目录；
- 都不传时 auto_run_dir() 在当前工作目录的 runs/ 下新建唯一名；当前目录若在
  Skill 安装目录内则拒绝（干净安装后不能往 Skill 目录落任何业务文件）。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def is_skill_path(path: Path) -> bool:
    path = Path(path)
    return path == SKILL_ROOT or SKILL_ROOT in path.parents


def _resolve(value: str) -> Path:
    raw = Path(str(value or "")).expanduser()
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    return raw.resolve()


def _reject_skill_path(path: Path, flag: str) -> None:
    if is_skill_path(path):
        raise ValueError(
            f"{flag} 不能指向 Skill 安装目录内：{path}\n"
            "请使用当前会话工作区的独立运行目录，例如 ./runs/20261120-B01-<时间>，"
            "避免污染安装目录、并行任务互相覆盖。"
        )


def new_run_dir(value: str, flag: str = "--out") -> Path:
    """新建运行目录：已存在且非空即拒绝（不覆盖已有 run）。"""
    path = _resolve(value)
    _reject_skill_path(path, flag)
    if path.exists() and any(path.iterdir()):
        raise ValueError(
            f"{flag} 目录已有运行结果：{path}\n"
            "请为本次运行使用独立目录，或先清理该目录。"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_run_dir(value: str, flag: str = "--run") -> Path:
    """打开已有运行目录（合并/渲染/补查/画像校验用）：必须存在且不在 Skill 目录内。"""
    path = _resolve(value)
    _reject_skill_path(path, flag)
    if not path.is_dir():
        raise ValueError(f"{flag} 不是已存在的运行目录：{path}")
    return path


def ensure_run_dir(value: str, flag: str = "--out") -> Path:
    """画像/材料/校验等上游脚本用：目录存在就复用，不存在就新建（不要求先跑检索）。"""
    path = _resolve(value)
    _reject_skill_path(path, flag)
    if path.exists() and not path.is_dir():
        raise ValueError(f"{flag} 已存在但不是目录：{path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def auto_run_dir(prefix: str = "tax") -> Path:
    """未传 --out 时的默认运行目录：当前工作目录 runs/<prefix>-<时间>。"""
    cwd = Path.cwd().resolve()
    _reject_skill_path(cwd, "当前工作目录")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = cwd / "runs" / f"{prefix}-{stamp}"
    path = base
    seq = 1
    while path.exists() and any(path.iterdir()):
        path = Path(f"{base}-{seq}")
        seq += 1
    path.mkdir(parents=True, exist_ok=True)
    return path


def out_file(run_dir: Path, name: str, flag: str = "--output") -> Path:
    """运行目录内的输出文件：只接受文件名，拒绝路径穿越与绝对路径。"""
    raw = str(name or "").strip()
    if not raw:
        raise ValueError(f"{flag} 不能为空")
    candidate = Path(raw)
    if candidate.is_absolute() or len(candidate.parts) > 1 or ".." in candidate.parts:
        raise ValueError(
            f"{flag} 只接受运行目录内的文件名（不含路径）：{name}\n"
            f"产物统一放在运行目录：{run_dir}"
        )
    target = (run_dir / candidate.name).resolve()
    _reject_skill_path(target, flag)
    if target.exists():
        raise ValueError(f"{flag} 文件已存在，不覆盖已有产物：{target}")
    return target


def resolve_input(value: str) -> Path:
    """输入路径：相对路径按当前工作目录解析；必须是已存在文件（由调用方判断存在性）。"""
    return _resolve(value)


def resolve_run_input(value: str, run_dir_path: str = "") -> Path:
    """运行目录内的输入：传了 run 目录时，裸文件名优先按 run 目录解析，其次 cwd。"""
    raw = Path(str(value or "")).expanduser()
    if run_dir_path and not raw.is_absolute() and "/" not in str(value):
        candidate = _resolve(str(Path(run_dir_path) / raw))
        if candidate.is_file():
            return candidate
    return resolve_input(value)


def resolve_output_path(value: str) -> Path:
    """显式输出路径（不带 --run 时用）：拒绝 Skill 安装目录内。"""
    path = _resolve(value)
    _reject_skill_path(path, "--output")
    return path


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-一-鿿]+$")


def is_bare_filename(value: str) -> bool:
    raw = str(value or "").strip()
    return bool(raw) and bool(_SAFE_NAME.match(raw)) and "/" not in raw and "\\" not in raw


def resolve_write_target(output: str, run_dir_path: str = "", *, flag: str = "--output") -> Path:
    """输出目标统一解析：
    - 传了运行目录（--out/--run）：output 必须是裸文件名，落在运行目录内且不覆盖；
    - 未传运行目录：output 必须是显式路径，拒绝 Skill 安装目录内。
    """
    if run_dir_path:
        run = ensure_run_dir(run_dir_path, "--out")
        return out_file(run, output or "", flag)
    if not str(output or "").strip():
        raise ValueError(f"未提供 {flag}：请传 --out 运行目录 + 文件名，或显式输出路径")
    return resolve_output_path(output)
