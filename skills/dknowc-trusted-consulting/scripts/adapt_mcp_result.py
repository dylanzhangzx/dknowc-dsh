#!/usr/bin/env python3
"""深知 dsh —— MCP 工具返回 → 渲染脚本输入 适配器。

dsh 场景下，skill 通过深知可信工作台 MCP 工具（credible_chat /
trusted_search / deep_query，或注册后经 mcp_direct.py 直调）拿数据。
MCP 返回是协议结构 {content:[{type:"text",text:"<业务JSON>"}]}，其内层
业务 JSON 的字段形态与原直连接口不同，而 render_trace_html.py 等渲染
脚本按原接口结构消费字段。

本脚本按【MCP 实测返回】做字段映射（2026-08-19 实测三个工具确认）：

credible_chat 内层（chat 模式，渲染脚本基本兼容，直通+防御）：
  answer                答案正文（渲染脚本 extract_answer 支持顶层 answer）
  referenceMaterials[]  参考材料（title/url/sourceUrl/unit/content[].text 等，
                        与 source_from_article 字段兼容，直接透传）
  policyFiles[] / recommendationItems[] / trace_report_url  附加信息，透传保留

trusted_search 内层（search 模式，需要映射）：
  materials[{title,source,date,paragraph,url}] → data.检索文章[]
      （渲染脚本 extract_articles_from_search 只认中文键 data.检索文章）
  knowledge_base_url → knowledgeBase / knowledgeBaseUrl（渲染脚本只认驼峰）

deep_query 内层（deep 模式，需要映射）：
  materials[] / search_groups[].materials[] → data.list[]
      （渲染脚本 extract_articles_from_deep 认 data.list）
  progress[]（字符串过程记录）原样保留，供 Agent 综合答案时参考
  答案不由接口给出，由 Agent 基于材料形成后经 --answer-file 传入

用法：
    python3 scripts/adapt_mcp_result.py <mcp返回.json> --output <规范化.json> [--mode chat|search|deep]

- 输入：MCP 工具返回 JSON（mcp_direct.py --output 的产物，或模型保存的
  dsh mcp-client 工具返回；支持 content[].text / structuredContent / 已解包形态）
- 输出：render_trace_html.py 可直接消费的接口 JSON
- --mode：chat=可信咨询 / search=可信搜索 / deep=深度搜索；缺省自动识别
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _deep_find(o: Any, keys, depth=0, max_depth=8):
    """在任意嵌套结构里查找第一个命中任一 key 的非空值。"""
    if depth > max_depth:
        return None
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys and v not in (None, "", [], {}):
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
    - {content: [{type:"text", text:"..."}]}（MCP 标准，text 为业务 JSON 字符串）
    - {structuredContent: {...}}
    - 已是解包后的业务 JSON dict
    """
    if isinstance(o, dict):
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
        # result.content 嵌套形态（完整 MCP JSON-RPC 响应）
        result = o.get("result")
        if isinstance(result, dict):
            return _extract_mcp_text(result)
        # 已是业务 JSON（answer/materials/referenceMaterials 等特征键）
        if any(k in o for k in ("answer", "referenceMaterials", "materials", "检索文章", "progress", "search_meta")):
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


def _material_to_search_article(m: Dict[str, Any]) -> Dict[str, Any]:
    """trusted_search 的 materials 条目 → 渲染脚本认的检索文章结构。

    渲染脚本 source_from_article 认的字段名（多 key 兜底）：
    标题：文章标题/title/标题；来源：unit/sourceElement/数据源/发布机关/来源；
    日期：发布日期/date/发布时间；网址：sourceUrl/source_url/源网址/url/原文；
    摘录：摘要/相关段落/全文/content/text。
    这里把 MCP 的英文字段同时写入中文键与英文键，保证两条提取路径都能命中。
    """
    title = str(m.get("title") or m.get("标题") or "")
    source = str(m.get("source") or m.get("来源") or m.get("unit") or "")
    date = str(m.get("date") or m.get("发布日期") or "")
    url = str(m.get("url") or m.get("sourceUrl") or m.get("源网址") or "")
    paragraph = str(m.get("paragraph") or m.get("content") or m.get("摘要") or "")
    return {
        "标题": title,
        "title": title,
        "来源": source,
        "发布日期": date,
        "date": date,
        "源网址": url,
        "sourceUrl": url,
        "url": url,
        "摘要": paragraph,
        "全文": paragraph,
    }


