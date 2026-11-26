#!/usr/bin/env python3
"""读写路径守卫（运行目录口径，2026-11-20 起）。

- 读：会话工作区的运行目录、Skill 内文档均可读（相对路径按当前工作目录解析）；
- 写：一律拒绝落在 Skill 安装目录内（含 official-docs/）；业务产物统一写到
  run_dir.py 管理的 `--out` / `--run` 运行目录。
"""

from __future__ import annotations

from pathlib import Path

from run_dir import resolve_input, resolve_output_path


def safe_read_path(value: str) -> Path:
    """输入路径：相对路径按当前工作目录解析（运行目录里的产物在会话工作区）。"""
    return resolve_input(value)


def safe_write_path(value: str) -> Path:
    """输出路径：拒绝 Skill 安装目录内；裸文件名按当前工作目录解析。"""
    return resolve_output_path(value)
