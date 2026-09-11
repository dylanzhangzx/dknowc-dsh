#!/usr/bin/env python3
"""统一解析 DKNOWC_API_KEY：优先进程环境变量，缺失时从 ~/.zshrc 兜底解析。

宿主应用（WorkBuddy 等）的会话进程可能读不到用户 shell 环境变量——启动早于
key 写入，或宿主安全更新后不再加载 ~/.zshrc 的导出变量（WorkBuddy 5.5.3 实测
持续读不到）。进程环境变量缺失但盘上已有 key 时直接从 zshrc 解析，避免误报
缺失、触发不必要的手机号验证码引导，也免去"写完 key 必须重启宿主"的限制。key 仅在本机解析并用于调用深知
接口，不写入任何其他位置，不随公开包分发。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

API_KEY_ENV = "DKNOWC_API_KEY"


def resolve_api_key() -> tuple[str, str]:
    """返回 (key, source)。source ∈ {'environment', 'zshrc', ''}（空串表示未找到）。"""
    value = os.environ.get(API_KEY_ENV, "").strip()
    if value:
        return value, "environment"

    zshrc = Path.home() / ".zshrc"
    try:
        text = zshrc.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "", ""

    # 匹配 export DKNOWC_API_KEY='xxx' / "xxx" / xxx；多条时取最后一条（最新写入）
    pattern = re.compile(
        r'^\s*export\s+' + re.escape(API_KEY_ENV) + r'\s*=\s*[\'"]?([^\'"\r\n#]+?)[\'"]?\s*$',
        re.M,
    )
    for value in reversed(pattern.findall(text)):
        value = value.strip()
        if value:
            return value, "zshrc"
    return "", ""
