#!/usr/bin/env python3
"""把 MCP「深知可信工作台」trusted_search（include_details=true 形态）的返回
转换成与深知可信搜索脚本 `scripts/dkag_search.py --clean` **完全同构**的形态，
供本 Skill 全部下游流程复用。

背景（3.7.3）：检测到宿主已连接 MCP「深知可信工作台」时，搜索走 MCP 通道
（免 API Key）。模型在对话层调用 MCP 工具后，把完整返回 JSON 保存到
official-docs/search-results/，再运行本脚本转换。

为什么必须与 `--clean` 同构：脚本通道的下游（模型整理溯源
JSON、`merge_search_results.py`、`source_note_html.py` 的历史索引回填）都按
`--clean` 的字段名读取——文章在**顶层 `articles`**、快照字段名是**`快照链接`**、
段落带自增 `id`。此前本脚本输出的是 REST 原始形态（`content.data.检索文章`），
导致 MCP 通道产物在下游：文章数组读空（被误判"未检索到相关文章"）、快照链接
整条丢失（`快照链接` 键不存在，而 `source_note_html.py` 只认这个键名）。
现直接输出 `--clean` 形态，文档只描述一种形态。

字段映射：
  title → 文章标题            source → 数据源          date → 发布日期
  url   → 源网址 / 原文链接   date_confidence → 发布日期可信度
  snapshot → 快照链接
  segments[{title,content}] → 段落[{id, 标题, 内容}]（段落标题为标题链数据源；
    segments 缺失时用 paragraph 兜底构造无标题单段；id 全局自增，同 --clean）
  doc_number → 文章级 `文号`（标准格式，供整理溯源 JSON 时直接复制）+
    顶层 `policyFiles[{title, writtenText}]`（与 --clean 的接口返回一致）
  内容中的 ＆lt;/＆gt;/＆amp;/＆quot; HTML 实体顺手反转义（MCP 透传未清洗）。

用法：
  python3 scripts/mcp_convert.py official-docs/search-results/mcp_raw.json \
      --area 北京市 --purpose "搜索目的" \
      --output official-docs/search-results/result_xxx.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SEARCH_RESULTS_DIR = SKILL_ROOT / "official-docs" / "search-results"

HTML_ENTITIES = (("＆lt;", "<"), ("＆gt;", ">"), ("＆amp;", "&"), ("＆quot;", '"'),
                 ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"'))

KNOWLEDGE_BASE_NOTE = ("知识专库链接来自深知可信搜索接口返回的 knowledgeBase；"
                       "MCP 通道由 mcp_convert.py 冗余复制到顶层，与 --clean 口径一致。")


def clean_text(text: str) -> str:
    """反转义 MCP 透传内容中的 HTML 实体（全角/半角形式）并去首尾空白。"""
    out = str(text or "")
    for a, b in HTML_ENTITIES:
        out = out.replace(a, b)
    return out.strip()


def first_value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def extract_materials(data) -> list:
    """从 MCP 返回中取出 materials 数组，兼容几种常见包裹形态。

    直接形态：{"materials": [...]}
    带信封：{"data": {"materials": [...]}}、{"content": [{"type": "text", "text": "{...}"}]}
    纯数组：[{...}, {...}]
    取不到时返回空列表，由调用方报错（不得静默产出 0 篇继续往下走）。
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    materials = data.get("materials")
    if isinstance(materials, list):
        return materials

    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("materials"), list):
        return inner["materials"]

    # MCP 工具信封：content 数组里放 JSON 字符串
    content = data.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text") or block.get("content")
            if isinstance(text, str) and text.strip().startswith(("{", "[")):
                try:
                    return extract_materials(json.loads(text))
                except json.JSONDecodeError:
                    continue
    return []


def parse_segments(material: dict, start_id: int) -> tuple[list, int]:
    """segments → 段落[{id,标题,内容}]，与 --clean 一致。

    兼容数组与（历史）字符串形态；缺失时用 paragraph 兜底构造无标题单段。
    返回（段落列表, 下一个可用 id）。
    """
    segments = material.get("segments")
    if isinstance(segments, str) and segments.strip().startswith("["):
        try:  # 历史形态容错：repr 字符串
            import ast
            segments = ast.literal_eval(segments)
        except (ValueError, SyntaxError):
            segments = None

    paragraphs: list = []
    next_id = start_id
    if isinstance(segments, list) and segments:
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            title = clean_text(first_value(seg, "title", "标题"))
            content = clean_text(first_value(seg, "content", "内容"))
            if content:
                paragraphs.append({"id": next_id, "标题": title, "内容": content})
                next_id += 1
    if not paragraphs:
        fallback = clean_text(first_value(material, "paragraph"))
        if fallback:
            paragraphs.append({"id": next_id, "标题": "", "内容": fallback})
            next_id += 1
    return paragraphs, next_id


