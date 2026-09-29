#!/usr/bin/env python3
"""多路检索结果合并（可信搜索/深度搜索混合输入 → 渲染器统一形态）。

背景（1.4.0）：复杂问题按复杂度分级可能产生多路产物——深度搜索（deep_query.py，
data.searches[] 形态）多路 + 可信搜索补搜（trusted_search.py，content.data.检索文章
形态）多路。渲染脚本 render_trace_html.py 只接受单个 input_json，此前需 Agent 手工
合并（实测易错）。本脚本把任意多路、跨通道产物程序化合并为渲染器可直接消费的单 JSON：

- **合并式去重**（对齐公文写作 3.7.5）：按"规范化标题 + 源网址"双键判同一材料——
  标题去空白/全角/开头"关于印发/关于"/结尾公文后缀词；同一材料**合并段落**（段落级
  去重，保留各检索召回的不同段落）与**字段取并集**（保留非空字段、合并搜索条件标记）；
  不再按标题整体丢弃后篇。
- **深度产物转换**：deep_query 的 data.searches[].result + data.common_articles 摊平为
  检索文章形态（子查询 query 作为默认搜索条件分组），与可信产物统一。
- **policyFiles 收集**：各可信产物携带的 policyFiles 合并去重（writtenText+title 双键），
  写入合并产物 content.data.policyFiles（文号匹配数据源）。
- **分组标签**：每路通过 --search-key 指定该路的搜索条件（核验报告"检索分组 tabs"
  与过程回顾按此分组）；未指定时可信产物默认"本次检索"、深度产物用子查询。
- **显式材料编号**（1.4.0 追加）：合并产物的每篇材料带 `编号` = 它在合并结果中的
  1-based 序号；答案角标 `[n]` 的 n 就用这个编号（渲染器优先读显式编号，不再依赖
  数组位置）。**写答案时读 `编号` 字段，不要按"某一路材料清单里的第几条"编号。**

用法：
  python3 scripts/merge_search_results.py \
      --input official-docs/search-results/route1.json --search-key "政策依据路" \
      --input official-docs/search-results/route2.json --search-key "数据口径路" \
      --output official-docs/search-results/merged_all.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

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

# 公文标题前后缀归一（合并去重用）
TITLE_PREFIX = ("关于印发", "关于", "印发", "发布", "印发《")
TITLE_SUFFIX = ("办法的通知", "办法", "实施细则的通知", "实施细则", "意见的通知",
                "意见", "规定的通知", "规定", "公告", "的通知")


def _norm_title(value: Any) -> str:
    """标题归一：全半角/大小写、去空白与书名号，去公文前后缀（变体判同一主体）。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）\"'“”‘’]", "", text)
    text = re.sub(r"\s+", "", text)
    for prefix in TITLE_PREFIX:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for suffix in TITLE_SUFFIX:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _first_value(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _dedupe_paragraphs(paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """段落级去重：按 id 或内容（归一后）去重，保留顺序。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for p in paragraphs:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        content = str(p.get("内容") or p.get("content") or "").strip()
        key = f"id:{pid}" if pid else f"c:{re.sub(r'\\s+', '', content)}"
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(p)
    return out


def _merge_article(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """同材料合并：段落并集 + 字段取并集（非空优先）+ 搜索条件合并。"""
    para_key = "段落" if "段落" in target or "段落" in incoming else "paragraphs"
    merged_paras = list(target.get(para_key) or []) + list(incoming.get(para_key) or [])
    target[para_key] = _dedupe_paragraphs(merged_paras)
    for key, value in incoming.items():
        if key == para_key:
            continue
        if value not in (None, "", [], {}):
            if key not in target or target[key] in (None, "", [], {}):
                target[key] = value
    # 搜索条件（分组标签）：**不拼接**，保留首路标签作为分组归属。
    # 旧实现把两路标签拼成 "上海市落户政策、上海：人才引进申办条件" 这类组合标签，
    # 会把 7 路撑成 10 个分组，过程回顾条的"检索 N 次"随之虚高，材料专库也出现怪分组
    # （2026-09-28 WB 实测：实际 7 路、报告显示 10 次）。并集信息不丢，另存 搜索条件全部。
    for key in ("搜索条件", "search_key"):
        cur = str(target.get(key) or "").strip()
        inc = str(incoming.get(key) or "").strip()
        if not cur:
            if inc:
                target[key] = inc
            continue
        if inc and inc != cur:
            all_key = f"{key}全部"
            vals = list(target.get(all_key) or [cur])
            if inc not in vals:
                vals.append(inc)
            target[all_key] = vals


def _to_article(item: Dict[str, Any], default_key: str = "") -> Dict[str, Any]:
    """把深度产物条目/可信产物条目归一为检索文章字段（渲染器 source_from_article 契约）。"""
    article = {
        "文章标题": _first_value(item, "文章标题", "title", "标题"),
        "数据源": _first_value(item, "数据源", "source"),
        "发布日期": _first_value(item, "发布日期", "date"),
        "发布日期可信度": _first_value(item, "发布日期可信度", "date_confidence"),
        "源网址": _first_value(item, "源网址", "url", "原文链接"),
        "段落": item.get("段落") if isinstance(item.get("段落"), list) else
               [{"内容": str(item.get("内容") or item.get("paragraph") or "").strip()}] if (item.get("内容") or item.get("paragraph")) else [],
    }
    for snap_key in ("screenShotPath", "快照链接", "snapshot"):
        snap = _first_value(item, snap_key)
        if snap:
            article["screenShotPath"] = snap
            break
    if _first_value(item, "文号", "doc_number"):
        article["文号"] = _first_value(item, "文号", "doc_number")
    key = _first_value(item, "搜索条件", "search_key", "deep_group") or default_key
    if key:
        article["搜索条件"] = key
    return article


def _collect_route(input_path: Path, search_key: str,
                   articles: List[Dict[str, Any]], policy_files: List[Dict[str, Any]]) -> None:
    """处理一路输入：可信形态（content.data.检索文章）或深度形态（data.searches）。"""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    policy_holder = data.get("content") if isinstance(data.get("content"), dict) else data
    pf = (policy_holder.get("data") or {}).get("policyFiles") if isinstance(policy_holder.get("data"), dict) else []
    for p in pf or []:
        if isinstance(p, dict):
            policy_files.append(dict(p))

    # 可信搜索形态
    search_articles = (policy_holder.get("data") or {}).get("检索文章")
    if isinstance(search_articles, list):
        for item in search_articles:
            if isinstance(item, dict):
                articles.append(_to_article(item, search_key or "本次检索"))
        return

    # 深度搜索形态（data.searches[].result + common_articles）
    d = data.get("data") if isinstance(data.get("data"), dict) else {}
    searches = [s for s in (d.get("searches") or []) if isinstance(s, dict)]
    for s in searches:
        sub_query = str(s.get("query") or s.get("标题") or "").strip()
        key = search_key or (f"深度-{sub_query}" if sub_query else "深度搜索")
        for item in s.get("result") or []:
            if isinstance(item, dict):
                articles.append(_to_article(item, key))
    for item in d.get("common_articles") or []:
        if isinstance(item, dict):
            articles.append(_to_article(item, search_key or "多查询公共"))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="多路检索结果合并（可信/深度混合 → 渲染器统一形态）")
    parser.add_argument("--input", action="append", required=True, help="输入 JSON（可多次传入，每路一个）")
    parser.add_argument("--search-key", action="append", help="对应 --input 路次的搜索条件分组标签（可多次，缺省自动）")
    parser.add_argument("--output", "-o", help="输出文件名，默认 official-docs/search-results/merged_all.json")
    args = parser.parse_args()

    if args.search_key and len(args.search_key) != len(args.input):
        raise SystemExit("错误：--search-key 数量必须与 --input 一致（或缺省）。")
    keys = args.search_key or [""] * len(args.input)

    articles: List[Dict[str, Any]] = []
    policy_files: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    total_in = 0

    for input_path_str, key in zip(args.input, keys):
        raw_path = Path(input_path_str).expanduser()
        if not raw_path.is_absolute():
            raw_path = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
        if not raw_path.is_file():
            raise SystemExit(f"错误：输入文件不存在: {raw_path}")
        before = len(articles)
        _collect_route(raw_path, key, articles, policy_files)
        total_in += len(articles) - before

    # 合并式去重
    for art in articles:
        title = str(art.get("文章标题") or "").strip()
        url = str(art.get("源网址") or "").strip()
        norm = _norm_title(title)
        key = f"{norm}|{url}" if url else norm
        if not key:
            continue
        if key in by_key:
            _merge_article(by_key[key], art)
        else:
            by_key[key] = art
    merged = list(by_key.values())

    # 显式材料编号（1.4.0）：给每篇材料盖上 `编号` = 它在合并产物中的 1-based 序号。
    # 渲染器优先读材料上的显式编号（render_trace_html.source_from_article 的 explicit_id），
    # 答案角标 [n] 因此锚定在一个"读得到"的编号上，不必让模型去数数组位置——
    # 多路合并后总序号与各路内部的相对编号不同（实测：WorkBuddy 需反复确认才敢写），
    # 数错会静默绑到另一份材料且核验单不会报警，故改为显式锚点。
    for _idx, _art in enumerate(merged, start=1):
        _art["编号"] = _idx

    # policyFiles 收集去重（writtenText+title 双键）
    pf_seen: set = set()
    pf_out: List[Dict[str, Any]] = []
    for p in policy_files:
        w = str(p.get("writtenText") or p.get("发文字号") or "").strip()
        t = str(p.get("title") or p.get("标题") or "").strip()
        if not w and not t:
            continue
        pf_key = f"{w}|{t}"
        if pf_key in pf_seen:
            continue
        pf_seen.add(pf_key)
        pf_out.append(p)

    out_name = args.output or "merged_all.json"
    out = Path(out_name).expanduser()
    if not out.is_absolute():
        out = (SEARCH_RESULTS_DIR / out.name).resolve()
    try:
        out.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise SystemExit(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}") from None

    result = {
        "search_meta": {"merged": True, "input_routes": len(args.input), "merged_from": [str(Path(x).name) for x in args.input]},
        "content": {"data": {"检索文章": merged, "policyFiles": pf_out}},
    }
    # official-docs/ 不随发布包携带（平台不接受 .gitkeep，目录由脚本运行期自动创建）
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 合并完成：{len(args.input)} 路 / 输入 {total_in} 篇 → 合并去重后 {len(merged)} 篇"
          f"（policyFiles {len(pf_out)} 条）→ {out}")
    print("  合并产物与 trusted_search.py 单路输出同构，可直接作为 render_trace_html.py 的 input_json。")


if __name__ == "__main__":
    main()
