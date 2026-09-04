#!/usr/bin/env python3
"""把项目 SVG 页面打包为单文件 HTML 预览页（首页确认门 / 页面进度查看用）。

宿主环境（WorkBuddy 等）通常无法直接预览 .svg 文件，本脚本把项目的
svg_output/ 下全部（或指定）页面以 data URI 内嵌到单个 HTML——浏览器
直接打开即可翻阅，无需任何外部依赖；SVG 以 <img> 方式内嵌，天然隔离
脚本，单文件可复制分发。

用法：
  python3 scripts/preview_slide_html.py <项目名> [--output <文件名>] [--title <标题>]
  项目须位于 projects/<项目名>/svg_output/；输出默认 official-docs/output/<项目名>_pages_preview.html，
  dsh 场景预览页落会话工作区产物目录，直接向用户展示该路径即可。
"""

from __future__ import annotations

import argparse
import base64
import html
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
# dsh：项目目录为工作区级 dknowc-projects/（跨会话延续、访达可直达）；预览页落会话隔离产物区
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
PROJECTS_DIR = Path(_os.getcwd()).resolve() / "dknowc-projects"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"


def esc(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def svg_dimensions(svg_text: str) -> str:
    """从 SVG 头部提取宽高比（width/height 或 viewBox），供响应式缩放。"""
    head = svg_text[:2000]
    m = re.search(r'viewBox\s*=\s*"[\d.+-]+\s+[\d.+-]+\s+([\d.]+)\s+([\d.]+)"', head)
    if m and float(m.group(1)) > 0 and float(m.group(2)) > 0:
        return f"{m.group(1)} / {m.group(2)}"
    m = re.search(r'width\s*=\s*"([\d.]+)', head)
    n = re.search(r'height\s*=\s*"([\d.]+)', head)
    if m and n and float(m.group(1)) > 0 and float(n.group(1)) > 0:
        return f"{m.group(1)} / {m.group(2)}"
    return "16 / 9"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成项目 SVG 页面的单文件 HTML 预览页")
    parser.add_argument("project", help="项目名（projects/ 下目录名）")
    parser.add_argument("--output", help="输出 HTML 文件名（落 official-docs/output/）")
    parser.add_argument("--title", default="", help="预览页标题（默认 <项目名> 页面预览）")
    args = parser.parse_args()

    svg_dir = (PROJECTS_DIR / args.project / "svg_output").resolve()
    if not _is_within(svg_dir, PROJECTS_DIR.resolve()) or not svg_dir.is_dir():
        print(f"未找到项目页面目录：{svg_dir}", file=sys.stderr)
        return 1
    svgs = sorted(p for p in svg_dir.glob("*.svg") if p.is_file())
    if not svgs:
        print(f"项目 svg_output/ 下没有 SVG 页面：{svg_dir}", file=sys.stderr)
        return 1

    title = args.title.strip() or f"{args.project} 页面预览"
    sections = []
    for p in svgs:
        try:
            raw = p.read_bytes()
        except OSError as exc:
            print(f"读取失败 {p.name}: {exc}", file=sys.stderr)
            return 1
        b64 = base64.b64encode(raw).decode("ascii")
        ratio = svg_dimensions(raw.decode("utf-8", errors="replace"))
        sections.append(
            f'<section class="slide"><div class="slide-label">{esc(p.stem)}</div>'
            f'<div class="slide-frame" style="aspect-ratio:{esc(ratio)}">'
            f'<img src="data:image/svg+xml;base64,{b64}" alt="{esc(p.stem)}"></div></section>'
        )

    name = args.output or f"{args.project}_pages_preview.html"
    out = (OUTPUT_DIR / Path(name).name).resolve()
    if not _is_within(out, OUTPUT_DIR.resolve()):
        print(f"输出必须位于 official-docs/output/ 内：{OUTPUT_DIR}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page_html(title, len(svgs), "\n".join(sections)), encoding="utf-8")
    print(f"已生成预览页（{len(svgs)} 页）：{out}")
    print("提示：dsh 场景预览页已在会话工作区内，向用户展示上述路径即可（浏览器打开确认首页）。")
    return 0


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _page_html(title: str, count: int, sections: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #f4f7fb; color: #172236; }}
header {{ position: sticky; top: 0; z-index: 2; padding: 10px 22px; background: #0b1f3a; color: #fff; font-size: 13px;
  display: flex; justify-content: space-between; gap: 10px; }}
header .meta {{ color: #9fb3d1; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 22px 16px 48px; }}
.slide {{ margin: 0 0 26px; }}
.slide-label {{ font-size: 12.5px; font-weight: 700; color: #40506b; margin: 0 0 7px 2px; }}
.slide-frame {{ background: #fff; border: 1px solid #dce4ef; border-radius: 10px; overflow: hidden;
  box-shadow: 0 6px 22px rgba(11,31,58,.07); }}
.slide-frame img {{ display: block; width: 100%; height: 100%; }}
footer {{ text-align: center; color: #8a97ab; font-size: 11.5px; padding: 10px 0 26px; }}
</style>
</head>
<body>
<header><span>{esc(title)}</span><span class="meta">共 {count} 页 · 深知可信PPT 页面预览</span></header>
<main>
{sections}
</main>
<footer>预览为页面设计稿（SVG）等比缩放，最终以导出的 .pptx 为准；内容由 AI 生成，仅供参考。</footer>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
