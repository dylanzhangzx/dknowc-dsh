#!/usr/bin/env python3
"""深度搜索产物转换层：v3 原始形态 → 可信搜索同构形态（1.5.1）。

输入：deep_query.py --json-only 落盘的原始产物
  {"data": {"searches": [{"query", "areas", "result": [文章…]}], "common_articles": [文章…]}}
输出：与 trusted_search.py 产物同构、可直接进 merge_search_results.py 的通用形态
  {"content": {"data": {"检索文章": [文章…（含 搜索条件 分组 + 检索通道=深知深度搜索）], "policyFiles": […]}}}

设计取向（2026-10-15，接口适配走独立转换层）：
- 深度搜索接口若调整，改动面收敛在本文件；merge/渲染等下游只处理通用形态；
- 原始与转换两份产物并存，可对账、可 diff；
- 外部复用方（如豆包配套 skill 移植）只依赖通用形态，无需理解深搜嵌套结构。
注意：字段原样透传（含段落内 <table> 等 HTML 标签——渲染层白名单清洗负责展示，
本层不做任何剥标签处理）。

用法：
  python3 scripts/deep_convert.py <deep_query 产物.json> [-o 转换产物名.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
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

DEEP_CHANNEL = "深知深度搜索"


def convert(payload: dict) -> dict:
    """摊平 v3 嵌套结构为通用检索文章列表（附分组与通道标记）。"""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    searches = [s for s in (data.get("searches") or []) if isinstance(s, dict)]
    articles: list = []
    seen: set = set()

    def _add(article, search_key: str) -> None:
        if not isinstance(article, dict):
            return
        # 按源网址（次选标题）去重：多子查询重复召回只保留先入（merge 侧仍有二次去重）
        key = str(article.get("源网址") or article.get("文章标题") or "")
        if key and key in seen:
            return
        if key:
            seen.add(key)
        out = dict(article)  # 字段原样透传
        if search_key and not out.get("搜索条件"):
            out["搜索条件"] = search_key
        if not out.get("检索通道"):
            out["检索通道"] = DEEP_CHANNEL
        articles.append(out)

    for search in searches:
        areas = "、".join(str(a) for a in (search.get("areas") or []))
        query = str(search.get("query") or "").strip()
        label = f"{areas}·{query[:14]}" if areas else query[:18]
        for article in search.get("result") or []:
            _add(article, label)
    for article in data.get("common_articles") or []:
        # 多查询公共文章给独立分组名（空 key 落不进任何分组 tab）
        _add(article, "多查询公共")

    policy_files = [p for p in (data.get("policyFiles") or []) if isinstance(p, dict)]
    return {
        "search_meta": {
            "deep_converted": True,
            "sub_queries": len(searches),
            "articles": len(articles),
        },
        "content": {"data": {"检索文章": articles, "policyFiles": policy_files}},
    }


def resolve_output(name: str) -> Path:
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = (SEARCH_RESULTS_DIR / path.name).resolve()
    try:
        path.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise SystemExit(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}") from None
    return path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="深度搜索产物转换（v3 原始 → 可信同构通用形态）")
    parser.add_argument("input", help="deep_query.py --json-only 的落盘 JSON（official-docs/search-results/ 内文件名或绝对路径）")
    parser.add_argument("-o", "--output", default="deep_converted.json", help="输出文件名（official-docs/search-results/ 内），默认 deep_converted.json")
    args = parser.parse_args()

    src = Path(args.input).expanduser()
    if not src.is_absolute():
        src = (SEARCH_RESULTS_DIR / src.name).resolve()
    if not src.is_file():
        raise SystemExit(f"错误：输入文件不存在: {src}")
    payload = json.loads(src.read_text(encoding="utf-8"))
    if not (isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("searches"), list)):
        raise SystemExit("错误：输入不是深度搜索 v3 原始产物（缺 data.searches）——若已是通用形态无需转换，直接进 merge。")

    result = convert(payload)
    out = resolve_output(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = result["search_meta"]
    print(f"已转换：{src.name} → {out}")
    print(f"子查询 {meta['sub_queries']} 路 · 输出文章 {meta['articles']} 篇（通用形态，可直接进 merge_search_results.py）")


if __name__ == "__main__":
    main()
