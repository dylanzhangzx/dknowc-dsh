#!/usr/bin/env python3
"""统一解析 DKNOWC_API_KEY：优先进程环境变量，缺失时从本机专用配置文件读取。

宿主应用（WorkBuddy 等）的会话进程可能读不到用户 shell 环境变量——启动早于
key 写入，或宿主安全更新后不再加载 shell 导出变量（WorkBuddy 5.5.3 实测持续
读不到）。因此 Key 持久化统一落在本机专用配置文件（XDG 规范路径），脚本直读
文件，避免误报缺失、触发不必要的手机号验证码引导，也免去"写完 key 必须重启
宿主"的限制。读取顺序：进程环境变量 → 专用配置文件 → 历史 ~/.zshrc 块（3.7.5
迁移期兜底，读到即视为已持久化）。key 仅在本机解析并用于调用深知接口，不写入
任何其他位置，不随公开包分发。
"""

from __future__ import annotations

import os
import re
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


def _read_legacy_zshrc() -> str:
    """迁移期：从历史 ~/.zshrc 块读取 Key（3.7.5 之前的写入位置）。"""
    zshrc = Path.home() / ".zshrc"
    try:
        text = zshrc.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    pattern = re.compile(
        r'^\s*export\s+' + re.escape(API_KEY_ENV) + r'\s*=\s*[\'"]?([^\'"\r\n#]+?)[\'"]?\s*$',
        re.M,
    )
    for value in reversed(pattern.findall(text)):
        value = value.strip()
        if value:
            return value
    return ""


def resolve_api_key() -> tuple[str, str]:
    """返回 (key, source)。source ∈ {'environment', 'keyfile', 'zshrc', ''}（空串表示未找到）。"""
    value = os.environ.get(API_KEY_ENV, "").strip()
    if value:
        return value, "environment"

    try:
        value = api_key_file_path().read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        value = ""
    if value:
        return value, "keyfile"

    legacy = _read_legacy_zshrc()
    if legacy:
        return legacy, "zshrc"
    return "", ""
