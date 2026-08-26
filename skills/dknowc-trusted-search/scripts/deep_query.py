#!/usr/bin/env python3
"""深知可信搜索深度搜索调用脚本。

调用 deep-query/v3 非流式接口：一次 POST 返回完整 JSON，无 SSE 流式合并步骤。
适合复杂政策研究、方案设计和多轮查证。
请求体字段为 query；areas 支持一次传多个地域（逗号分隔），
服务端按地域自动拆分子查询。返回 data.searches（按子查询分组的材料）、
data.common_articles（多查询公共文章）与 traceId（链路追踪）。
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_ENDPOINT = "https://open.dknowc.cn/api/services/deep-query/v3"
SKILL_ROOT = Path(__file__).resolve().parent.parent
# 产物根：dsh 会话隔离 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/；DKNWOC_WS_ROOT 显式优先；无会话回退 _default
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"


def resolve_output_json(output_path: str) -> Path:
    """把深度搜索结果 JSON 落到 official-docs/search-results/，阻断路径遍历。"""
    raw_path = Path(output_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = (SKILL_ROOT / raw_path).resolve()

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


def _split_areas(value: Optional[str]) -> List[str]:
    """v3 支持一次传多个地域：按逗号/顿号/分号拆分；单个地域直接使用。"""
    if not value:
        return []
    areas: List[str] = []
    for token in str(value).replace("，", ",").replace("、", ",").replace(";", ",").replace("；", ",").split(","):
        token = token.strip()
        if token and token not in areas:
            areas.append(token)
    return areas


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"query": args.question}

    areas = _split_areas(args.area)
    if areas:
        payload["areas"] = areas

    if args.query_id:
        payload["queryId"] = args.query_id

    return payload


def _post(url: str, api_key: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    """非流式 POST：一次性读取完整 JSON 响应体。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("api-key", api_key)
    req.add_header("Content-Type", "application/json")

    started = time.perf_counter()
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
        print("错误：深度搜索接口请求超时。该接口耗时较长，可适当增大 --timeout。", file=sys.stderr)
        sys.exit(1)
    elapsed = time.perf_counter() - started

    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    if isinstance(body, dict):
        body["_elapsedSeconds"] = round(elapsed, 2)
        return body
    return {"data": body, "_elapsedSeconds": round(elapsed, 2)}


def _flatten_articles(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 searches[].result 与 common_articles 按源网址去重摊平，供摘要展示。"""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    seen: set = set()
    out: List[Dict[str, Any]] = []

    def add(article: Any) -> None:
        if not isinstance(article, dict):
            return
        key = str(article.get("源网址") or article.get("文章标题") or "")
        if key and key in seen:
            return
        if key:
            seen.add(key)
        out.append(article)

    for search in data.get("searches") or []:
        if isinstance(search, dict):
            for article in search.get("result") or []:
                add(article)
    for article in data.get("common_articles") or []:
        add(article)
    return out


def _short(text: Any, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _print_summary(body: Dict[str, Any], show_materials: int) -> None:
    code = body.get("code")
    msg = body.get("message") or body.get("msg")
    if code not in (0, None) or msg not in ("success", None, ""):
        hint = "；该错误多为服务端转发失败，可稍后重试或调整问题表述" if code == 500 else ""
        print(f"错误：深度搜索接口返回 code={code} {msg or ''}{hint}".strip())
        return

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    searches = [s for s in (data.get("searches") or []) if isinstance(s, dict)]
    common = [a for a in (data.get("common_articles") or []) if isinstance(a, dict)]

    print("深度搜索结果（deep-query/v3 非流式）")
    if body.get("_elapsedSeconds"):
        print(f"总耗时：{body['_elapsedSeconds']:.2f} 秒")

    if searches:
        print(f"\n子查询分组：共 {len(searches)} 组")
        for s in searches:
            areas = "、".join(str(x) for x in (s.get("areas") or []))
            print(f"- {s.get('query', '')}（{areas}）：{len(s.get('result') or [])} 篇")

    articles = _flatten_articles(body)
    if common:
        print(f"\n多查询公共文章：{len(common)} 篇")
    print(f"召回材料（去重后）：{len(articles)} 篇")
    if data.get("traceId"):
        print(f"traceId：{data['traceId']}")

    if articles and show_materials > 0:
        print(f"\n重点材料（前 {min(show_materials, len(articles))} 篇）")
        for idx, item in enumerate(articles[:show_materials], start=1):
            title = item.get("文章标题") or "未命名材料"
            agency = item.get("数据源") or ""
            date = item.get("发布日期") or ""
            area = item.get("办理地域") or ""
            url = item.get("源网址") or ""
            print(f"{idx}. {title}")
            meta = [x for x in [agency, area, date] if x]
            if meta:
                print(f"   {' | '.join(meta)}")
            paragraphs = item.get("段落") or []
            first_para = next((p.get("内容") for p in paragraphs if isinstance(p, dict) and p.get("内容")), "")
            if first_para:
                print(f"   摘要：{_short(first_para)}")
            if url:
                print(f"   原文：{url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="深知可信搜索 deep-query/v3 深度搜索调用脚本（非流式）")
    parser.add_argument("question", help="用户复杂问题（请求体字段 query）")
    parser.add_argument("--endpoint", help="覆盖深度搜索接口地址")
    parser.add_argument("--area", help="办理地域；v3 支持逗号分隔一次传多个地域，服务端按地域拆分子查询")
    parser.add_argument("--query-id", help="显式传入 queryId；默认不传，返回侧以 traceId 做链路追踪")
    parser.add_argument("--show-payload", action="store_true", help="打印请求参数")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求参数，不发起请求")
    parser.add_argument("--json-only", action="store_true", help="仅输出接口原始 JSON")
    parser.add_argument("--output", "-o", help="深度搜索结果 JSON 文件名，写入 official-docs/search-results/（配合 --json-only 使用）")
    parser.add_argument("--show-materials", type=int, default=5, help="摘要中展示前 N 篇材料")
    parser.add_argument("--timeout", type=int, default=300, help="请求超时秒数")
    args = parser.parse_args()

    endpoint = _pick(
        args.endpoint,
        os.environ.get("DKNOWC_KNOW_DEEP_QUERY_ENDPOINT"),
        os.environ.get("DKNOWC_DEEP_QUERY_ENDPOINT"),
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
        print("=== 请求参数 ===")
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
            print(f"已保存深度搜索结果 JSON：{output_path.relative_to(SKILL_ROOT)}")
        else:
            print(raw_json)
        return

    _print_summary(body, args.show_materials)


if __name__ == "__main__":
    main()
