#!/usr/bin/env python3
"""调用公文范文大纲接口，生成写作结构参考。"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests


SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
import os as _os
WS_ROOT = Path(_os.environ.get("DKNWOC_WS_ROOT") or _os.getcwd()).resolve()

API_KEY_ENV = "DKNOWC_API_KEY"
OUTLINE_RESULTS_DIR = WS_ROOT / "official-docs" / "outline-results"
OUTLINE_API_URL = "https://open.dknowc.cn/llm-api/proxy-builtin/official-doc-outline/v1"
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 1200
DEFAULT_TIMEOUT = 180


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def safe_filename(text: str, max_length: int = 60) -> str:
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text.strip())
    name = "_".join(part for part in name.split("_") if part)
    return (name or "outline")[:max_length]


def _rel_to_ws(path: Path) -> str:
    """把输出路径显示为相对工作区（WS_ROOT）的形式；不在工作区内则显示绝对路径。"""
    try:
        return str(path.relative_to(WS_ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_output_json(output_path: Optional[str], query: str) -> Path:
    if output_path:
        raw_path = Path(output_path).expanduser()
    else:
        raw_path = Path(f"{safe_filename(query)}_范文大纲.json")

    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (OUTLINE_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = (WS_ROOT / raw_path).resolve()

    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    if not is_relative_to(resolved, OUTLINE_RESULTS_DIR.resolve()):
        raise ValueError(f"输出文件必须位于范文大纲结果目录内: {OUTLINE_RESULTS_DIR}")
    return resolved


def load_api_key(config_path: Optional[Path] = None) -> str:
    if config_path is not None:
        raise ValueError(f"当前版本不再读取 config.ini，请通过环境变量 {API_KEY_ENV} 配置 API Key。")

    # dsh 场景：dsh 会清理名字含 KEY 的隐式环境变量，bundle 插件会把主进程的
    # DKNOWC_API_KEY 经 shell-env 显式注入为 DSH_DKNOWC_API_KEY，优先读取。
    api_key = os.environ.get("DSH_DKNOWC_API_KEY", "").strip() or os.environ.get(API_KEY_ENV, "").strip()
    if not api_key or api_key in {"your_api_key_here", "你的深知搜索 API Key"}:
        raise ValueError(f"API Key 为空，请通过环境变量 {API_KEY_ENV} 配置有效 API Key。")
    return api_key


def validate_query(query: str) -> str:
    value = query.strip()
    if len(value) < MIN_QUERY_LENGTH:
        raise ValueError(f"写作需求过短，最少需要 {MIN_QUERY_LENGTH} 个字符")
    if len(value) > MAX_QUERY_LENGTH:
        raise ValueError(f"写作需求过长，超过限制（最大 {MAX_QUERY_LENGTH} 字符）")
    return value


def call_outline_api(query: str, api_key: str, timeout: int) -> tuple[int, dict | str, float]:
    start = time.time()
    response = requests.post(
        OUTLINE_API_URL,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        json={"query": query},
        timeout=timeout,
    )
    elapsed = round(time.time() - start, 2)
    try:
        body: dict | str = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body, elapsed


def build_output(query: str, status_code: int, body: dict | str, elapsed: float) -> dict:
    result = {
        "request_meta": {
            "query": query,
            "url": OUTLINE_API_URL,
            "elapsed_seconds": elapsed,
            "status_code": status_code,
            "auth": f"api-key from {API_KEY_ENV}",
        },
        "raw_response": body,
    }

    if not isinstance(body, dict):
        result.update({
            "success": False,
            "reason": "接口未返回 JSON",
            "outline_available": False,
        })
        return result

    data = body.get("data")
    outline_available = (
        status_code == 200
        and body.get("code") == 200
        and isinstance(data, dict)
        and data.get("success") is True
        and isinstance(data.get("outline"), list)
        and len(data.get("outline")) > 0
    )
    result.update({
        "success": status_code == 200 and body.get("code") == 200,
        "outline_available": outline_available,
        "response_id": body.get("id"),
        "message": body.get("msg"),
    })
    if isinstance(data, dict):
        result["outline_title"] = data.get("outline_title")
        result["doc_type"] = data.get("doc_type")
        result["structure_summary"] = data.get("structure_summary")
        result["outline"] = data.get("outline")
        result["style_notes"] = data.get("style_notes")
        result["risk_notes"] = data.get("risk_notes")
        result["reason"] = data.get("reason") if data.get("success") is False else None
    else:
        result["reason"] = body.get("msg") or "接口未返回 data 对象"
    return result


def main():
    parser = argparse.ArgumentParser(description="公文范文大纲接口调用工具")
    parser.add_argument("query", help="用户写作需求，包含文种、主题、用途和写作重点")
    parser.add_argument("--output", help="输出 JSON 文件名或 official-docs/outline-results/ 下的路径")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="请求超时时间，默认 180 秒")
    args = parser.parse_args()

    try:
        query = validate_query(args.query)
        api_key = load_api_key()
        output_path = resolve_output_json(args.output, query)
        status_code, body, elapsed = call_outline_api(query, api_key, args.timeout)
        result = build_output(query, status_code, body, elapsed)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        summary = {
            "output": str(_rel_to_ws(output_path)),
            "status_code": status_code,
            "elapsed_seconds": elapsed,
            "request_success": result.get("success"),
            "outline_available": result.get("outline_available"),
            "outline_title": result.get("outline_title"),
            "doc_type": result.get("doc_type"),
            "outline_count": len(result.get("outline") or []),
            "reason": result.get("reason"),
            "next_action": "confirm_outline_and_search_suggestions" if result.get("outline_available") else "ignore_outline_and_continue_314_flow",
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if status_code != 200:
            return 1
        return 0
    except Exception as exc:
        print(json.dumps({
            "success": False,
            "outline_available": False,
            "error": str(exc),
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
