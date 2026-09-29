#!/usr/bin/env python3
"""把深知可信搜索 deep-query/v3（深度搜索）的返回转换成与 dkag_search.py --clean 同构的形态，
供本 Skill 全部下游流程复用（素材分类、研究资料、溯源 JSON、核验报告）。

背景（3.7.5）：首轮检索改用深度搜索做广度召回——分 3 路（政策依据型/数据支撑型/参考案例型），
每路一次深度搜索，query 用「对象+关注方向」句式（不列举具体信息需求）；拿到材料后，
缺的文号/政策原文/快照由可信搜索（trusted_search / dkag_search）按缺口补搜。

为什么转 clean 形态：深度搜索返回的文章字段（文章标题/数据源/发布日期/办理地域/源网址/段落）
与脚本通道 `--clean` 同构。真实 deep-query/v3 返回含快照（screenShotPath）、段落
标题（标题链数据源）、发布日期可信度，本脚本如实保留；**独立的"文号"字段缺失**
（政策文号在段落内容中），政策依据型靠可信搜索补搜的 policyFiles 匹配文号。
本脚本把 `data.searches[].result` 与 `data.common_articles` 按源网址/标题去重摊平，
段落重新编号（id 全局自增与 `--clean` 一致），段落内容去 HTML 标签后保留。

字段映射：
  data.searches[].result[] + data.common_articles[] → 顶层 articles
    （searches 为服务端按地域拆的子查询分组，摊平时不丢失：每篇附带 deep_group 字段，
     值为所属子查询的 query，供溯源 JSON 整理时参考）
  文章标题 / 数据源 / 发布日期 / 办理地域 / 源网址 / 段落 原样保留
  段落[{id, 标题, 内容, ...}] → 段落[{id, 标题, 内容}]（内容去 HTML 标签；标题保留为标题链数据源）

用法：
  python3 scripts/deep_convert.py official-docs/search-results/deep_<路名>.json \
      --area 北京市 --purpose "政策依据型" \
      --output official-docs/search-results/result_deep_<路名>.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"


HTML_ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"), ("&quot;", '"'),
                 ("&nbsp;", " "), ("&#39;", "'"))


def clean_text(text) -> str:
    """去首尾空白并压缩内部空白。"""
    return " ".join(str(text or "").split())


def strip_html(text) -> str:
    """去掉深度搜索段落内容里的 HTML 标签并反转义实体（真实返回含表格等标签）。"""
    out = re.sub(r"<[^>]+>", " ", str(text or ""))
    for a, b in HTML_ENTITIES:
        out = out.replace(a, b)
    return " ".join(out.split())


def first_value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def extract_articles(data) -> list:
    """从深度搜索返回中取出文章列表（searches[].result + common_articles，去重摊平）。"""
    body = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
    seen = set()
    out: list = []

    def add(article, group: str = "") -> None:
        if not isinstance(article, dict):
            return
        title = clean_text(first_value(article, "文章标题", "title"))
        url = clean_text(first_value(article, "源网址", "url"))
        key = url or title
        if not key or key in seen:
            return
        seen.add(key)
        item = dict(article)
        if group:
            item["deep_group"] = group
        out.append(item)

    for search in body.get("searches") or []:
        if not isinstance(search, dict):
            continue
        group = clean_text(search.get("query") or "")
        for article in search.get("result") or []:
            add(article, group)
    for article in body.get("common_articles") or []:
        add(article)
    return out


def convert(data, area: str, purpose: str) -> dict:
    raw_articles = extract_articles(data)
    articles: list = []
    para_id = 1

    for raw in raw_articles:
        title = clean_text(first_value(raw, "文章标题"))
        if not title:
            continue
        source_url = clean_text(first_value(raw, "源网址", "url"))
        paragraphs: list = []
        for para in raw.get("段落") or []:
            if not isinstance(para, dict):
                continue
            # 真实 deep-query/v3 返回的段落内容含 HTML 标签（表格等），清洗为纯文本
            content = strip_html(para.get("内容") or para.get("content"))
            if not content:
                continue
            paragraphs.append({"id": para_id, "标题": clean_text(para.get("标题") or para.get("title") or ""),
                               "内容": content})
            para_id += 1

        article = {
            "文章标题": title,
            "发布日期": clean_text(first_value(raw, "发布日期", "date")),
            "数据源": clean_text(first_value(raw, "数据源", "source")) or "未知来源",
            "段落": paragraphs,
        }
        if source_url:
            article["源网址"] = source_url
            article["原文链接"] = source_url
        region = clean_text(first_value(raw, "办理地域", "area"))
        if region:
            article["办理地域"] = region
        # 真实返回含发布日期可信度与快照（screenShotPath）——如实保留；
        # 独立"文号"字段仍缺失（文号在段落内容中，政策依据型用补搜的 policyFiles 匹配）
        confidence = clean_text(first_value(raw, "发布日期可信度"))
        if confidence:
            article["发布日期可信度"] = confidence
        snapshot = clean_text(first_value(raw, "screenShotPath", "快照链接"))
        if snapshot:
            article["快照链接"] = snapshot
        if raw.get("deep_group"):
            article["deep_group"] = raw["deep_group"]
        articles.append(article)

    knowledge_base = first_value(data, "knowledgeBase", "knowledge_base_url") if isinstance(data, dict) else ""
    raw_query = first_value(data, "query") if isinstance(data, dict) else ""
    search_meta = {
        "query": raw_query,
        # purpose 兜底（3.7.6 修复）：--purpose 为空时用该路 query 兜底——
        # 留空会导致合并产物文章"搜索目的"缺失，溯源分组键退化成地域碎片。
        "purpose": purpose or raw_query,
        "area": area,
        "time": "",
        "requested_time": "",
        "time_ignored": False,
        "policy": True,
        "full": False,
        "clean": True,
        "segmentCount": 0,
        "simplified": False,
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
        "knowledgeBase_note": "深度搜索返回，knowledgeBase 若有则复制；多数深度搜索不返回该字段。",
        "policyFiles": [],
        "search_meta": search_meta,
        "channel": "deep",
        "deep_note": ("深度搜索首轮召回产物：含快照/段落标题/发布日期可信度，但无独立文号字段，"
                      "政策依据型需用可信搜索补搜（policyFiles 匹配文号），数据/案例视缺口决定是否补搜。"),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="深度搜索（deep-query/v3）返回 → 与 dkag_search.py --clean 同构的形态")
    parser.add_argument("input", help="深度搜索完整返回 JSON 文件（deep-query/v3 形态）")
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
        raise SystemExit(f"错误：{raw.name} 不是合法 JSON（{exc}）。请把深度搜索返回**完整原样**保存为文件。") from None

    converted = convert(data, args.area, args.purpose)
    articles = converted["articles"]
    if not articles:
        raise SystemExit(
            f"错误：从 {raw.name} 中解析出 0 篇材料，已停止（不写空结果）。"
            "请确认保存的是 deep-query/v3 的完整返回（data.searches[].result 或 data.common_articles 至少其一非空）。")

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
    print(f"✓ 深度搜索转换完成：{len(articles)} 篇材料（{with_doc} 篇带段落）→ {out}")
    print("  产物与 dkag_search.py --clean 同构；深度搜索含快照/段落标题，缺独立文号字段，"
          "政策依据型按缺口用可信搜索补搜（policyFiles 匹配文号）。")


if __name__ == "__main__":
    main()
