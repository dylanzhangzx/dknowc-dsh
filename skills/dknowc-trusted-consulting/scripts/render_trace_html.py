#!/usr/bin/env python3
"""Generate an interactive local HTML trace report from DKnownAI API JSON."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 cwd（会话工作区）
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<会话ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"


def _resolve_input(value: str) -> Path:
    """把待读取文件解析到本 Skill 的 official-docs/search-results/ 工作区。

    裸文件名进 search-results/；带子路径的相对路径按 SKILL_ROOT 解析，
    因此 official-docs/search-results/xxx.json 这类写法也可直接使用。
    """
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if raw.parent == Path("."):
        return (SEARCH_RESULTS_DIR / raw.name).resolve()
    return raw.resolve()


def _resolve_output(value: str) -> Path:
    """把交付物解析到本 Skill 的 official-docs/output/ 工作区，自动补 .html 后缀。"""
    raw = Path(value).expanduser()
    if raw.is_absolute():
        resolved = raw.resolve()
    elif raw.parent == Path("."):
        resolved = (OUTPUT_DIR / raw.name).resolve()
    else:
        resolved = raw.resolve()
    if resolved.suffix.lower() not in {".html", ".htm"}:
        resolved = resolved.with_suffix(".html")
    return resolved


def _resolve_output_md(value: str) -> Path:
    """把干净 Markdown 交付物解析到 official-docs/output/ 工作区，自动补 .md 后缀。"""
    raw = Path(value).expanduser()
    if raw.is_absolute():
        resolved = raw.resolve()
    elif raw.parent == Path("."):
        resolved = (OUTPUT_DIR / raw.name).resolve()
    else:
        resolved = raw.resolve()
    if resolved.suffix.lower() != ".md":
        resolved = resolved.with_suffix(".md")
    return resolved


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"data": data}


def unwrap(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get("data"), dict) and data.get("success") is True:
        return data["data"]
    if isinstance(data.get("content"), dict):
        return data["content"]
    return data


def first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


def short(text: Any, limit: int = 360) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def normalize_citations(text: str) -> str:
    text = strip_tags(text)
    return re.sub(r"\[\^?(\d+)\^?\]", r"[\1]", text)


def strip_citation_markers(text: str) -> str:
    text = strip_tags(text)
    text = re.sub(r"【\s*\d+\s*】", "", text)
    text = re.sub(r"\[\^?\d+\^?\]", "", text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


def paragraph_text(item: Dict[str, Any]) -> str:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    if isinstance(paragraphs, list):
        chunks = []
        for para in paragraphs:
            if isinstance(para, dict):
                chunks.append(first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"), para.get("标题"), para.get("title")))
            else:
                chunks.append(str(para))
        text = "\n".join(chunk for chunk in chunks if chunk)
        if text:
            return text
    return first_str(
        item.get("摘录"),
        item.get("摘要"),
        item.get("相关段落"),
        item.get("全文"),
        item.get("content"),
        item.get("text"),
        item.get("snippet"),
    )


def content_segments(item: Dict[str, Any]) -> List[Dict[str, str]]:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    segments: List[Dict[str, str]] = []
    if not isinstance(paragraphs, list):
        return segments
    for para in paragraphs:
        if isinstance(para, dict):
            text = first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"))
            title = first_str(para.get("title"), para.get("标题"), para.get("name"))
            pid = first_str(para.get("id"), para.get("idx"), para.get("index"), para.get("seq"), para.get("编号"))
            if text or title:
                segments.append({"id": pid, "title": title, "text": text})
        else:
            text = first_str(para)
            if text:
                segments.append({"id": "", "title": "", "text": text})
    return segments


def source_from_article(item: Dict[str, Any], index: int, segment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
    segment = segment or {}
    explicit_id = first_str(
        segment.get("id"),
        item.get("角标"),
        item.get("编号"),
        item.get("index"),
        item.get("idx"),
        item.get("seq"),
        item.get("serialNo"),
        item.get("materialIndex"),
        item.get("referenceIndex"),
        item.get("引用编号"),
        vo.get("index"),
        vo.get("idx"),
    )
    if explicit_id:
        match = re.search(r"\d+", explicit_id)
        explicit_id = match.group(0) if match else ""
    source = {
        "id": explicit_id or str(index),
        "title": first_str(
            item.get("文章标题"),
            item.get("title"),
            item.get("标题"),
            item.get("name"),
            vo.get("showTitle"),
            vo.get("title"),
            "未命名材料",
        ),
        "agency": first_str(
            item.get("unit") if not isinstance(item.get("unit"), list) else "、".join(str(x) for x in item.get("unit")[:3]),
            item.get("sourceElement"),
            item.get("数据源"),
            item.get("发布或实施机构"),
            item.get("发布机关"),
            item.get("来源"),
            vo.get("typeName"),
            vo.get("sourceName"),
        ),
        "date": first_str(item.get("发布日期"), item.get("date"), item.get("发布时间"), item.get("createDate"), vo.get("dateTime"), vo.get("createDate")),
        "url": first_str(item.get("sourceUrl"), item.get("source_url"), item.get("源网址"), item.get("url"), item.get("原文"), vo.get("sourceUrl"), vo.get("url")),
        "policy_url": first_str(item.get("policyUrl"), item.get("policy_url"), item.get("知识专库原文"), vo.get("policyUrl")),
        "excerpt": segment.get("text") or paragraph_text(item),
        "section": first_str(segment.get("title")),
        "kind": first_str(item.get("类型"), item.get("type"), vo.get("typeName"), "材料"),
        "area": first_str(item.get("intentionArea"), item.get("area"), item.get("地域")),
        "reliability": first_str(item.get("createDateReliability"), item.get("reliability"), item.get("时间可靠性")),
    }
    return source


def extract_articles_from_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else content.get("data")
    if isinstance(data, dict) and isinstance(data.get("检索文章"), list):
        return [x for x in data["检索文章"] if isinstance(x, dict)]
    return []


def extract_articles_from_deep(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = payload.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, list) and len(event) == 2:
                name, obj = event
            elif isinstance(event, dict):
                name, obj = event.get("event"), event
            else:
                continue
            if name == "result" and isinstance(obj, dict):
                data = obj.get("data")
                result_list = data.get("list") if isinstance(data, dict) else None
                if isinstance(result_list, list):
                    return [x for x in result_list if isinstance(x, dict)]
    data = payload.get("data")
    result_list = data.get("list") if isinstance(data, dict) else None
    if isinstance(result_list, list):
        return [x for x in result_list if isinstance(x, dict)]
    return []


def extract_reference_materials(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    materials = payload.get("referenceMaterials")
    if isinstance(materials, list):
        return [x for x in materials if isinstance(x, dict)]
    return []


def extract_sources(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    raw_sources: List[Dict[str, Any]] = []
    raw_sources.extend(extract_reference_materials(payload))
    raw_sources.extend(extract_articles_from_search(payload))
    raw_sources.extend(extract_articles_from_deep(payload))

    sources: List[Dict[str, str]] = []
    seen = set()
    for item in raw_sources:
        segments = content_segments(item)
        candidates = segments or [None]
        for segment in candidates:
            source = source_from_article(item, len(sources) + 1, segment=segment)
            key = (source["id"], source["title"], source["url"], source["excerpt"][:80])
            if key in seen:
                continue
            seen.add(key)
            if not source["id"]:
                source["id"] = str(len(sources) + 1)
            sources.append(source)
    return sources


def extract_answer(payload: Dict[str, Any]) -> str:
    resp = payload.get("resp")
    if isinstance(resp, dict):
        answer = first_str(resp.get("content"), resp.get("answer"), resp.get("text"))
        if answer:
            return normalize_citations(answer)
    answer = first_str(payload.get("answer"), payload.get("contentText"), payload.get("text"))
    if answer:
        return normalize_citations(answer)
    articles = extract_articles_from_search(payload)
    if articles:
        rows = ["统一接口召回了以下重点材料："]
        for idx, item in enumerate(articles[:8], start=1):
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), item.get('title'), item.get('标题'), '未命名材料')}")
        return "\n".join(rows)
    deep_articles = extract_articles_from_deep(payload)
    if deep_articles:
        rows = ["统一接口召回了以下重点材料："]
        for idx, item in enumerate(deep_articles[:8], start=1):
            vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
            rows.append(f"[{idx}] {first_str(vo.get('showTitle'), vo.get('title'), item.get('title'), '未命名材料')}")
        return "\n".join(rows)
    return "接口返回中未识别到正文内容；请查看右侧来源或原始 JSON。"


def extract_trace_url(payload: Dict[str, Any]) -> str:
    return first_str(payload.get("traceUrl"), payload.get("trace_url"), payload.get("traceReportUrl"))


def extract_knowledge_base(payload: Dict[str, Any]) -> str:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    return first_str(
        content.get("knowledgeBase"),
        payload.get("knowledgeBase"),
        data.get("knowledgeBase"),
        payload.get("knowledgeBaseUrl"),
    )


def citation_ids(answer: str) -> List[str]:
    ids: List[str] = []
    for match in re.finditer(r"\[(\d+)\]", answer):
        item = match.group(1)
        if item not in ids:
            ids.append(item)
    return ids


def render_inline_markdown(text: str, citation_repl) -> str:
    body = esc(text)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"__(.+?)__", r"<strong>\1</strong>", body)
    body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", body)
    body = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", body)
    body = re.sub(r"\[(\d+)\]", citation_repl, body)
    return body


def is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def split_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown_table(lines: List[str], citation_repl) -> str:
    header = split_markdown_table_row(lines[0])
    body_lines = lines[2:] if len(lines) > 1 and is_markdown_table_separator(lines[1]) else lines[1:]
    head_html = "".join(f"<th>{render_inline_markdown(cell, citation_repl)}</th>" for cell in header)
    rows = []
    for line in body_lines:
        cells = split_markdown_table_row(line)
        rows.append("<tr>" + "".join(f"<td>{render_inline_markdown(cell, citation_repl)}</td>" for cell in cells) + "</tr>")
    return f'<div class="answer-table-wrap"><table class="answer-table"><thead><tr>{head_html}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_excerpt_html(text: str) -> str:
    value = str(text or "")
    if "<table" not in value.lower():
        return f'<div class="source-excerpt plain">{esc(value)}</div>'
    cleaned = re.sub(r"(?is)<script.*?</script>", "", value)
    cleaned = re.sub(r"(?is)<style.*?</style>", "", cleaned)
    cleaned = re.sub(r"\s+on\w+\s*=\s*(['\"]).*?\1", "", cleaned)
    cleaned = re.sub(r"\s+(href|src)\s*=\s*(['\"]).*?\2", "", cleaned)
    allowed = {"table", "thead", "tbody", "tr", "td", "th", "br"}

    def tag_repl(match: re.Match[str]) -> str:
        closing, name = match.group(1), match.group(2).lower()
        if name not in allowed:
            return ""
        return f"<{closing}{name}>"

    cleaned = re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", tag_repl, cleaned)
    return f'<div class="source-excerpt rich">{cleaned}</div>'


def render_source_links(url: str, policy_url: str = "") -> str:
    links = []
    if url and url != "接口未返回":
        links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">查看原文</a>')
    if policy_url:
        links.append(f'<a href="{esc(policy_url)}" target="_blank" rel="noopener">知识专库原文</a>')
    if not links:
        return ""
    return '<div class="source-links">' + "".join(f"<span>{link}</span>" for link in links) + "</div>"


def render_evidence_chips(ids: List[str], sources: List[Dict[str, str]]) -> str:
    source_map = {source["id"]: source for source in sources}
    chips = []
    for cid in ids:
        source = source_map.get(cid)
        if not source:
            continue
        title = source.get("title") or "未命名材料"
        section = source.get("section") or ""
        meta = " | ".join(v for v in [source.get("agency"), source.get("date"), source.get("area"), source.get("kind")] if v)
        excerpt = source.get("excerpt") or "接口返回中未识别到可展示的摘录。"
        url = source.get("url")
        links = render_source_links(url, source.get("policy_url", ""))
        chips.append(
            f"""
            <details class="evidence-detail" data-source="{esc(cid)}">
              <summary><b>[{esc(cid)}]</b>{esc(short(title, 64))}</summary>
              <div class="evidence-panel">
                <div class="evidence-title">{esc(title)}</div>
                <div class="evidence-meta">{esc(meta)}</div>
                {f'<div class="evidence-section">{esc(section)}</div>' if section else ''}
                <p>{esc(excerpt)}</p>
                {links}
              </div>
            </details>
            """
        )
    if not chips:
        return ""
    return f'<div class="evidence-row">{"".join(chips)}</div>'


def render_answer(answer: str, sources: List[Dict[str, str]]) -> str:
    valid_ids = {source["id"] for source in sources}

    def repl(match: re.Match[str]) -> str:
        cid = match.group(1)
        disabled = "" if cid in valid_ids else " disabled"
        return f'<button class="cite{disabled}" data-source="{esc(cid)}" type="button">[{esc(cid)}]</button>'

    paragraphs = []
    lines = answer.split("\n")
    idx = 0
    while idx < len(lines):
        raw_block = lines[idx]
        block = raw_block.strip()
        if not block:
            idx += 1
            continue
        if "|" in block and idx + 1 < len(lines) and is_markdown_table_separator(lines[idx + 1]):
            table_lines = [block, lines[idx + 1].strip()]
            idx += 2
            while idx < len(lines) and "|" in lines[idx].strip() and lines[idx].strip():
                table_lines.append(lines[idx].strip())
                idx += 1
            ids = citation_ids("\n".join(table_lines))
            paragraphs.append(f'<div class="answer-block">{render_markdown_table(table_lines, repl)}{render_evidence_chips(ids, sources)}</div>')
            continue
        ids = citation_ids(block)
        evidence = render_evidence_chips(ids, sources)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading_match:
            level = min(len(heading_match.group(1)) + 1, 4)
            heading = render_inline_markdown(heading_match.group(2), repl)
            paragraphs.append(f'<h{level} class="answer-heading">{heading}</h{level}>')
        elif block in {"---", "***"}:
            paragraphs.append('<hr class="answer-divider">')
        elif re.match(r"^[-*]\s+", block):
            body = render_inline_markdown(re.sub(r"^[-*]\s+", "", block), repl)
            paragraphs.append(
                f'<div class="answer-item"><span class="bullet">•</span><div><p>{body}</p>{evidence}</div></div>'
            )
        elif re.match(r"^\d+[.)]\s+", block):
            number = re.match(r"^(\d+)[.)]\s+", block).group(1)
            body = render_inline_markdown(re.sub(r"^\d+[.)]\s+", "", block), repl)
            paragraphs.append(
                f'<div class="answer-item numbered"><span class="bullet">{esc(number)}.</span><div><p>{body}</p>{evidence}</div></div>'
            )
        else:
            body = render_inline_markdown(block, repl)
            paragraphs.append(f'<div class="answer-block"><p>{body}</p>{evidence}</div>')
        idx += 1
    return "\n".join(paragraphs)


def render_sources(sources: List[Dict[str, str]]) -> str:
    if not sources:
        return '<p class="empty">接口返回中未识别到可展示的材料。</p>'
    cards = []
    for source in sources:
        url = source.get("url")
        links = render_source_links(url, source.get("policy_url", ""))
        meta = " | ".join(v for v in [source.get("agency"), source.get("date"), source.get("area"), source.get("kind")] if v)
        section = source.get("section") or ""
        cards.append(
            f"""
            <article class="source-card" id="source-{esc(source['id'])}" data-source="{esc(source['id'])}">
              <div class="source-top">
                <span class="source-index">[{esc(source['id'])}]</span>
                <h3>{esc(source.get("title"))}</h3>
              </div>
              <p class="meta">{esc(meta)}</p>
              {f'<p class="section">{esc(section)}</p>' if section else ''}
              {render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")}
              {links}
            </article>
            """
        )
    return "\n".join(cards)


def align_sources_to_answer(answer: str, sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cited = citation_ids(answer)
    if not cited or not sources:
        return sources
    existing = {source["id"] for source in sources}
    if existing.intersection(cited):
        return sources
    aligned = [dict(source) for source in sources]
    for idx, citation in enumerate(cited):
        if idx >= len(aligned):
            break
        aligned[idx]["id"] = citation
    return aligned


def extract_question(payload: Dict[str, Any]) -> str:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    return first_str(
        payload.get("question"),
        payload.get("input"),
        payload.get("query"),
        data.get("用户问题"),
        content.get("query"),
        content.get("question"),
    )


def render_entry_chip(kb_url: str, source_count: int) -> str:
    if not kb_url:
        return ""
    count_text = f"{source_count}条来源" if source_count else "来源材料"
    return (
        f'<a class="kb-chip" href="{esc(kb_url)}" target="_blank" rel="noopener">'
        f'<span class="kb-label">知识专库</span>'
        f'<span class="kb-count">{esc(count_text)}</span>'
        f'<span class="kb-arrow">查看</span>'
        f'</a>'
    )


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_consulting_trace") -> str:
    raw = question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    suffix = timestamp.strftime("%Y%m%d_%H%M")
    stem = normalized[:32].strip("._-") or fallback
    return f"{stem}_{suffix}.html"


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "", generated_at: Optional[datetime] = None) -> str:
    payload = unwrap(payload)
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    sources = align_sources_to_answer(answer, extract_sources(payload))
    used = citation_ids(answer)
    kb_url = extract_knowledge_base(payload)
    question = question_override.strip() or extract_question(payload)
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")
    kb_link = f'<a href="{esc(kb_url)}" target="_blank" rel="noopener">知识专库</a>' if kb_url else ""
    links = kb_link
    tools_html = f'<div class="tools">{links}</div>' if links else ""
    question_html = f'<div class="question-bubble">{esc(question)}</div>' if question else ""
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warning-box">'
            '<b>生成检查提示：</b>本轮最终答案没有包含来源角标，因此无法在答案段落下做“结论-来源”一一对应。'
            '请重新生成最终答案，并在关键结论后标注接口材料编号，例如 [1]、[2]。'
            '</div>'
        )
    note_text = "AI综合所有相关权威材料后，参考性解读如下，建议点击角标查看所依据的材料原文。"
    compact_answer_start = re.sub(r"\s+", "", answer.lstrip()[:120])
    compact_note_start = re.sub(r"\s+", "", note_text[:36])
    note_html = "" if compact_answer_start.startswith(compact_note_start) else f'<p class="ai-note">{esc(note_text)}</p>'
    product_links_html = (
        '<nav class="product-links" aria-label="产品链接">'
        '<a href="https://yun.dknowc.cn/wlcb/dknowc-chat/#/" target="_blank" rel="noopener">深知晓内测</a>'
        '<a href="https://www.dknowc.cn/" target="_blank" rel="noopener">深知可信智能官网</a>'
        '</nav>'
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --purple: #6b18c9;
      --purple-soft: #f4ebff;
      --ink: #2f3033;
      --muted: #6b7280;
      --line: #e5e7eb;
      --panel: #ffffff;
      --page: #ffffff;
      --soft: #f7f7f8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--page);
    }}
    header {{
      padding: 12px 28px;
      background: #fff;
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 2;
      text-align: center;
    }}
    h1 {{ margin: 0 0 3px; font-size: 16px; letter-spacing: 0; font-weight: 700; }}
    header p {{ margin: 0; color: #9ca3af; font-size: 12px; }}
    .product-links {{
      display: flex;
      justify-content: center;
      gap: 14px;
      margin-top: 8px;
      font-size: 12px;
    }}
    .product-links a {{
      color: var(--purple);
      text-decoration: none;
      font-weight: 600;
    }}
    .product-links a:hover {{ text-decoration: underline; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 700px) minmax(390px, 460px);
      gap: 30px;
      justify-content: center;
      max-width: 1220px;
      margin: 0 auto;
      padding: 30px 18px 40px;
    }}
    .conversation {{
      min-width: 0;
    }}
    .question-bubble {{
      max-width: 560px;
      margin: 0 0 26px auto;
      padding: 12px 16px;
      border-radius: 9px;
      background: var(--purple);
      color: #fff;
      line-height: 1.55;
      font-weight: 700;
      font-size: 14px;
    }}
    .answer {{
      background: transparent;
      padding: 0;
    }}
    .kb-chip {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      max-width: 100%;
      margin: 0 0 16px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      color: #4b5563;
      background: #fafafa;
      text-decoration: none;
      box-shadow: none;
      font-size: 12px;
    }}
    .kb-chip:hover {{ border-color: #d1d5db; background: #f7f7f8; }}
    .kb-label {{ font-weight: 700; color: #374151; }}
    .kb-count {{
      padding-left: 10px;
      border-left: 1px solid var(--line);
      color: #6b7280;
    }}
    .kb-arrow {{
      color: var(--purple);
      font-weight: 700;
    }}
    .ai-note {{ margin: 0 0 10px; color: #52525b; line-height: 1.75; font-size: 14px; }}
    .answer-body {{
      padding: 0;
      background: transparent;
    }}
    .answer-block, .answer-item {{ margin: 0 0 12px; }}
    .answer-item {{ display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; }}
    .answer-item .bullet {{ padding-top: 2px; color: #111827; font-size: 16px; line-height: 1.75; }}
    .answer-item.numbered {{ grid-template-columns: 28px minmax(0, 1fr); }}
    .answer p {{ margin: 0; font-size: 14px; line-height: 1.85; }}
    .answer strong {{ font-weight: 700; color: #202124; }}
    .answer em {{ font-style: normal; color: #4b5563; }}
    .answer code {{
      padding: 1px 5px;
      border-radius: 4px;
      background: #f3f4f6;
      color: #374151;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    .answer-table-wrap {{ max-width: 100%; overflow-x: auto; margin: 6px 0 8px; }}
    .answer-table {{
      width: 100%;
      border-collapse: collapse;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      font-size: 13px;
    }}
    .answer-table th, .answer-table td {{
      padding: 9px 10px;
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      line-height: 1.65;
    }}
    .answer-table th {{ background: #f8fafc; font-weight: 700; color: #374151; }}
    .answer-heading {{ margin: 20px 0 9px; color: #111827; line-height: 1.45; letter-spacing: 0; }}
    h2.answer-heading {{ font-size: 18px; }}
    h3.answer-heading {{ font-size: 16px; }}
    h4.answer-heading {{ font-size: 15px; }}
    .answer-divider {{ border: 0; border-top: 1px solid var(--line); margin: 22px 0; }}
    .warning-box {{
      margin: 0 0 16px;
      padding: 12px 14px;
      border: 1px solid #f59e0b;
      border-radius: 8px;
      background: #fffbeb;
      color: #92400e;
      line-height: 1.7;
      font-size: 14px;
    }}
    .cite {{
      margin: 0 2px;
      padding: 0 5px;
      border: 0;
      border-radius: 4px;
      color: var(--purple);
      background: var(--purple-soft);
      font-weight: 700;
      cursor: pointer;
      vertical-align: super;
      font-size: 10px;
      line-height: 1.4;
    }}
    .cite.disabled {{ color: #9ca3af; background: #f3f4f6; cursor: default; }}
    .evidence-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 5px 0 0;
    }}
    .evidence-detail {{
      max-width: 100%;
    }}
    .evidence-detail summary {{
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      border-radius: 999px;
      padding: 4px 9px;
      color: #6b7280;
      background: #f3f4f6;
      cursor: pointer;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      list-style: none;
      font-size: 12px;
    }}
    .evidence-detail summary::-webkit-details-marker {{ display: none; }}
    .evidence-detail summary::after {{
      content: "展开";
      margin-left: 7px;
      color: #9ca3af;
      font-size: 11px;
    }}
    .evidence-detail[open] summary::after {{ content: "收起"; }}
    .evidence-detail summary b {{ color: var(--purple); margin-right: 5px; }}
    .evidence-panel {{
      margin: 7px 0 4px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
    }}
    .evidence-title {{ font-weight: 700; font-size: 14px; margin-bottom: 5px; color: #111827; }}
    .evidence-meta {{ color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    .evidence-section {{ color: var(--purple); font-size: 12px; margin-bottom: 6px; font-weight: 700; }}
    .evidence-panel p {{ margin: 0 0 8px; color: #374151; font-size: 13px; line-height: 1.7; }}
    .evidence-panel a {{ color: var(--purple); font-weight: 700; text-decoration: none; }}
    .source-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
    }}
    .source-links span {{
      display: inline-flex;
    }}
    .source-links a {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 8px;
      border-radius: 6px;
      background: var(--purple-soft);
      color: var(--purple);
      font-weight: 700;
      text-decoration: none;
      font-size: 12px;
    }}
    .tools {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 20px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .tools a {{
      color: var(--purple);
      background: var(--purple-soft);
      border-radius: 999px;
      padding: 7px 12px;
      text-decoration: none;
      font-weight: 600;
    }}
    .sources {{
      align-self: start;
      position: sticky;
      top: 70px;
      max-height: calc(100vh - 92px);
      overflow: auto;
      background: #fff;
      border-left: 1px solid var(--line);
      padding: 16px 0 16px 24px;
    }}
    .sources h2 {{ margin: 0 0 12px; font-size: 15px; }}
    .searchbox {{
      width: 100%;
      margin: 0 0 14px;
      padding: 9px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      color: #6b7280;
      background: #fff;
    }}
    .source-card {{
      padding: 14px 0 15px;
      border: 0;
      border-bottom: 1px solid #f1f1f2;
      border-radius: 0;
      margin-bottom: 0;
      background: #fff;
    }}
    .source-card.active {{
      margin-left: -10px;
      padding-left: 10px;
      border-left: 3px solid var(--purple);
      background: #fbf8ff;
      box-shadow: none;
    }}
    .source-top {{
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 7px;
      align-items: start;
      margin-bottom: 6px;
    }}
    .source-index {{
      color: var(--purple);
      background: var(--purple-soft);
      border-radius: 5px;
      padding: 1px 5px;
      font-weight: 800;
      font-size: 12px;
      line-height: 1.5;
    }}
    .source-card h3 {{ margin: 0; font-size: 13px; line-height: 1.55; letter-spacing: 0; }}
    .source-card p {{ margin: 0 0 7px; color: #374151; line-height: 1.72; font-size: 12px; }}
    .source-card .meta {{ color: var(--muted); font-size: 12px; line-height: 1.55; }}
    .source-card .section {{ color: var(--purple); font-size: 12px; font-weight: 700; }}
    .source-card a {{ color: var(--purple); font-weight: 700; text-decoration: none; font-size: 12px; }}
    .source-card .source-excerpt {{
      margin: 8px 0 8px;
      padding: 9px 10px;
      border-radius: 7px;
      background: #f8fafc;
      color: #374151;
      font-size: 12px;
      line-height: 1.75;
    }}
    .source-excerpt.rich {{
      overflow-x: auto;
      max-width: 100%;
    }}
    .source-excerpt.rich table {{
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      background: #fff;
      font-size: 12px;
      line-height: 1.55;
    }}
    .source-excerpt.rich td, .source-excerpt.rich th {{
      min-width: 92px;
      max-width: 220px;
      padding: 7px 8px;
      border: 1px solid #e5e7eb;
      vertical-align: top;
      word-break: break-word;
    }}
    .source-excerpt.rich thead td, .source-excerpt.rich th {{
      background: #f3f4f6;
      color: #374151;
      font-weight: 700;
    }}
    .empty {{ color: var(--muted); }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; padding: 14px; }}
      .sources {{ position: static; max-height: none; }}
      .question-bubble {{ margin-left: 0; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{esc(title)}</h1>
    <p>内容为 AI 生成，仅供参考｜生成时间：{esc(generated)}</p>
    {product_links_html}
  </header>
  <main class="layout">
    <section class="conversation" aria-label="回答正文">
      {question_html}
      <div class="answer">
        {render_entry_chip(kb_url, len(sources))}
        {note_html}
        {citation_warning}
        <div class="answer-body">{render_answer(answer, sources)}</div>
        {tools_html}
      </div>
    </section>
    <aside class="sources" aria-label="可信来源">
      <h2>可信来源</h2>
      <input class="searchbox" type="search" placeholder="搜索来源标题或摘录">
      {render_sources(sources)}
    </aside>
  </main>
  <script>
    const cards = Array.from(document.querySelectorAll(".source-card"));
    function activate(id) {{
      cards.forEach(card => card.classList.toggle("active", card.dataset.source === id));
      const target = document.querySelector(`#source-${{CSS.escape(id)}}`);
      if (target) target.scrollIntoView({{ block: "nearest", behavior: "smooth" }});
    }}
    document.querySelectorAll(".cite").forEach(button => {{
      if (button.classList.contains("disabled")) return;
      button.addEventListener("click", () => activate(button.dataset.source));
    }});
    document.querySelectorAll(".evidence-detail").forEach(detail => {{
      detail.addEventListener("toggle", () => {{
        if (!detail.open) return;
        cards.forEach(card => card.classList.toggle("active", card.dataset.source === detail.dataset.source));
      }});
    }});
    const searchbox = document.querySelector(".searchbox");
    if (searchbox) {{
      searchbox.addEventListener("input", () => {{
        const value = searchbox.value.trim().toLowerCase();
        cards.forEach(card => {{
          card.style.display = !value || card.innerText.toLowerCase().includes(value) ? "" : "none";
        }});
      }});
    }}
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成深知可信咨询可交互可信溯源 HTML")
    parser.add_argument("input_json", help="gov_chat.py 的 --json-only 输出 JSON（位于 official-docs/search-results/）")
    parser.add_argument("--output", help="输出 HTML 路径；不传时根据问题自动生成短文件名到 official-docs/output/")
    parser.add_argument("--title", default="深知可信咨询可信溯源", help="页面标题")
    parser.add_argument("--answer-file", help="最终回答正文文件。复杂任务综合后必须传入，确保 HTML 展示的答案与聊天答案一致。")
    parser.add_argument("--clean-md-output", help="输出干净 Markdown 路径；内容来自同一份最终答案，并移除 [1]、【1】等溯源角标。")
    parser.add_argument("--question", default="", help="用户问题，用于生成顶部对话气泡。")
    args = parser.parse_args()

    input_path = _resolve_input(args.input_json)
    payload = load_json(input_path)
    answer_override = ""
    if args.answer_file:
        answer_override = _resolve_input(args.answer_file).read_text(encoding="utf-8")
    question = args.question.strip() or extract_question(unwrap(payload))
    generated_at = datetime.now()
    if args.output:
        output = _resolve_output(args.output)
    else:
        output = _resolve_output(safe_output_filename(question, generated_at))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payload, args.title, answer_override=answer_override, question_override=args.question, generated_at=generated_at), encoding="utf-8")
    print(f"已生成：{output}")
    if args.clean_md_output:
        clean_output = _resolve_output_md(args.clean_md_output)
    else:
        clean_output = _resolve_output_md(output.with_suffix(".clean.md").name)
    clean_output.parent.mkdir(parents=True, exist_ok=True)
    clean_answer = strip_citation_markers(answer_override or extract_answer(unwrap(payload)))
    clean_output.write_text(clean_answer, encoding="utf-8")
    print(f"已生成干净 Markdown：{clean_output}")


if __name__ == "__main__":
    main()
