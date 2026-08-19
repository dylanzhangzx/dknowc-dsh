#!/usr/bin/env python3
"""深知可信搜索深度搜索调用脚本。

调用 deep-query/v2 SSE 接口，适合复杂政策研究、方案设计和多轮查证。
默认不传 queryId，由接口自动生成。
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
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_ENDPOINT = "https://open.dknowc.cn/api/services/deep-query/v2"
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
    """把深度搜索结果 JSON 落到 official-docs/search-results/，阻断路径遍历。"""
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


def _validate_area(value: str) -> str:
    value = value.strip()
    multi_area_markers = [",", "，", "、", ";", "；", "/", "|", " 和 ", " 与 ", "及"]
    if any(marker in value for marker in multi_area_markers):
        print(
            "错误：areas 每次只传一个地域，例如 北京市、重庆市、重庆两江新区；复杂任务需要多地域时请拆成多次调用。",
            file=sys.stderr,
        )
        sys.exit(2)
    return value


def _build_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"question": args.question}

    areas = args.area
    if areas:
        payload["areas"] = [_validate_area(areas)]

    query_id = args.query_id
    if query_id:
        payload["queryId"] = query_id

    return payload


def _post_sse(url: str, api_key: str, payload: Dict[str, Any], timeout: int) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, float]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("api-key", api_key)
    req.add_header("Content-Type", "application/json")

    events: List[Tuple[str, Dict[str, Any]]] = []
    timings = {"start": time.perf_counter(), "first_event": 0.0, "total": 0.0}
    current_event = "message"

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").replace("\x00", "").strip()
                if not line:
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip() or "message"
                    continue
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    obj = {"raw": chunk}
                if not timings["first_event"]:
                    timings["first_event"] = time.perf_counter() - timings["start"]
                events.append((current_event, obj))
                if current_event == "done":
                    break
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
    finally:
        timings["total"] = time.perf_counter() - timings["start"]

    return events, timings


def _query_id(events: Iterable[Tuple[str, Dict[str, Any]]]) -> str:
    last = ""
    for _, obj in events:
        value = obj.get("queryId")
        if isinstance(value, str) and value.strip():
            last = value.strip()
    return last


def _result_data(events: Iterable[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    for event, obj in events:
        if event == "result":
            data = obj.get("data")
            if isinstance(data, dict):
                return data
    return {}


def _short(text: Any, limit: int = 180) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def _print_summary(events: List[Tuple[str, Dict[str, Any]]], timings: Dict[str, float], show_materials: int) -> None:
    print("深度搜索结果")
    print(f"首个事件耗时：{timings['first_event']:.2f} 秒")
    print(f"总耗时：{timings['total']:.2f} 秒")

    progress = [obj.get("message") for event, obj in events if event == "progress" and obj.get("message")]
    if progress:
        print("\n搜索过程")
        for item in progress:
            print(f"- {_short(item, 500)}")

    data = _result_data(events)
    result_list = data.get("list")
    if isinstance(result_list, list):
        print(f"\n召回材料：{len(result_list)} 条")

    groups = data.get("searchGroupInfos")
    if isinstance(groups, list) and groups:
        print("\n搜索分组")
        for group in groups:
            if not isinstance(group, dict):
                continue
            area = group.get("area") or ""
            text = group.get("text") or ""
            count = len(group.get("voMd5List") or [])
            print(f"- {area} {text}（{count} 条）".strip())

    if isinstance(result_list, list) and result_list and show_materials > 0:
        print(f"\n重点材料（前 {min(show_materials, len(result_list))} 条）")
        for idx, item in enumerate(result_list[:show_materials], start=1):
            if not isinstance(item, dict):
                continue
            vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
            title = vo.get("showTitle") or vo.get("title") or item.get("title") or "未命名材料"
            type_name = vo.get("typeName") or vo.get("type") or ""
            area = vo.get("areaName") or ""
            date = vo.get("dateTime") or vo.get("createDate") or ""
            url = vo.get("sourceUrl") or vo.get("url") or ""
            print(f"{idx}. {title}")
            if type_name or area or date:
                print(f"   类型/地域/日期：{' | '.join(v for v in [type_name, area, date] if v)}")
            if url:
                print(f"   原文：{url}")

    event_names = [event for event, _ in events]
    if "done" in event_names:
        print("\n状态：检索完成")


def main() -> None:
    parser = argparse.ArgumentParser(description="深知可信搜索 deep-query/v2 深度搜索调用脚本")
    parser.add_argument("question", help="用户复杂问题")
    parser.add_argument("--endpoint", help="覆盖深度搜索接口地址")
    parser.add_argument("--area", help="单个地域，例如 北京市、重庆市、重庆两江新区")
    parser.add_argument("--query-id", help="显式传入 queryId；默认不传，由接口自动生成")
    parser.add_argument("--show-payload", action="store_true", help="打印请求参数")
    parser.add_argument("--dry-run", action="store_true", help="只打印请求参数，不发起请求")
    parser.add_argument("--raw", action="store_true", help="打印原始事件 JSON")
    parser.add_argument("--json-only", action="store_true", help="仅输出结构化 JSON")
    parser.add_argument("--output", "-o", help="深度搜索结果 JSON 文件名，写入 official-docs/search-results/（配合 --json-only 使用）")
    parser.add_argument("--show-materials", type=int, default=5, help="摘要中展示前 N 条材料")
    parser.add_argument("--timeout", type=int, default=180, help="请求超时秒数")
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

    events, timings = _post_sse(endpoint, api_key, payload, args.timeout)

    if args.json_only:
        raw_json = json.dumps({"success": True, "timings": timings, "events": events}, ensure_ascii=False, indent=2)
        if args.output:
            output_path = resolve_output_json(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(raw_json, encoding="utf-8")
            print(f"已保存深度搜索结果 JSON：{_rel_to_ws(output_path)}")
        else:
            print(raw_json)
        return

    if args.raw:
        for event, obj in events:
            print(f"event:{event}")
            print(json.dumps(obj, ensure_ascii=False))
        return

    _print_summary(events, timings, args.show_materials)


if __name__ == "__main__":
    main()
