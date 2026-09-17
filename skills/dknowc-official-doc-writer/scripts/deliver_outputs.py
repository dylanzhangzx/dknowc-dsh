#!/usr/bin/env python3
"""把本次任务产出物复制到用户可见的工作目录（WorkBuddy 等宿主环境）。

产出物默认生成在 skill 安装目录的 official-docs/output/，宿主（如 WorkBuddy）
只向用户展示其工作区目录中的文件，导致用户看不到交付物。本脚本自动探测
宿主工作区，把刚生成的文件复制过去并输出用户可见路径。

探测优先级（宿主工作区）：
  1. --dest 显式指定
  2. 环境变量（WORKBUDDY_WORKSPACE / AGENT_WORKSPACE / WORKSPACE 等）
  3. WorkBuddy 时间戳工作区：~/WorkBuddy/ 下目录名形如 2026-08-29-16-28-53
     的最新一个，产物复制到其 outputs/ 子目录
  4. 当前目录（仅当当前目录不在 skill 目录树内）
  5. 都探测不到：不复制，输出 need_dest=true，要求用 --dest 指定后重跑

注意：宿主 agent 执行 skill 脚本时当前目录常在 skill 安装目录内，因此
不能用"当前目录是否等于 skill 目录"判断宿主环境，必须按上述顺序探测。
任何情况下都不会把文件复制到 skill 安装目录自身。

用法：
  python3 scripts/deliver_outputs.py <文件1> [文件2 ...] [--dest <目录>]
  文件路径为空时，自动复制 official-docs/output/ 下最近 10 分钟内新建的文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = SKILL_ROOT / "official-docs" / "output"
RECENT_WINDOW_SECONDS = 10 * 60

# 常见宿主工作区环境变量，按顺序探测
WORKSPACE_ENV_VARS = (
    "WORKBUDDY_WORKSPACE",
    "WORKBUDDY_WORKDIR",
    "WORKBUDDY_PROJECT_DIR",
    "AGENT_WORKSPACE",
    "AGENT_WORKDIR",
    "AGENT_PROJECT_DIR",
    "WORKSPACE_DIR",
    "WORKSPACE",
    "PROJECT_DIR",
    "WORKING_DIR",
)

# WorkBuddy 任务工作区目录名：YYYY-MM-DD-HH-MM-SS
WORKBUDDY_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")


def detect_workbuddy_workspace() -> Path | None:
    """返回 ~/WorkBuddy/ 下最新的时间戳工作区目录，找不到返回 None。

    目录名形如 2026-08-29-16-28-53，字典序即时间序，按目录名取最大最可靠
    （新工作区刚创建、尚无文件写入时 mtime 不可靠）。
    """
    root = Path.home() / "WorkBuddy"
    if not root.is_dir():
        return None
    candidates = [
        d for d in root.iterdir()
        if d.is_dir() and WORKBUDDY_DIR_PATTERN.match(d.name)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.name)


def in_skill_tree(path: Path) -> bool:
    """路径是否等于 skill 目录或位于其内部。"""
    return path == SKILL_ROOT or SKILL_ROOT in path.parents


def detect_dest(explicit_dest: str | None) -> tuple[Path | None, bool, str, bool]:
    """探测交付目标目录。

    返回（目标目录或 None, 是否宿主环境, 探测来源说明, 是否需要用户补 --dest）。
    """
    if explicit_dest:
        dest = Path(explicit_dest).expanduser().resolve()
        return dest, True, "explicit", False

    for name in WORKSPACE_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            dest = Path(value).expanduser().resolve()
            if dest.is_dir():
                return dest, True, f"env:{name}", False

    workbuddy = detect_workbuddy_workspace()
    if workbuddy is not None:
        return workbuddy / "outputs", True, f"workbuddy:{workbuddy.name}", False

    cwd = Path.cwd().resolve()
    if not in_skill_tree(cwd):
        # 当前目录在 skill 目录树之外，视为宿主工作区；已有 outputs/ 子目录时对齐
        dest = cwd / "outputs" if (cwd / "outputs").is_dir() else cwd
        return dest, True, "cwd", False

    # 当前目录在 skill 目录树内且未探测到宿主工作区：宁可不复制，也不污染 skill 目录
    return None, False, "unknown", True


def collect_files(args_files: list[str]) -> list[Path]:
    if args_files:
        files = []
        for name in args_files:
            p = Path(name).expanduser()
            if not p.is_absolute():
                p = (SKILL_ROOT / p).resolve() if (SKILL_ROOT / p).is_file() else p.resolve()
            files.append(p)
        return files
    # 未指定文件：取 output 目录最近窗口内新建的文件
    now = time.time()
    files = []
    if OUTPUT_DIR.is_dir():
        for p in sorted(OUTPUT_DIR.iterdir()):
            if p.is_file() and (now - p.stat().st_mtime) < RECENT_WINDOW_SECONDS:
                files.append(p)
    return files


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="复制产出物到宿主工作区（如 WorkBuddy）")
    parser.add_argument("files", nargs="*", help="要复制的产出物路径；为空时自动取 output 目录最近 10 分钟的文件")
    parser.add_argument("--dest", help="宿主工作区目录（探测失败或需要明确指定时使用）")
    args = parser.parse_args()

    dest, host_env, dest_source, need_dest = detect_dest(args.dest)
    files = collect_files(args.files)

    results = []
    if need_dest:
        note = ("未能自动确定宿主工作区（当前目录在 skill 目录内，且未找到宿主工作区标记）。"
                "请用 --dest <宿主工作区目录> 重新运行本脚本；在此之前不要向用户交付 skill 内部路径。")
    elif not files:
        note = "没有找到可交付的产出物"
        results.append({"copied": False, "error": "没有找到可交付的产出物"})
    else:
        dest.mkdir(parents=True, exist_ok=True)
        for src in files:
            if not src.is_file():
                results.append({"copied": False, "source": str(src), "error": "文件不存在"})
                continue
            target = dest / src.name
            try:
                shutil.copy2(src, target)
                results.append({
                    "copied": True,
                    "source": str(src),
                    "delivered": str(target),
                    "delivered_display": str(target),
                })
            except OSError as exc:
                results.append({"copied": False, "source": str(src), "error": str(exc)})
        note = (f"宿主环境（{dest_source}）：产出物已复制到宿主工作区，向用户展示 delivered 路径。"
                "如该目录不是当前任务工作区，请用 --dest 指定正确目录重跑。") if host_env else ""

    payload = {
        "host_env": host_env,
        "need_dest": need_dest,
        "dest_source": dest_source,
        "dest": str(dest) if dest is not None else None,
        "skill_output_dir": str(OUTPUT_DIR),
        "note": note,
        "files": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = bool(results) and all(r.get("copied") for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
