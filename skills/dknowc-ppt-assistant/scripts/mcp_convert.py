#!/usr/bin/env python3
"""把 MCP「深知可信工作台」trusted_search（include_details=true 形态）的返回
转换成深知可信搜索 REST 接口的原始响应形态，供深知可信PPT 全部下游流程复用。

背景（3.7.3）：检测到宿主已连接 MCP「深知可信工作台」时，搜索走 MCP 通道
（免 API Key）。模型在对话层调用 MCP 工具后，把完整返回 JSON 保存到
official-docs/search-results/，再运行本脚本转换——转换产物与 trusted_search.py
直调 REST 的输出同构（content.data.检索文章 / policyFiles / knowledgeBase /
search_meta），内容包、合并 JSON 整理与溯源核验报告生成全部按现有流程执行。

字段映射：
  title → 文章标题            source → 数据源          date → 发布日期
  url   → 源网址              date_confidence → 发布日期可信度
  snapshot → screenShotPath
  segments[{title,content}] → 段落[{标题,内容}]（段落标题为标题链数据源；
    segments 缺失时用 paragraph 兜底构造无标题单段）
  doc_number → 同时写入文章级「文号」与反向构造 policyFiles[{title, writtenText}]
    （渲染器直接读文章级文号；MCP 侧已完成变体匹配，直接复用其结果）
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
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SEARCH_RESULTS_DIR = SKILL_ROOT / "official-docs" / "search-results"

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
            # 文号同时写入文章级（整理合并 JSON 时直接复制，免跨文件翻 policyFiles——
            # 实测模型做跨文件标题匹配会跳过，2026-09-21 中医药轮 34 条现成文号取 0）
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
