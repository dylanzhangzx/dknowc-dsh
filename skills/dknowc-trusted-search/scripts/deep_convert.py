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

from run_paths import RunPathError, resolve_input_path, resolve_output_path, resolve_run_dir

DEEP_CHANNEL = "深知深度搜索"


def _paragraphs(article: dict) -> list:
    """取文章段落文本列表（兼容 段落[].内容 / 内容 / content 等形态）。"""
    paragraphs = article.get("段落") or article.get("paragraphs") or []
    chunks = []
    if isinstance(paragraphs, list):
        for p in paragraphs:
            if isinstance(p, dict):
                chunks.append(str(p.get("内容") or p.get("text") or p.get("content") or ""))
            else:
                chunks.append(str(p or ""))
    if not chunks:
        chunks.append(str(article.get("内容") or article.get("content") or ""))
    return [c for c in chunks if c.strip()]


def _paragraph_text(article: dict) -> str:
    return "\n".join(_paragraphs(article)).strip()


def _is_version_index_text(text: str) -> bool:
    """判断是否为政策库版本索引元数据段（不是法规正文）。

    与渲染层 clean_paragraph_noise 的口径一致：段首为“生效时间：”且含“所属地域：”，
    或仅有“修订说明：……相关文件有下面这些版本”的版本清单。
    """
    value = (text or "").strip()
    if value.startswith("生效时间：") and "所属地域：" in value:
        return True
    if value.startswith("修订说明") and "相关文件有下面这些版本" in value:
        return True
    return False


def _mark_citability(article: dict) -> None:
    """给文章补“可引用”判断（1.7.3）。

    政策库对多版本法规常返回 policy 版本索引记录：标题命中，但段落只有
    生效时间/失效日期/修订说明，没有条文正文。此类记录只能当版本线索，
    不能作为正文依据；在此显式标记，供 Agent 与渲染层统一识别。
    """
    texts = _paragraphs(article)
    # 逐段判断：只要有一段不是版本索引元数据，就视为有正文（多段材料不能因首段是元数据而误杀）
    substantive = any(not _is_version_index_text(t) for t in texts)
    if substantive:
        article["可引用"] = True
        return
    article["可引用"] = False
    if str(article.get("文章类型") or "").strip() == "policy" or any(
            _is_version_index_text(t) for t in texts):
        article["材料性质"] = "版本索引"
        article["不可引用原因"] = "policy 版本索引记录，仅含生效时间/修订说明，无正文段落"
    else:
        article["材料性质"] = "无正文"
        article["不可引用原因"] = "接口未返回可引用的正文段落"


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
        _mark_citability(out)
        articles.append(out)

    for search in searches:
        area_list = [str(a).strip() for a in (search.get("areas") or []) if str(a).strip()]
        areas = "、".join(area_list)
        query = str(search.get("query") or "").strip()
        # 地域已写进 query 时不再重复前缀（原会显示成"成都·成都 人才落户…"）
        area_in_query = bool(area_list) and all(a in query for a in area_list)
        label = f"{areas}·{query[:14]}" if areas and not area_in_query else query[:18]
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


def resolve_output(name: str, run_dir: Path | None) -> Path:
    if not Path(name).expanduser().is_absolute() and run_dir is None:
        raise RunPathError("相对 -o/--output 必须同时用 --run 指定运行目录")
    return resolve_output_path(name, run_dir, {".json"}, ".json", "deep_converted.json")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="深度搜索产物转换（v3 原始 → 可信同构通用形态）")
    parser.add_argument("input", help="deep_query.py --json-only 的落盘 JSON（run 目录内文件名或绝对路径）")
    parser.add_argument("--run", help="本次运行的独立目录（必须在 Skill 安装目录之外）")
    parser.add_argument("-o", "--output", default="deep_converted.json", help="输出文件名；相对名落在 --run 目录")
    args = parser.parse_args()

    try:
        run_dir = resolve_run_dir(args.run) if args.run else None
        src = resolve_input_path(args.input, run_dir, {".json"})
    except RunPathError as exc:
        raise SystemExit(f"错误：{exc}") from None
    payload = json.loads(src.read_text(encoding="utf-8"))
    if not (isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("searches"), list)):
        raise SystemExit("错误：输入不是深度搜索 v3 原始产物（缺 data.searches）——若已是通用形态无需转换，直接进 merge。")

    result = convert(payload)
    try:
        out = resolve_output(args.output, run_dir)
    except RunPathError as exc:
        raise SystemExit(f"错误：{exc}") from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = result["search_meta"]
    print(f"已转换：{src.name} → {out}")
    print(f"子查询 {meta['sub_queries']} 路 · 输出文章 {meta['articles']} 篇（通用形态，可直接进 merge_search_results.py）")


if __name__ == "__main__":
    main()