def convert(data, area: str, purpose: str) -> dict:
    materials = extract_materials(data)
    articles: list = []
    policy_files: list = []
    seen_pf = set()
    para_id = 1

    for material in materials:
        if not isinstance(material, dict):
            continue
        title = clean_text(first_value(material, "title", "文章标题"))
        if not title:
            continue
        paragraphs, para_id = parse_segments(material, para_id)
        source_url = clean_text(first_value(material, "url", "源网址", "sourceUrl"))
        article = {
            # 字段名与顺序对齐 --clean 白名单口径
            "文章标题": title,
            "发布日期": clean_text(first_value(material, "date", "发布日期")),
            "数据源": clean_text(first_value(material, "source", "数据源")),
            "段落": paragraphs,
        }
        if source_url:
            article["源网址"] = source_url
            article["原文链接"] = source_url
        date_confidence = clean_text(first_value(material, "date_confidence", "发布日期可信度"))
        if date_confidence:
            article["发布日期可信度"] = date_confidence
        snapshot = clean_text(first_value(material, "snapshot", "screenShotPath", "快照链接"))
        if snapshot:
            # 键名必须是"快照链接"：source_note_html.py 读历史索引时只认这个键
            article["快照链接"] = snapshot
        doc_number = clean_text(first_value(material, "doc_number", "文号"))
        if doc_number:
            # 文号直写文章级（MCP 通道增量）：整理溯源 JSON 时直接复制，
            # 免跨文件翻 policyFiles——实测模型做跨文件标题匹配会跳过
            article["文号"] = doc_number
        articles.append(article)

        if doc_number and title not in seen_pf:
            seen_pf.add(title)
            policy_files.append({"title": title, "writtenText": doc_number,
                                 "sourceUrl": source_url or None,
                                 "createDate": article["发布日期"] or None,
                                 "createDateReliability": date_confidence or None})

    raw_meta = {}
    if isinstance(data, dict) and isinstance(data.get("search_meta"), dict):
        raw_meta = data["search_meta"]
    query = first_value(data, "query") if isinstance(data, dict) else ""
    query = query or raw_meta.get("query", "")
    knowledge_base = first_value(data, "knowledge_base_url", "knowledgeBase") if isinstance(data, dict) else ""

    search_meta = {
        "query": query,
        "purpose": purpose,
        "area": area or (first_value(data, "service_area") if isinstance(data, dict) else ""),
        "time": raw_meta.get("eff_time", ""),
        "requested_time": "",
        "time_ignored": False,
        "policy": True,
        "full": False,
        "clean": True,
        "segmentCount": int(raw_meta.get("segment_count", 2) or 2),
        "simplified": bool(raw_meta.get("simplified", False)),
        "MaterialLength": "",
        "searchType": [],
        "searchChannel": [],
        "knowledgeBase": knowledge_base,
    }

    return {
        "cleaned": True,
        "articles": articles,
        "total_articles": len(articles),
        "total_paragraphs": para_id - 1,
        "knowledgeBase": knowledge_base,
        "knowledgeBasePath": "content.knowledgeBase",
        "knowledgeBase_note": KNOWLEDGE_BASE_NOTE,
        "policyFiles": policy_files,
        "search_meta": search_meta,
        # 通道标记（--clean 无此键，属增量）：便于排查本文件出自哪条通道
        "channel": "mcp",
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="MCP trusted_search 返回 → 与 dkag_search.py --clean 同构的形态（供全下游流程复用）")
    parser.add_argument("input", help="MCP trusted_search 完整返回 JSON 文件（materials 形态）")
    parser.add_argument("--area", default="", help="本次检索地域（写入 search_meta.area）")
    parser.add_argument("--purpose", default="", help="搜索方案中的搜索目的（内部字段，不向用户展示）")
    parser.add_argument("--output", "-o", help="输出文件名，默认写入 official-docs/search-results/")
    args = parser.parse_args()

    raw = Path(args.input).expanduser()
    if not raw.is_absolute():
        raw = (SEARCH_RESULTS_DIR / raw.name).resolve()
    if not raw.is_file():
        raise SystemExit(f"错误：输入文件不存在: {raw}")
    try:
        data = json.loads(raw.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"错误：{raw.name} 不是合法 JSON（{exc}）。请把 MCP 工具返回**完整原样**保存为文件——"
            "内容里若含 ASCII 双引号，必须用 json.dump 写出，不要手工拼接字符串。") from None

    converted = convert(data, args.area, args.purpose)
    articles = converted["articles"]
    if not articles:
        raise SystemExit(
            f"错误：从 {raw.name} 中解析出 0 篇材料，已停止（不写空结果，避免下游把「没取到材料」"
            "当成「检索到 0 篇」继续走）。请确认保存的是 MCP trusted_search 的完整返回"
            "（顶层含 materials 数组，且 include_details=true）。")

    out_name = args.output or (raw.stem + "_converted.json")
    out = Path(out_name).expanduser()
    if not out.is_absolute():
        out = (SEARCH_RESULTS_DIR / out.name).resolve()
    try:
        out.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise SystemExit(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}") from None

    out.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    with_doc = sum(1 for a in articles if a["段落"])
    with_snap = sum(1 for a in articles if a.get("快照链接"))
    print(f"✓ 转换完成：{len(articles)} 篇材料（{with_doc} 篇带段落、{with_snap} 篇带快照）、"
          f"{len(converted['policyFiles'])} 条文号 → {out}")
    print("  产物与 dkag_search.py --clean 同构（顶层 articles / 快照链接 / 段落 id），"
          "研究资料、溯源 JSON、核验报告按现有流程执行。")


if __name__ == "__main__":
    main()
