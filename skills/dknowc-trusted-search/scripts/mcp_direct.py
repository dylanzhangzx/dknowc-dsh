#!/usr/bin/env python3
"""深知 dsh —— MCP 临时直连客户端。

dsh 场景下，MCP Bearer 认证在会话启动时从环境变量冻结，注册后拿到的新
API Key 无法热注入到已运行的 mcp-client。本脚本作为"临时 Key 通道"：
用 `DKNOWC_API_KEY=<临时Key> python3 mcp_direct.py ...` 前缀赋值方式，
把临时 Key 直接传给脚本（绕过 dsh 的环境清理），通过 HTTP 直调深知可信
工作台 MCP server 的 tools/call，输出与 dsh mcp-client 一致的 MCP 返回
结构，后续照常走 adapt_mcp_result.py → render_trace_html.py 链路。

用法：
    DKNOWC_API_KEY=<key> python3 mcp_direct.py <tool> '<json-args>' [--output <out.json>] [--timeout 120]

示例：
    DKNOWC_API_KEY=sk-xxx python3 mcp_direct.py credible_chat \
      '{"query": "深圳公积金租房提取需要哪些材料？", "area": "深圳"}' \
      --output official-docs/search-results/dknowc_mcp_raw.json

注意：
- API Key 只通过环境变量 DKNOWC_API_KEY 传入（bash 前缀赋值），不得作为命令行参数
- 不打印完整 Key，不持久化 Key
- 输出为 MCP 协议结构 {"content":[{"type":"text","text":"<接口JSON>"}]}
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_ENDPOINT = "https://mcp.dknowc.cn/s6/mcp/"
PROTOCOL_VERSION = "2025-03-26"
API_KEY_ENV = "DKNOWC_API_KEY"


def _post(endpoint: str, api_key: str, payload: Dict[str, Any], session_id: Optional[str], timeout: int) -> tuple[int, str, Optional[str]]:
    """POST 一次 JSON-RPC，返回 (http_code, body, 新 session_id)。"""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {api_key}",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            new_session = resp.headers.get("Mcp-Session-Id")
            return resp.status, body, new_session
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body, e.headers.get("Mcp-Session-Id")
    except urllib.error.URLError as e:
        raise RuntimeError(f"MCP 连接失败: {e.reason}")


def _call_tool(api_key: str, tool: str, arguments: Dict[str, Any], endpoint: str, timeout: int) -> Dict[str, Any]:
    """initialize → tools/call，返回 MCP 标准结果。"""
    # 1. initialize 建立会话
    status, body, session_id = _post(endpoint, api_key, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "dknowc-dsh-mcp-direct", "version": "1.0.0"},
        },
    }, None, timeout)
    if status not in (200, 202):
        raise RuntimeError(f"MCP initialize 失败 (HTTP {status}): {body[:300]}")
    # session_id 若未在响应头返回，尝试从 JSON 里读；无则沿用
    if not session_id:
        try:
            init = json.loads(body)
            sid = init.get("result", {}).get("_meta", {}).get("sessionId")
            if isinstance(sid, str) and sid:
                session_id = sid
        except json.JSONDecodeError:
            pass

    # 2. tools/call
    status, body, _ = _post(endpoint, api_key, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }, session_id, timeout)
    if status not in (200, 202):
        raise RuntimeError(f"MCP tools/call 失败 (HTTP {status}): {body[:300]}")

    # 解析返回；streamable-http 可能是 SSE 或 JSON
    text = body.strip()
    # 若为 SSE 多行，取 data: 行拼接
    if text.startswith("event:") or "\ndata:" in text:
        chunks = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunks.append(line[5:].strip())
        text = "\n".join(chunks)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 不是标准 JSON，包成 MCP content
        return {"content": [{"type": "text", "text": text}], "isError": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 临时直连客户端（注册后临时 Key 通道）")
    parser.add_argument("tool", help="MCP 工具名：credible_chat / trusted_search / deep_query")
    parser.add_argument("args_json", help="工具参数 JSON 字符串")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径（保存 MCP 原始返回）")
    parser.add_argument("--endpoint", default=None, help="MCP 端点，默认 https://mcp.dknowc.cn/s6/mcp/")
    parser.add_argument("--timeout", type=int, default=120, help="请求超时秒数，deep_query 建议更大")
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        print(f"错误：缺少环境变量 {API_KEY_ENV}（请用 DKNOWC_API_KEY=<key> 前缀赋值方式传入）。", file=sys.stderr)
        return 2

    try:
        arguments = json.loads(args.args_json)
        if not isinstance(arguments, dict):
            raise ValueError("参数必须是 JSON 对象")
    except (json.JSONDecodeError, ValueError) as e:
        print(f"错误：参数不是合法 JSON 对象：{e}", file=sys.stderr)
        return 2

    endpoint = args.endpoint or DEFAULT_ENDPOINT
    try:
        result = _call_tool(api_key, args.tool, arguments, endpoint, args.timeout)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    raw_json = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out_path = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(raw_json)
        print(f"已保存 MCP 返回：{out_path}")
    else:
        print(raw_json)

    # 若工具返回 isError 或内嵌业务错误码，非零退出以提示
    if result.get("isError"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
