#!/usr/bin/env python3
"""深知可信搜索可信搜索调用脚本。

调用可信搜索接口 dependable/search，返回权威材料召回结果。
"""

import argparse
import json
import os
import re
import socket
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_ENDPOINT = "https://open.dknowc.cn/dependable/search"
SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<会话ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()

SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"


def resolve_output_json(output_path: str) -> Path:
    """把搜索结果 JSON 落到 official-docs/search-results/，阻断路径遍历。"""
    raw_path = Path(output_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = raw_path.resolve()

    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    try:
        resolved.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise ValueError(f"输出文件必须位于 official-docs/search-results/ 内: {output_path}")
    return resolved


def _pick(*values: Optional[str]) -> str:
    for value in values:
        if value:
            return value.strip()
    return ""


def _list_arg(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [value.strip()]


def _validate_eff_time(value: str) -> str:
    value = value.strip()
    pattern = r"^\d{4}年(\d{2}月(\d{2}日)?)?$"
    if re.fullmatch(pattern, value):
        return value
    print(
        "错误：eff_time 只能传一个查询所属的生效日期，格式为 YYYY年、YYYY年MM月或 YYYY年MM月DD日；"
        "不要传 2024-2025年、2024至2025年、2024 2025 这类时间范围。",
        file=sys.stderr,
    )
    sys.exit(2)


def _validate_service_area(value: str) -> str:
    value = value.strip()
    multi_area_markers = [",", "，", "、", ";", "；", "/", "|", " 和 ", " 与 ", "及"]
    if any(marker in value for marker in multi_area_markers) or re.search(r"\s+", value):
        print(
            "错误：service_area 只能传一个规范地域名，例如 重庆、重庆两江新区、中国；"
            "不要传 重庆,两江新区、重庆 两江新区、北京和上海 这类多个地域。复杂任务请拆成多次搜索。",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "query": args.query,
        "policy": False if args.no_policy else True,
        "item": False if args.no_item else True,
        "knowBase": False if args.no_know_base else True,
        "return_full_content": args.return_full_content,
        "simplified": False if args.no_simplified else True,
    }

    segment_count = args.segment_count if args.segment_count is not None else 2
    if segment_count not in (None, ""):
        payload["segmentCount"] = int(segment_count)

    service_area = args.service_area
    if service_area:
        payload["service_area"] = _list_arg(_validate_service_area(service_area))

    eff_time = args.eff_time
    if eff_time:
        payload["eff_time"] = _list_arg(_validate_eff_time(eff_time))

    return payload


def _post(url: str, api_key: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("api-key", api_key)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace").replace("\x00", "")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        print(f"错误：HTTP {e.code} {detail or e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"错误：网络请求失败 - {e.reason}", file=sys.stderr)
        sys.exit(1)
    except socket.timeout:
        print("错误：可信搜索接口请求超时。", file=sys.stderr)
        sys.exit(1)

    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(body, dict):
        return body
    return {"data": body}


def _content(body: Dict[str, Any]) -> Dict[str, Any]:
    content = body.get("content")
    if isinstance(content, dict):
        return content
    return body


def _data(body: Dict[str, Any]) -> Dict[str, Any]:
    content = _content(body)
    data = content.get("data")
    if isinstance(data, dict):
        return data
    return {}


def _knowledge_base_url(body: Dict[str, Any], data: Dict[str, Any]) -> str:
    content = _content(body)
    candidates = [
        content.get("knowledgeBase"),
        body.get("knowledgeBase"),
        data.get("knowledgeBase"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _articles(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    articles = data.get("检索文章")
    if isinstance(articles, list):
        return [item for item in articles if isinstance(item, dict)]
    return []


def _short(text: Any, limit: int) -> str:
    if text is None:
        return ""
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _print_list(title: str, items: Any, fields: Iterable[str], max_items: int) -> None:
    if not isinstance(items, list) or not items:
        return
    print(f"\n{title}")
    for idx, item in enumerate(items[:max_items], start=1):
        if not isinstance(item, dict):
            continue
        print(f"{idx}. {item.get('title') or item.get('标题') or item.get('name') or '未命名'}")
        for field in fields:
            value = item.get(field)
            if value:
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value)
                print(f"   {field}: {_short(value, 220)}")


def _print_summary(body: Dict[str, Any], max_articles: int, max_paragraphs: int, paragraph_chars: int) -> None:
    content = _content(body)
    code = content.get("code")
    msg = content.get("msg")
    if code and code != 200:
        print(f"错误：可信搜索接口返回 {code} {msg or ''}".strip())
        return

    data = _data(body)
    if not data:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return

    print("可信搜索结果")
    for key in ("用户问题", "咨询日期", "办理地域"):
        value = data.get(key)
        if value:
            print(f"{key}：{value}")

    articles = _articles(data)
    total_articles = len(articles)
    display_count = min(max_articles, total_articles)
    knowledge_base_url = _knowledge_base_url(body, data)
    if knowledge_base_url:
        print(f"\n知识专库链接：{knowledge_base_url}")
    elif total_articles > max_articles:
        print(f"\n知识专库链接：接口未返回")

    if total_articles:
        print(f"\n召回材料：共 {total_articles} 条，聊天窗口展示前 {display_count} 条材料")
    else:
        print("\n召回材料：0 条")

    for idx, article in enumerate(articles[:max_articles], start=1):
        title = article.get('文章标题') or '未命名材料'
        source = article.get('数据源') or article.get('发布或实施机构') or ''
        date = article.get('发布日期') or '接口未返回'
        url = article.get('源网址') or '接口未返回'

        paragraph_text = ''
        paragraphs = article.get("段落")
        if isinstance(paragraphs, list) and paragraphs:
            first = next((p for p in paragraphs if isinstance(p, dict)), {})
            paragraph_text = first.get("内容") or first.get("标题") or ''
        full = article.get("全文")
        if not paragraph_text and full:
            paragraph_text = str(full)

        print(f"\n{idx}. {title}")
        meta = []
        if source:
            meta.append(f"来源：{source}")
        meta.append(f"发布日期：{date}")
        print("｜".join(meta))
        print(f"相关段落：{_short(paragraph_text, paragraph_chars) or '接口未返回'}")
        print(f"原文：{url}")

    if knowledge_base_url and total_articles > max_articles:
        print(f"\n完整召回内容可通过上方知识专库链接查看。")


def main() -> None:
    parser = argparse.ArgumentParser(description="深知可信搜索可信搜索调用脚本")
    parser.add_argument("query", help="用户搜索问题")
    parser.add_argument("--endpoint", help="覆盖可信搜索接口地址")
    parser.add_argument("--service-area", help="办理地域，只传一个中文地域名")
    parser.add_argument("--eff-time", help="生效时间，只传一个日期值，如 2026年、2026年07月")
    parser.add_argument("--policy", action="store_true", help="返回规范性文件清单")
    parser.add_argument("--no-policy", action="store_true", help="不返回规范性文件清单")
    parser.add_argument("--item", action="store_true", help="返回公共事项在线办理清单")
    parser.add_argument("--no-item", action="store_true", help="不返回公共事项在线办理清单")
    parser.add_argument("--know-base", action="store_true", help="返回知识专库链接")
    parser.add_argument("--no-know-base", action="store_true", help="不返回知识专库链接")
    parser.add_argument("--return-full-content", action="store_true", help="返回资料全文")
    parser.add_argument("--segment-count", type=int, help="每篇材料最多返回段落数")
    parser.add_argument("--simplified", action="store_true", help="精炼输出")
    parser.add_argument("--no-simplified", action="store_true", help="不剔除材料")
    parser.add_argument("--max-articles", type=int, default=3, help="摘要最多展示材料数")
    parser.add_argument("--max-paragraphs", type=int, default=1, help="每篇材料最多展示段落数")
    parser.add_argument("--paragraph-chars", type=int, default=1200, help="每段最多展示字符数")
    parser.add_argument("--show-payload", action="store_true", help="打印请求参数")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求参数，不发起请求")
    parser.add_argument("--json-only", action="store_true", help="仅输出原始 JSON")
    parser.add_argument("--output", "-o", help="搜索结果 JSON 文件名，写入 official-docs/search-results/（配合 --json-only 使用）")
    parser.add_argument("--timeout", type=int, default=60, help="请求超时秒数")
    args = parser.parse_args()

    endpoint = _pick(
        args.endpoint,
        os.environ.get("DKNOWC_TRUSTED_SEARCH_ENDPOINT"),
        os.environ.get("DKNOWC_KNOW_SEARCH_ENDPOINT"),
        DEFAULT_ENDPOINT,
    )
    api_key = _pick(
        os.environ.get("DKNOWC_API_KEY"),
    )

    if not api_key:
        print("错误：缺少 api_key，请配置环境变量 DKNOWC_API_KEY。", file=sys.stderr)
        sys.exit(2)

    payload = _build_payload(args)
    if args.show_payload:
        print("=== 可信搜索请求参数 ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print()
    if args.dry_run:
        return

    body = _post(endpoint, api_key, payload, args.timeout)
    if args.json_only:
        raw_json = json.dumps(body, ensure_ascii=False, indent=2)
        if args.output:
            output_path = resolve_output_json(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(raw_json, encoding="utf-8")
            print(f"已保存搜索结果 JSON：{_rel_to_ws(output_path)}")
        else:
            print(raw_json)
        return
    _print_summary(body, args.max_articles, args.max_paragraphs, args.paragraph_chars)


if __name__ == "__main__":
    main()
