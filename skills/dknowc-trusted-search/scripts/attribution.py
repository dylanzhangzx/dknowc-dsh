#!/usr/bin/env python3
"""统一来源声明：构造 `X-Dknowc-Attribution` 请求头值。

依据 MaaS 平台调用来源统计方案（2026-09-14；2026-10-09 头内键名由 source 改为
agentSource——平台方改名，区别于注册 body 的 source 合同标记，值不变）：

- 声明格式（单行纯 ASCII）：`kind=skill;agentSource=dknowc-trusted-search;version=1.4.1;channel=skillhub`
- kind/source/channel 读自**包根 `attribution.json`**（json 字段名保持 `source` 不变，仅请求头输出键名为 `agentSource`；渠道差异由打包期改这一个文件表达）；
- **version 运行时从 SKILL.md frontmatter 解析**（单一事实源，不硬编码）；
- 声明为调用方自报，**仅用于统计、不参与鉴权、不作安全凭证**；
  读取失败时返回 None，调用方不加该头、**不阻断请求**（服务端归"未声明"桶）。

使用方（本包内所有向深知 MaaS 发请求的脚本）：
    from attribution import build_attribution_header, ATTRIBUTION_HEADER
    attr = build_attribution_header()
    if attr:
        headers[ATTRIBUTION_HEADER] = attr
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ATTRIBUTION_HEADER = "X-Dknowc-Attribution"


def _read_skill_version() -> str:
    """从 SKILL.md frontmatter 解析 version（单一事实源）。失败返回空串（头值省略 version 字段）。"""
    try:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r'^version:\s*"?([^"\n]+)"?', text, re.M)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def build_attribution_header() -> str | None:
    """构造声明头值。attribution.json 缺失或 source 为空时返回 None（不加头，不阻断）。"""
    try:
        meta = json.loads((SKILL_ROOT / "attribution.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    kind = str(meta.get("kind") or "skill").strip() or "skill"
    source = str(meta.get("source") or "").strip()
    if not source:
        return None
    channel = str(meta.get("channel") or "").strip()
    parts = [f"kind={kind}", f"agentSource={source}"]
    version = _read_skill_version()
    if version:
        parts.append(f"version={version}")
    if channel:
        parts.append(f"channel={channel}")
    return ";".join(parts)


if __name__ == "__main__":
    print(build_attribution_header() or "(无声明：attribution.json 缺失或 source 为空)")
