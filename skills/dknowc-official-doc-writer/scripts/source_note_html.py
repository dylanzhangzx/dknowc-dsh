#!/usr/bin/env python3
"""把写作流程的结构化正文/素材 JSON 转成可信搜索同款溯源报告。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import unicodedata
from pathlib import Path


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

INPUT_DIR = WS_ROOT / "official-docs" / "input"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"


def load_renderer():
    path = Path(__file__).with_name("render_trace_html.py")
    spec = importlib.util.spec_from_file_location("dknowc_trace_renderer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载可信溯源报告模板: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_input(value: str) -> Path:
    raw = Path(value).expanduser()
    path = raw.resolve() if raw.is_absolute() else (INPUT_DIR / raw.name).resolve()
    if path.suffix.lower() != ".json":
        raise ValueError("输入文件必须是 JSON")
    try:
        path.relative_to(INPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError(f"输入文件必须位于 official-docs/input/: {value}") from exc
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在: {path}")
    return path


def safe_output(value: str, title: str) -> Path:
    if value:
        raw = Path(value).expanduser()
        path = raw.resolve() if raw.is_absolute() else (OUTPUT_DIR / raw.name).resolve()
    else:
        safe_title = "".join("_" if char in '\\/:*?"<>| ' else char for char in title).strip("_")
        path = (OUTPUT_DIR / f"{safe_title[:80] or '可信溯源报告'}_可信溯源报告.html").resolve()
    if path.suffix.lower() not in {".html", ".htm"}:
        path = path.with_suffix(".html")
    try:
        path.relative_to(OUTPUT_DIR.resolve())
    except ValueError as exc:
        raise ValueError("输出文件必须位于 official-docs/output/") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def first_value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def normalize_title(value: str) -> str:
    """仅用于兼容旧结果的标题兜底匹配；新流程优先使用素材中的 source_url。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def load_source_index() -> dict:
    """从本地搜索结果按文章标题建立原文 URL 索引，补齐上游整理时遗漏的字段。"""
    index = {}
    if not SEARCH_RESULTS_DIR.exists():
        return index
    for path in SEARCH_RESULTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        articles = data.get("articles", [])
        if not isinstance(articles, list):
            content = data.get("content", {})
            payload = content.get("data", {}) if isinstance(content, dict) else {}
            articles = payload.get("检索文章", []) if isinstance(payload, dict) else []
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = first_value(article, "文章标题", "title", "标题")
            if not title:
                continue
            source_url = first_value(article, "源网址", "原文链接", "sourceUrl", "source_url", "url")
            policy_url = first_value(article, "知识专库原文", "policyUrl", "policy_url")
            if source_url or policy_url:
                record = {"source_url": source_url, "policy_url": policy_url}
                index.setdefault(title, record)
                index.setdefault(normalize_title(title), record)
    return index


def to_trace_payload(data: dict) -> tuple[dict, str, str]:
    title = first_value(data, "title", "标题") or "可信溯源报告"
    answer = first_value(data, "document_content", "documentContent", "正文", "body", "answer", "content_markdown")
    if isinstance(data.get("document_content"), list):
        answer = "\n\n".join(first_value(item, "text", "content") for item in data["document_content"] if isinstance(item, dict))
    materials = data.get("materials") or data.get("素材使用情况") or []
    articles = []
    source_index = load_source_index()
    for index, item in enumerate(materials, 1):
        if not isinstance(item, dict):
            continue
        material_name = first_value(item, "material_name", "材料名称", "title", "文章标题") or f"来源材料{index}"
        # 新结果必须直接携带 source_url；标题匹配仅兼容历史 JSON。
        matched = source_index.get(material_name) or source_index.get(normalize_title(material_name), {})
        source_url = first_value(item, "source_url", "sourceUrl", "源网址", "原文链接", "url") or matched.get("source_url", "")
        policy_url = first_value(item, "policyUrl", "policy_url", "knowledgeBase", "知识专库链接") or matched.get("policy_url", "")
        articles.append({
            "文章标题": material_name,
            "来源": first_value(item, "source", "来源", "publisher"),
            "发布日期": first_value(item, "date", "发布日期", "time"),
            "相关段落": first_value(item, "excerpt", "摘录", "支撑内容", "support"),
            "正文对应": first_value(item, "section", "正文对应"),
            "源网址": source_url,
            "知识专库原文": policy_url,
            "policyUrl": first_value(item, "policyUrl", "policy_url"),
            "类型": first_value(item, "type", "素材类型") or "材料",
        })
    knowledge_bases = data.get("knowledge_bases") or data.get("knowledgeBases") or data.get("知识专库链接") or []
    kb_urls = []
    kb_labels = []
    for item in knowledge_bases if isinstance(knowledge_bases, list) else [knowledge_bases]:
        if isinstance(item, dict):
            url = first_value(item, "url", "knowledgeBase", "知识专库链接")
            label = first_value(item, "label", "purpose", "搜索目的", "query") or "相关搜索来源"
        else:
            url = str(item)
            label = "相关搜索来源"
        if url and url not in kb_urls:
            kb_urls.append(url)
            kb_labels.append(label)
    content = {"data": {"检索文章": articles}}
    payload = {"answer": answer, "question": title, "content": content}
    if kb_urls:
        payload["knowledgeBase"] = kb_urls[0]
        payload["knowledgeBases"] = kb_urls
        payload["knowledgeBaseLabels"] = kb_labels
        # 可信搜索渲染器会优先展开 content，必须在该层保留这些字段。
        content["knowledgeBase"] = kb_urls[0]
        content["knowledgeBases"] = kb_urls
        content["knowledgeBaseLabels"] = kb_labels
    return payload, title, answer


def main() -> None:
    parser = argparse.ArgumentParser(description="生成深知可信搜索同款可信溯源报告 HTML")
    parser.add_argument("input", help="结构化可信溯源 JSON，必须位于 official-docs/input")
    parser.add_argument("--output", "-o", help="输出 HTML 文件名，默认写入 official-docs/output")
    args = parser.parse_args()
    input_path = resolve_input(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    payload, title, answer = to_trace_payload(data)
    output_path = safe_output(args.output, title)
    renderer = load_renderer()
    rendered = renderer.render_html(payload, title, answer_override=answer, question_override=title)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"可信溯源报告 HTML 已生成: {output_path}")


if __name__ == "__main__":
    main()
