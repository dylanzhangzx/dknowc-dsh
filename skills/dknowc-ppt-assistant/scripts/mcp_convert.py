#!/usr/bin/env python3
"""历史工具：把 MCP「深知可信工作台」trusted_search（include_details=true 形态）的返回
转换成深知可信搜索 REST 接口的原始响应形态，供深知可信PPT 全部下游流程复用。

当前状态：素材检索统一走 trusted_search.py 脚本通道，本脚本随包保留、规则层不引用。
宿主 MCP 工具结果存在过期清理机制，大结果在对话层中转的可靠性不足，因此不作为检索通道；
若后续宿主工具能力升级，可由技术侧评估后重新启用。

字段映射（通道启用时适用）：
  title → 文章标题            source → 数据源          date → 发布日期
  url   → 源网址              date_confidence → 发布日期可信度
  snapshot → screenShotPath
  segments[{title,content}] → 段落[{标题,内容}]（段落标题为标题链数据源；
    segments 缺失时用 paragraph 兜底构造无标题单段）
  doc_number → 同时写入文章级「文号」与反向构造 policyFiles[{title, writtenText}]
    （渲染器直接读文章级文号；MCP 侧已完成变体匹配，直接复用其结果）
  内容中的 ＆lt;/＆gt;/＆amp;/＆quot; HTML 实体顺手反转义（MCP 透传未清洗）。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 cwd
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"

HTML_ENTITIES = (("＆lt;", "<"), ("＆gt;", ">"), ("＆amp;", "&"), ("＆quot;", '"'),
                 ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"'))


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


def parse_segments(material: dict) -> list:
    """segments → 段落[{标题,内容}]。兼容数组与（历史）字符串形态；缺失时用 paragraph 兜底。"""
    segments = material.get("segments")
    if isinstance(segments, str) and segments.strip().startswith("["):
        try:  # 历史形态容错：repr 字符串
            import ast
            segments = ast.literal_eval(segments)
        except (ValueError, SyntaxError):
            segments = None
    paragraphs = []
    if isinstance(segments, list) and segments:
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            title = clean_text(first_value(seg, "title", "标题"))
            content = clean_text(first_value(seg, "content", "内容"))
            if content:
                paragraphs.append({"标题": title, "内容": content})
    if not paragraphs:
        fallback = clean_text(first_value(material, "paragraph"))
        if fallback:
            paragraphs.append({"标题": "", "内容": fallback})
    return paragraphs


def convert(data: dict, area: str, purpose: str) -> dict:
    materials = data.get("materials") or []
    articles, policy_files = [], []
    seen_pf = set()
    for material in materials:
        if not isinstance(material, dict):
            continue
        title = clean_text(first_value(material, "title", "文章标题"))
        if not title:
            continue
        article = {
            "文章标题": title,
            "数据源": clean_text(first_value(material, "source", "数据源")),
            "发布日期": clean_text(first_value(material, "date", "发布日期")),
            "发布日期可信度": clean_text(first_value(material, "date_confidence", "发布日期可信度")),
            "源网址": clean_text(first_value(material, "url", "源网址")),
            "段落": parse_segments(material),
        }
        snapshot = clean_text(first_value(material, "snapshot", "screenShotPath", "快照链接"))
        if snapshot:
            article["screenShotPath"] = snapshot
        doc_number = clean_text(first_value(material, "doc_number", "文号"))
        if doc_number:
            # 文号同时写入文章级（整理合并 JSON 时直接复制，免跨文件回查 policyFiles——
            # 跨文件标题匹配易被跳过，文章级字段最稳定）
            article["文号"] = doc_number
        if purpose:
            # 搜索条件写文章级：合并 JSON 时材料自带检索分组（专库 tabs 数据源）
            article["搜索条件"] = purpose
        articles.append(article)
        if doc_number and title not in seen_pf:
            seen_pf.add(title)
            policy_files.append({"title": title, "writtenText": doc_number,
                                 "sourceUrl": article["源网址"] or None,
                                 "createDate": article["发布日期"] or None,
                                 "createDateReliability": article["发布日期可信度"] or None})

    mcp_meta = data.get("search_meta") if isinstance(data.get("search_meta"), dict) else {}
    payload = {
        "query": first_value(data, "query") or mcp_meta.get("query", ""),
        "eff_time": [mcp_meta.get("eff_time", "")],
        "service_area": [area or first_value(data, "service_area")],
        "knowBase": bool(mcp_meta.get("know_base", True)),
        "policy": True,
        "return_full_content": False,
        "segmentCount": int(mcp_meta.get("segment_count", 2) or 2),
        "simplified": bool(mcp_meta.get("simplified", False)),
    }
    knowledge_base = first_value(data, "knowledge_base_url", "knowledgeBase")
    content = {"data": {"检索文章": articles, "policyFiles": policy_files,
                        "办理地域": area, "用户问题": payload["query"]}}
    if knowledge_base:
        content["knowledgeBase"] = knowledge_base
    return {
        "search_meta": {
            "query": payload["query"], "area": area, "time": mcp_meta.get("eff_time", ""),
            "requested_time": "", "time_ignored": False, "policy": True, "full": False,
            "clean": False, "segmentCount": payload["segmentCount"],
            "simplified": payload["simplified"], "MaterialLength": "",
            "searchType": [], "searchChannel": [], "purpose": purpose,
            "channel": "mcp",
            "knowledgeBase": knowledge_base,
        },
        "knowledgeBase": knowledge_base,
        "content": content,
        "request_body": payload,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="MCP trusted_search 返回 → REST 原始形态（供全下游流程复用）")
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
    data = json.loads(raw.read_text(encoding="utf-8"))

    out_name = args.output or (raw.stem + "_converted.json")
    out = Path(out_name).expanduser()
    if not out.is_absolute():
        out = (SEARCH_RESULTS_DIR / out.name).resolve()
    try:
        out.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise SystemExit(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}") from None

    converted = convert(data, args.area, args.purpose)
    articles = converted["content"]["data"]["检索文章"]
    out.write_text(json.dumps(converted, ensure_ascii=False, indent=2), encoding="utf-8")
    with_doc = sum(1 for a in articles if a["段落"])
    print(f"✓ 转换完成：{len(articles)} 篇材料（{with_doc} 篇带段落）、"
          f"{len(converted['content']['data']['policyFiles'])} 条文号 → {out}")
    print("  转换产物与 trusted_search.py 直调 REST 同构，内容包/合并 JSON/核验报告按现有流程执行。")


if __name__ == "__main__":
    main()
