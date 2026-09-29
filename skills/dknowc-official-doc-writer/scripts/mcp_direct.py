#!/usr/bin/env python3
"""在 WorkBuddy 环境里，用脚本直连「本地 MCP 代理」调用深知可信工作台工具，
把返回**原样落盘**到 search-results，全程不经模型上下文。

背景（3.7.5）：WorkBuddy 不把深知 MCP 的真实 OAuth 凭据放进 skill 环境，而是起一个
本地代理（127.0.0.1，路径带会话级 hash），内部持有真实凭据转发到云端 mcp.dknowc.cn。
环境变量 `CODEBUDDY_MCP_CONFIG` 内联 JSON 里含各 MCP server 的 url + headers
（Bearer 会话令牌）。脚本从该变量动态拿到 dknowc-mcp 的地址与头，直连代理发 JSON-RPC，
返回的完整 JSON 由脚本写入文件——模型不抄写大 JSON，也就没有转写丢内容的问题
（此前模型调 MCP 工具会把 60-170KB 返回抄进上下文再落盘，实测丢失 83%）。

只负责"调用 + 落盘原始返回"；转换仍走现有 deep_convert.py / mcp_convert.py。

用法（WorkBuddy 环境，必须有 CODEBUDDY_MCP_CONFIG）：
  python3 scripts/mcp_direct.py --tool deep_query --query "北京市养老服务政策" \
      --areas 北京市 --area 北京市 --purpose "政策依据型" -o deep_policy.json
  python3 scripts/mcp_direct.py --tool trusted_search --query "北京市养老服务政策" \
      --areas 北京市 --area 北京市 --purpose "政策依据型" -o mcp_policy.json

安全：脚本只读取并使用 url/headers，绝不打印 token / 会话令牌 / 代理路径 hash。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
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

MCP_CONFIG_ENV = "CODEBUDDY_MCP_CONFIG"


def _walk(obj, path: str = ""):
    """深度优先遍历任意嵌套结构，产出 (路径, 值)，用于从 CODEBUDDY_MCP_CONFIG 里找 server。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def find_dknowc_endpoint(config_raw: str):
    """从 CODEBUDDY_MCP_CONFIG 里解析出深知 MCP 的 {url, headers}。

    结构未知（WorkBuddy 内部格式），自适应遍历：找含 dknowc/深知 标识的 server 项，
    取其 url/endpoint 与 headers。找不到时报错并打印键路径（不含值）辅助调试。
    """
    if not config_raw:
        raise SystemExit(f"错误：环境变量 {MCP_CONFIG_ENV} 为空。本脚本只在 WorkBuddy 环境（宿主注入了该变量）可用。")
    try:
        data = json.loads(config_raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"错误：{MCP_CONFIG_ENV} 不是合法 JSON（{exc}）。") from None

    key_paths = []
    for path, value in _walk(data):
        key_paths.append(path)
        if not isinstance(value, str):
            continue
        low = value.lower()
        # 找 url 值且标识含 dknowc / 深知
        if ("dknowc" in low or "深知" in low) and ("http" in low or "/mcp" in low):
            # 向上找该 server 的 headers：遍历父路径太复杂，改为收集所有 server 候选后匹配
            pass

    # 简化策略：收集所有"可能是一组 server 配置"的节点（含 url + headers 的 dict）
    candidates = []

    def collect(node, hint: str = ""):
        if isinstance(node, dict):
            keys = {str(k).lower() for k in node.keys()}
            url = node.get("url") or node.get("endpoint") or node.get("baseUrl") or node.get("serverUrl")
            headers = node.get("headers") or node.get("header") or node.get("auth")
            # server 名在 mcpServers 的**键**上（如 "dknowc-mcp"），不在节点内部；
            # 节点内无 name 字段时用父级键名兜底，否则会退化成候选列表第一项而选错服务。
            name = str(node.get("name") or node.get("serverName") or node.get("id") or hint or "").lower()
            blob = f"{name} {url}".lower() if url else name
            if url and headers and ("dknowc" in blob or "深知" in blob or "/mcp" in blob):
                candidates.append({"url": str(url), "headers": headers, "name": name})
            for k, v in node.items():
                collect(v, str(k))
        elif isinstance(node, list):
            for v in node:
                collect(v, hint)

    collect(data)
    if not candidates:
        raise SystemExit(
            "错误：未在 CODEBUDDY_MCP_CONFIG 中找到深知 MCP 的 url+headers。"
            f"该变量键路径结构（不含值）：{sorted(set(key_paths))[:30]}")

    # 优先选明确含 dknowc 的
    pick = next((c for c in candidates if "dknowc" in c["name"]), candidates[0])
    headers = pick["headers"] if isinstance(pick["headers"], dict) else {}
    # headers 可能是 {"Authorization": "Bearer ..."} 或带嵌套
    norm = {}
    if isinstance(headers, dict):
        for k, v in headers.items():
            norm[str(k)] = str(v)
    elif isinstance(headers, list):
        for h in headers:
            if isinstance(h, dict):
                for k, v in h.items():
                    norm[str(k)] = str(v)
    return pick["url"], norm


