#!/usr/bin/env python3
"""深知 dsh —— MCP 工具返回 → 渲染脚本输入 适配器。

dsh 场景下，skill 不再直连深知接口，而是通过 MCP 工具
（mcp__dknowc__credible_chat / _trusted_search / _deep_query）拿数据。
MCP 工具返回的是 MCP 协议结构（{content:[{type:"text",text:"..."}]}），
而 render_trace_html.py 等渲染脚本期望的是深知接口 JSON 结构。

本脚本把 MCP 返回规范化成渲染脚本可消费的接口 JSON，保证溯源 HTML
等交付物与直连版一致。

用法：
    python3 scripts/adapt_mcp_result.py <mcp返回.json> --output <规范化.json> [--mode chat|search|deep]

- 输入：模型保存的 MCP 工具返回 JSON（content 数组形式，或已含接口 JSON）
- 输出：可直接传给 render_trace_html.py 的接口 JSON 结构
- --mode：chat=可信咨询 / search=可信搜索 / deep=深度搜索；缺省自动识别
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _deep_find(o: Any, keys, depth=0, max_depth=8):
    """在任意嵌套结构里查找第一个命中任一 key 的值。"""
    if depth > max_depth:
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys:
                return v
            r = _deep_find(v, keys, depth + 1, max_depth)
            if r is not None:
                return r
    elif isinstance(o, list):
        for item in o:
            r = _deep_find(item, keys, depth + 1, max_depth)
            if r is not None:
                return r
    return None


def _extract_mcp_text(o: Any) -> Optional[str]:
    """从 MCP 协议返回中提取文本内容。

    支持形态：
    - {content: [{type:"text", text:"..."}]}（MCP 标准，text 常为 JSON 字符串）
    - {structuredContent: {...}}
    - 直接就是接口 JSON
    返回：解析出的 dict payload；无法解析时返回 None。
    """
    if isinstance(o, dict):
        # structuredContent 优先
        sc = o.get("structuredContent")
        if isinstance(sc, dict):
            return json.dumps(sc, ensure_ascii=False)
        content = o.get("content")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
            if parts:
                return "\n".join(parts)
        # 已经是接口 JSON？
        if any(k in o for k in ("resp", "data", "referenceMaterials", "检索文章", "success")):
            return json.dumps(o, ensure_ascii=False)
    return None


def _try_json(text: str) -> Any:
    """尝试把文本解析为 JSON。"""
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _unwrap_payload(o: Any) -> Dict[str, Any]:
    """递归展开嵌套的接口 JSON，找到最内层含业务字段的对象。

    接口返回常见 {data: {resp: {...}, referenceMaterials:[...]}}，
    也偶见 {content: {data: {...}}} 等包装。这里尽量展开到业务层。
    """
    cur = o
    seen = set()
    while isinstance(cur, dict) and id(cur) not in seen:
        seen.add(id(cur))
        # 展开 {content:{...}} / {data:{...}} 包装，但保留 data 本身
        if len(cur) == 1:
            only = next(iter(cur.values()))
            if isinstance(only, dict):
                cur = only
                continue
        if isinstance(cur.get("data"), dict) and (
            "resp" in cur["data"] or "检索文章" in cur["data"] or "referenceMaterials" in cur["data"]
        ):
            # 保留外层 data 键，同时业务字段也升到顶层
            merged = dict(cur)
            merged.update({k: v for k, v in cur["data"].items() if k not in merged})
            merged["data"] = cur["data"]
            return merged
        break
    return cur if isinstance(cur, dict) else {"raw": cur}


def _normalize_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化可信咨询（credible_chat）返回。"""
    out = dict(payload)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    # 确保 resp.content 可被提取
    if "resp" not in out:
        resp = data.get("resp") if isinstance(data, dict) else None
        if isinstance(resp, dict):
            out["resp"] = resp
        else:
            # 从任意位置找正文
            answer = _deep_find(payload, ("content", "answer", "text", "resp"), depth=0)
            if isinstance(answer, str):
                out["resp"] = {"content": answer}
    # 确保 referenceMaterials
    if "referenceMaterials" not in out:
        rm = data.get("referenceMaterials") if isinstance(data, dict) else None
        if isinstance(rm, list):
            out["referenceMaterials"] = rm
    # knowledgeBase / question
    for key in ("knowledgeBase", "question"):
        if key not in out and isinstance(data, dict) and key in data:
            out[key] = data[key]
    return out


def _normalize_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化可信搜索（trusted_search）返回。"""
    out = dict(payload)
    # 检索文章：优先顶层 data.检索文章，其次 content.data.检索文章
    articles = _deep_find(payload, ("检索文章",))
    if articles is None:
        content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
        data = content.get("data") if isinstance(content.get("data"), dict) else {}
        articles = data.get("检索文章")
    if isinstance(articles, list):
        if "data" not in out or not isinstance(out["data"], dict):
            out["data"] = {}
        out["data"]["检索文章"] = articles
    # 确保 referenceMaterials
    if "referenceMaterials" not in out:
        rm = _deep_find(payload, ("referenceMaterials",))
        if isinstance(rm, list):
            out["referenceMaterials"] = rm
    # knowledgeBase
    if "knowledgeBase" not in out:
        kb = _deep_find(payload, ("knowledgeBase", "knowledgeBaseUrl"))
        if isinstance(kb, str):
            out["knowledgeBase"] = kb
    return out


def _normalize_deep(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化深度搜索（deep_query）返回。"""
    out = dict(payload)
    events = payload.get("events")
    if not isinstance(events, list):
        events = _deep_find(payload, ("events",))
    if isinstance(events, list):
        out["events"] = events
    # data.list 兜底
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if isinstance(data.get("list"), list):
        out["data"] = data
    if "referenceMaterials" not in out:
        rm = _deep_find(payload, ("referenceMaterials",))
        if isinstance(rm, list):
            out["referenceMaterials"] = rm
    return out


def detect_mode(payload: Dict[str, Any]) -> str:
    """自动识别返回属于哪种接口。"""
    if _deep_find(payload, ("检索文章",)) is not None:
        return "search"
    if isinstance(payload.get("events"), list) or _deep_find(payload, ("events",)) is not None:
        return "deep"
    if _deep_find(payload, ("resp",)) is not None:
        return "chat"
    return "chat"


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 返回 → 渲染脚本输入 适配器")
    parser.add_argument("input_json", help="MCP 工具返回 JSON 文件路径")
    parser.add_argument("--output", "-o", required=True, help="规范化 JSON 输出路径")
    parser.add_argument("--mode", choices=["chat", "search", "deep"], default=None, help="接口类型；缺省自动识别")
    args = parser.parse_args()

    src = Path(args.input_json).expanduser()
    if not src.exists():
        print(f"错误：输入文件不存在：{src}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误：输入不是合法 JSON：{e}", file=sys.stderr)
        return 2

    # 1) 提取 MCP 文本 → 尝试解析成接口 JSON
    text = _extract_mcp_text(raw)
    payload = _try_json(text) if text else None
    if not isinstance(payload, dict):
        # 纯文本回答（无 JSON）→ 包成 resp.content
        payload = {"resp": {"content": text or json.dumps(raw, ensure_ascii=False)}}

    # 2) 展开包装层
    payload = _unwrap_payload(payload)

    # 3) 按模式规范化
    mode = args.mode or detect_mode(payload)
    if mode == "search":
        out = _normalize_search(payload)
    elif mode == "deep":
        out = _normalize_deep(payload)
    else:
        out = _normalize_chat(payload)

    out_path = Path(args.output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已规范化（mode={mode}）：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