def _normalize_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化可信咨询（credible_chat）返回。

    MCP 内层已是顶层 answer + referenceMaterials 形态，渲染脚本
    extract_answer / extract_sources / source_from_article 直接兼容，
    此处直通透传，仅做两处防御：
    - answer 缺失时从任意位置兜底找正文，包成渲染脚本认的 resp.content
    - 保留 trace_report_url / policyFiles / recommendationItems 等附加字段
    """
    out = dict(payload)
    if not (isinstance(out.get("answer"), str) and out.get("answer").strip()):
        answer = _deep_find(payload, ("answer", "contentText"))
        if isinstance(answer, str) and answer.strip():
            out["answer"] = answer
    # 渲染脚本 extract_answer 优先找 resp.content；补一份兼容形态
    answer = out.get("answer")
    if isinstance(answer, str) and answer.strip() and not isinstance(out.get("resp"), dict):
        out["resp"] = {"content": answer}
    return out


def _normalize_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化可信搜索（trusted_search）返回：materials → data.检索文章，
    knowledge_base_url → knowledgeBase（驼峰）。
    """
    out = dict(payload)
    materials = payload.get("materials")
    if isinstance(materials, list):
        articles = [_material_to_search_article(m) for m in materials if isinstance(m, dict)]
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        data["检索文章"] = articles
        out["data"] = data
        out["total_articles"] = out.get("total_articles") or len(articles)
    # 兼容旧直连形态（content.data.检索文章）的防御提取
    if not (isinstance(out.get("data"), dict) and isinstance(out["data"].get("检索文章"), list)):
        legacy = _deep_find(payload, ("检索文章",))
        if isinstance(legacy, list) and legacy:
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            data["检索文章"] = [x for x in legacy if isinstance(x, dict)]
            out["data"] = data
    # 知识专库链接：MCP 用下划线 knowledge_base_url，渲染脚本只认驼峰
    kb = payload.get("knowledge_base_url") or payload.get("knowledgeBase") or payload.get("knowledgeBaseUrl")
    if isinstance(kb, str) and kb.strip():
        out["knowledgeBase"] = kb
        out["knowledgeBaseUrl"] = kb
    return out


def _normalize_deep(payload: Dict[str, Any]) -> Dict[str, Any]:
    """规范化深度搜索（deep_query）返回：materials / search_groups → data.list，
    progress（字符串过程）保留，knowledge_base_url 映射驼峰。
    深度搜索答案由 Agent 基于材料与 progress 综合形成，经 --answer-file 传入渲染。
    """
    out = dict(payload)
    items: List[Dict[str, Any]] = []
    mats = payload.get("materials")
    if isinstance(mats, list):
        items.extend([m for m in mats if isinstance(m, dict)])
    groups = payload.get("search_groups")
    if isinstance(groups, list):
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("materials"), list):
                items.extend([m for m in g["materials"] if isinstance(m, dict)])
            elif isinstance(g, dict):
                # search_groups 条目本身可能就是材料（含 title/url 等特征键）
                if any(k in g for k in ("title", "url", "sourceUrl")):
                    items.append(g)
    if items:
        # 渲染脚本 extract_articles_from_deep 消费顶层 data.list
        out["data"] = {"list": items}
    # 兼容旧直连 events 形态的防御提取
    if "data" not in out:
        events = payload.get("events")
        if isinstance(events, list):
            out["events"] = events
    kb = payload.get("knowledge_base_url") or payload.get("knowledgeBase") or payload.get("knowledgeBaseUrl")
    if isinstance(kb, str) and kb.strip():
        out["knowledgeBase"] = kb
        out["knowledgeBaseUrl"] = kb
    return out


def detect_mode(payload: Dict[str, Any]) -> str:
    """按 MCP 实测特征自动识别接口类型。

    deep 的特征键（query_id/progress/search_groups/deep_query_meta）最特异，
    必须先于 search 判断：deep 返回同样携带 materials 键，若先判 search
    会被误判（materials 为空列表也是 list）。
    """
    if (
        "query_id" in payload
        or isinstance(payload.get("progress"), list)
        or isinstance(payload.get("search_groups"), list)
        or isinstance(payload.get("deep_query_meta"), dict)
    ):
        return "deep"
    if isinstance(payload.get("search_meta"), dict) or (
        isinstance(payload.get("materials"), list) and "answer" not in payload
    ):
        return "search"
    return "chat"


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 返回 → 渲染脚本输入 适配器（按 2026-08-19 实测 MCP 结构映射）")
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

    # 1) 提取 MCP 协议层 → 业务 JSON
    text = _extract_mcp_text(raw)
    payload = _try_json(text) if text else None
    if not isinstance(payload, dict):
        # 纯文本回答（无业务 JSON）→ 包成 answer
        payload = {"answer": text or json.dumps(raw, ensure_ascii=False)}

    # 2) 按模式做字段映射
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