def decode_jsonrpc(text: str) -> dict:
    """解析 MCP 响应体，兼容纯 JSON 与 SSE（text/event-stream）两种形态。

    本地 MCP 代理即使收到的 Accept 同时包含 application/json，也可能仍以 SSE 返回
    （`event: message\\ndata: {...}\\n\\n`）；若直接 json.loads 会在 initialize 阶段
    报 "Expecting value: line 1 column 1 (char 0)"。此处先试纯 JSON，失败再逐行解析
    SSE 的 `data:` 载荷，取最后一个可解析对象。
    """
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(text)
    parsed = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
    if parsed is None:
        raise json.JSONDecodeError("响应体中未找到可解析 JSON（既非纯 JSON 也非 SSE data 载荷）", text, 0)
    return parsed


_SESSION: dict = {}


def mcp_call(url: str, headers: dict, method: str, params: dict, timeout: int = 300) -> dict:
    """发一次 MCP JSON-RPC，返回完整响应。streamableHttp，POST JSON。

    本地代理为有状态会话：initialize 响应头返回 mcp-session-id，后续 tools/call
    必须回带该头，否则代理返回 HTTP 400 Bad Request。
    """
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if _SESSION.get("id"):
        req.add_header("Mcp-Session-Id", _SESSION["id"])
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            sid = resp.headers.get("mcp-session-id")
            if sid:
                _SESSION["id"] = sid
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"错误：MCP {method} 返回 HTTP {exc.code}。响应体：{detail}") from None
    data = decode_jsonrpc(text)
    if "error" in data:
        raise SystemExit(f"错误：MCP {method} 返回 error: {data['error']}")
    return data


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="WorkBuddy 环境直连本地 MCP 代理调用深知工具并把返回原样落盘（不经模型上下文）")
    parser.add_argument("--tool", required=True, choices=["deep_query", "trusted_search"],
                        help="要调用的深知 MCP 工具")
    parser.add_argument("--query", required=True, help="搜索 query（按 Query 生成原则）")
    parser.add_argument("--areas", default="", help="地域；deep_query 传数组、trusted_search 传 service_area")
    parser.add_argument("--area", default="", help="写入 search_meta 的检索地域（deep_convert/mcp_convert 用）")
    parser.add_argument("--purpose", default="", help="搜索目的（内部参数，不向用户展示）")
    parser.add_argument("--timeout", type=int, default=300, help="请求超时秒数（深度搜索较慢）")
    parser.add_argument("--output", "-o", required=True, help="输出文件名，写入 official-docs/search-results/（原始返回）")
    args = parser.parse_args()

    url, headers = find_dknowc_endpoint(os.environ.get(MCP_CONFIG_ENV, ""))

    # ① initialize（拿 serverInfo；无状态 server 也兼容）
    try:
        init = mcp_call(url, headers, "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "dknowc-skill-direct", "version": "3.7.5"},
        }, timeout=30)
        server = init.get("result", {}).get("serverInfo", {})
        print(f"✓ MCP 连接：{server.get('name', '?')} v{server.get('version', '?')}（本地代理）")
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"错误：MCP initialize 失败（{exc}）。请确认 WorkBuddy 正在运行且深知 MCP 已连接。") from None

    # ② tools/call
    if args.tool == "deep_query":
        tool_args = {"query": args.query}
        if args.areas:
            tool_args["areas"] = [a.strip() for a in args.areas.split(",") if a.strip()]
    else:  # trusted_search
        tool_args = {
            "query": args.query,
            "include_details": True,
            "max_articles": 50,
            "material_length": 200000,
            "policy": True,
            "segment_count": 2,
            "simplified": False,
            "know_base": True,
            "return_full_content": False,
        }
        if args.areas:
            tool_args["service_area"] = args.areas.split(",")[0].strip()

    result = mcp_call(url, headers, "tools/call", {"name": args.tool, "arguments": tool_args},
                      timeout=args.timeout)
    content = result.get("result", {}).get("content", [])
    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    if not texts:
        raise SystemExit(f"错误：{args.tool} 未返回文本内容。原始响应: {json.dumps(result, ensure_ascii=False)[:300]}")
    raw = texts[0]

    # ③ 校验并落盘（程序化：内容直接进文件，不经模型）
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"错误：MCP {args.tool} 返回的 text 不是合法 JSON（{exc}）。这是接口返回问题，请保留原始响应排查。") from None

    out = Path(args.output).expanduser()
    if not out.is_absolute():
        out = (SEARCH_RESULTS_DIR / out.name).resolve()
    try:
        out.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        raise SystemExit(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}") from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(raw, encoding="utf-8")

    # ④ 摘要（不打印 token / 路径 hash）
    summary = ""
    if args.tool == "deep_query":
        data = parsed.get("data") or {}
        searches = data.get("searches") or []
        total = sum(len(s.get("result") or []) for s in searches)
        common = len(data.get("common_articles") or [])
        summary = f"{total + common} 篇（子查询 {len(searches)} 组 + common {common}）"
    else:
        mats = parsed.get("materials") or []
        summary = f"{len(mats)} 篇 materials"
    print(f"✓ {args.tool} 调用成功：{summary} → {out.relative_to(SKILL_ROOT)}")
    print(f"  下一步：python3 scripts/{'deep_convert' if args.tool == 'deep_query' else 'mcp_convert'}.py {out.name} "
          f"--area {args.area or '地域'} --purpose \"{args.purpose or '搜索目的'}\"")


if __name__ == "__main__":
    raise SystemExit(main())
