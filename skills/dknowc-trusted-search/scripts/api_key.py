#!/usr/bin/env python3
"""统一解析 DKNOWC_API_KEY：优先进程环境变量，缺失时从本机专用配置文件读取。

宿主应用（WorkBuddy 等）的会话进程可能读不到用户 shell 环境变量——启动早于
key 写入，或宿主安全更新后不再加载 shell 导出变量（WorkBuddy 5.5.3 实测持续
读不到）。因此 Key 持久化统一落在本机专用配置文件（XDG 规范路径），脚本直读
文件，避免误报缺失、触发不必要的手机号验证码引导，也免去"写完 key 必须重启
宿主"的限制。读取顺序：进程环境变量 → 专用配置文件（两处均无则视为未配置）。
不读取、不写入、不改写任何 shell 配置文件（如 ~/.zshrc）。key 仅在本机解析并用于
调用深知接口，不写入任何其他位置，不随公开包分发。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

API_KEY_ENV = "DKNOWC_API_KEY"
# 本机 Key 专用配置文件（XDG 规范：$XDG_CONFIG_HOME 默认 ~/.config；Windows 用 %APPDATA%）
KEY_FILE_NAME = "api_key"


def api_key_file_path() -> Path:
    """Key 专用配置文件路径。跨平台：macOS/Linux 用 ~/.config/dknowc/api_key，Windows 用 %APPDATA%/dknowc/api_key。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "dknowc" / KEY_FILE_NAME



def resolve_api_key() -> tuple[str, str]:
    """返回 (key, source)。source ∈ {'environment', 'keyfile', ''}（空串表示未找到）。"""
    value = os.environ.get(API_KEY_ENV, "").strip()
    if value:
        return value, "environment"

    # dsh：插件 shell-env 注入的 DSH_DKNOWC_API_KEY（与 MCP Bearer 同源；dsh 的安全机制
    # 会清理名字含 KEY 的隐式环境变量，该 DSH_ 前缀变量是官方显式注入通道）。
    # 取数脚本与 initialize 门禁同源解析，避免"门禁显示已配置、检索脚本取不到 Key"。
    value = os.environ.get("DSH_DKNOWC_API_KEY", "").strip()
    if value:
        return value, "environment"

    try:
        value = api_key_file_path().read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        value = ""
    if value:
        return value, "keyfile"
    return "", ""
