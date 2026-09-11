#!/usr/bin/env python3
"""深知可信咨询 · 可信核验报告渲染器：把统一问答 JSON 渲染为单文件可核验 HTML。

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。
三个核验层次：
- 报告级：核验报告单（依据溯源 / 引用对应 / 材料新旧 / 交付前检查）
- 材料级：每条来源卡核验链标记（摘录可比对 + 原文可打开 + 知识专库可回溯）
- 引用级：答案角标与来源卡一一绑定，未绑定角标红色警示

诚实原则：脚本真实计算的结果才打勾；政策现行效力等无法自动判定项归入
"建议人工复核"；self_check 未传入时显示"未记录"，不假装通过。
生成前硬校验：识别到来源材料而答案无 [n] 角标时拒绝生成并报错。

布局：深色顶栏 + 左栏报告正文（分节卡片）+ 右栏核验材料面板（搜索）；
打印归档模式（@media print 单栏全展开）。同时输出移除角标的干净 Markdown。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 基础工具
# ============================================================

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
    text = re.sub(r"【\s*(\d+)\s*】", r"[\1]", text)
    return re.sub(r"\[\^?(\d+)\^?\]", r"[\1]", text)


def strip_citation_markers(text: str) -> str:
    text = strip_tags(text)
    text = re.sub(r"【\s*\d+\s*】", "", text)
    text = re.sub(r"\[\^?\d+\^?\]", "", text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ============================================================
# 工作区路径（official-docs 约定）
# ============================================================

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 cwd
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"


def _resolve_input(value: str) -> Path:
    """把待读取文件解析到本 Skill 的 official-docs/search-results/ 工作区。

    裸文件名进 search-results/；带子路径的相对路径按当前目录解析，
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


_SOURCE_HEADINGS = {"来源", "来源清单", "参考来源"}


def _normalize_source_heading(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^[#>\s*\-]+", "", value)
    value = re.sub(r"[\s:*#：:]+$", "", value)
    return value


def _is_source_entry(line: str) -> bool:
    value = line.strip()
    if re.match(r"^(\[\^?\d+\^?\]|【\d+】)\s*", value):
        return True
    return value.startswith("《")


def strip_trailing_source_list(text: str) -> str:
    """去除答案末尾的"来源"清单块。

    来源清单只应在对话输出中展示：核验报告由右栏核验材料面板承载来源，
    clean.md 保持纯正文。仅当标题行之后全部非空行都是来源条目时才剥离，
    避免误删正文中恰好出现"来源"字样的段落。
    """
    lines = text.split("\n")
    cut = -1
    for i, line in enumerate(lines):
        if _normalize_source_heading(line) in _SOURCE_HEADINGS:
            tail = [l.strip() for l in lines[i + 1:] if l.strip()]
            if tail and all(_is_source_entry(t) for t in tail):
                cut = i
    if cut < 0:
        return text
    return "\n".join(lines[:cut]).rstrip()


def renumber_citations(answer: str, sources: List[Dict[str, str]]) -> tuple:
    """把被引用角标按首次出现顺序重编号为 1..n，未引用材料顺延编号。

    统一问答接口返回的材料自带全量召回序号（如 101、601），直接透传会让
    报告角标从三位数开始；交付视角应使用连续编号，同时保持角标与材料
    一一对应。未绑定角标（不对应任何材料）保持原样，由生成前硬校验拦截。
    返回（重编号后答案, 重编号后来源列表, 旧编号→新编号映射）。
    """
    source_ids = {s["id"] for s in sources}
    cited = [cid for cid in citation_ids(answer) if cid in source_ids]
    mapping = {old: str(i + 1) for i, old in enumerate(cited)}
    next_no = len(mapping)
    for source in sources:
        old = source["id"]
        if old in mapping and mapping[old] != old:
            source["id"] = mapping[old]
        elif old not in mapping:
            next_no += 1
            mapping[old] = str(next_no)
            source["id"] = mapping[old]

    def repl(match: "re.Match[str]") -> str:
        cid = match.group(1)
        return f"[{mapping.get(cid, cid)}]"

    answer = re.sub(r"\[(\d+)\]", repl, answer)
    return answer, sources, mapping


# ============================================================
# 素材提取（沿用原数据层）
# ============================================================

def parse_year_month(raw: str) -> Optional[Tuple[int, int]]:
    """从日期文本提取（年, 月）；识别 2025年8月 / 2025-08 / 2025.08 / 2025-08-15。"""
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.search(r"(20\d{2})\s*[年./-]\s*(\d{1,2})", text)
    if m:
        return int(m.group(1)), min(int(m.group(2)), 12)
    m = re.search(r"(20\d{2})", text)
    if m:
        return int(m.group(1)), 1
    return None

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
        item.get("支撑内容"),
        item.get("support"),
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


def source_from_article(item: Dict[str, Any], index: int) -> Dict[str, str]:
    vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
    # 角标号只用"材料级"编号：接口段落 id（每篇从 1 重排）不得作为角标号，否则多篇绑定冲突。
    explicit_id = first_str(
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
            item.get("material_name"),
            item.get("材料名称"),
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
        "url": first_str(item.get("sourceUrl"), item.get("source_url"), item.get("源网址"), item.get("原文链接"), item.get("url"), item.get("原文"), vo.get("sourceUrl"), vo.get("url")),
        "policy_url": first_str(item.get("policyUrl"), item.get("policy_url"), item.get("知识专库原文"), vo.get("policyUrl")),
        # 一篇材料一张卡：段落全部合并为摘录（不再按段拆卡，防止角标语义错位）
        "excerpt": paragraph_text(item),
        "section": first_str(item.get("正文对应"), item.get("section"), item.get("支撑")),
        "verify_note": first_str(item.get("核验"), item.get("verification"), item.get("核验说明")),
        "area": first_str(item.get("intentionArea"), item.get("area"), item.get("地域")),
        # 发布日期可信度（"高"=模型治理入库，标题模型精抽；其余为门户抓取不标）
        "conf": first_str(item.get("发布日期可信度"), item.get("可信度"), item.get("confidence"), item.get("createDateReliability"), item.get("时间可靠性"), item.get("reliability")),
    }
    # 原文位置标题链：接口返回的段落标题即该段在原文件中的章节位置（层级以 > 分隔），统一转 ›。
    # 一篇材料多段时取首个非空段落标题作位置；无段落标题如实不显示。
    seg_title = ""
    for seg in content_segments(item):
        if first_str(seg.get("title")):
            seg_title = first_str(seg.get("title"))
            break
    seg_title = re.sub(r"\s*>\s*", " › ", seg_title).strip("› ").strip()
    if seg_title and seg_title != source["title"]:
        source["doc_section"] = seg_title
        source["chain_full"] = f"{source['title']} › {seg_title}"
    else:
        source["doc_section"] = ""
        source["chain_full"] = ""
    source["has_link"] = bool(source["url"] and source["url"] != "接口未返回") or bool(source["policy_url"])
    source["verified"] = bool(source["excerpt"]) and source["has_link"]
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
        # 一篇材料一张卡：角标按"材料"粒度与正文一一对应，段落合并为摘录，不按段拆卡。
        source = source_from_article(item, len(sources) + 1)
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
        rows = ["可信搜索召回了以下重点材料："]
        for idx, item in enumerate(articles[:8], start=1):
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), item.get('title'), item.get('标题'), '未命名材料')}")
        return "\n".join(rows)
    deep_articles = extract_articles_from_deep(payload)
    if deep_articles:
        rows = ["深度搜索召回了以下重点材料："]
        for idx, item in enumerate(deep_articles[:8], start=1):
            vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
            rows.append(f"[{idx}] {first_str(vo.get('showTitle'), vo.get('title'), item.get('title'), '未命名材料')}")
        return "\n".join(rows)
    return "接口返回中未识别到正文内容；请查看右侧来源或原始 JSON。"


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


def extract_knowledge_base(payload: Dict[str, Any]) -> str:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    return first_str(
        content.get("knowledgeBase"),
        payload.get("knowledgeBase"),
        data.get("knowledgeBase"),
        payload.get("knowledgeBaseUrl"),
    )


def extract_trace_archives(payload: Dict[str, Any]) -> List[str]:
    """收集"云端溯源存档"链接。

    统一问答接口与公文写作的搜索接口不同：不返回可再浏览的知识专库
    knowledgeBase 链接，实际提供 traceUrl——云平台为本次问答生成的接口侧
    可信溯源报告。两种字段都兼容，避免接口字段调整时丢链接。
    """
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    values: List[str] = []
    for value in (payload.get("knowledgeBases"), content.get("knowledgeBases"), payload.get("knowledgeBase"), content.get("knowledgeBase")):
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            values.append(value.strip())
    trace = first_str(payload.get("traceUrl"), payload.get("trace_url"), content.get("traceUrl"), content.get("trace_url"))
    if trace:
        values.append(trace)
    return list(dict.fromkeys(values))


def citation_ids(answer: str) -> List[str]:
    ids: List[str] = []
    for match in re.finditer(r"\[(\d+)\]", answer):
        item = match.group(1)
        if item not in ids:
            ids.append(item)
    return ids


# ============================================================
# 核验计算（报告级）
# ============================================================

SELF_CHECK_ITEMS = [
    ("citation_present", "角标存在"),
    ("citation_bound", "角标对应来源"),
    ("statement_verifiable", "结论可核验"),
    ("answer_consistent", "答案一致"),
    ("source_list_covered", "来源清单覆盖"),
]

SELF_CHECK_LABELS = dict(SELF_CHECK_ITEMS)
SELF_CHECK_LABELS.update({
    "角标存在": "角标存在", "角标对应来源": "角标对应来源", "结论可核验": "结论可核验",
    "答案一致": "答案一致", "来源清单覆盖": "来源清单覆盖",
})


def classify_check_value(raw: Any) -> Tuple[str, str]:
    """把自检项的值解析为（状态, 核验说明）。

    兼容多种写法：`pass` / `true` / `通过` / `通过：说明文字` / `✓` 等；
    值后面的说明文字保留下来供核验单展示。无法识别的状态按未通过处理，
    并保留原文，不假装通过。
    """
    text = str(raw or "").strip()
    lowered = text.lower()
    for prefix in ("未通过", "不通过", "不合格", "fail", "false", "否", "✗", "no"):
        if lowered.startswith(prefix):
            return "fail", text[len(prefix):].lstrip("：:，,、 ").strip()
    for prefix in ("已通过", "通过", "合格", "pass", "ok", "true", "是", "✓", "yes"):
        if lowered.startswith(prefix):
            return "pass", text[len(prefix):].lstrip("：:，,、 ").strip()
    return "fail", text


def normalize_self_check(raw: Any) -> Optional[Dict[str, Tuple[str, str]]]:
    if not isinstance(raw, dict):
        return None
    items: Dict[str, Tuple[str, str]] = {}
    for key, value in raw.items():
        status, note = classify_check_value(value)
        label = SELF_CHECK_LABELS.get(key, SELF_CHECK_LABELS.get(str(key), str(key)))
        items[label] = (status, note)
    return items or None


def compute_verification(answer: str, sources: List[Dict[str, str]], payload: Dict[str, Any],
                         generated_at: Optional[datetime] = None) -> Dict[str, Any]:
    """核验报告单数据。只计算脚本真实可得的结果，不虚构通过。"""
    generated_at = generated_at or datetime.now()

    # ① 依据溯源：只统计正文引用材料（未引用召回未进入正文核验流程，缺链不影响结论）
    used_ids = set(citation_ids(answer))
    used_sources = [s for s in sources if s["id"] in used_ids]
    missing_links = [s["title"] for s in used_sources if not s.get("has_link")]
    missing_excerpts = [s["title"] for s in used_sources if not (s.get("excerpt") or "").strip()]
    trace_passed = len(used_sources) - len(set(missing_links) | set(missing_excerpts))

    # ② 引用对应：正文角标与来源卡一一对应（按角标出现次数计，与用户在正文中数到的一致）
    cited = citation_ids(answer)
    all_marks = re.findall(r"\[(\d+)\]", answer)
    source_ids = {s["id"] for s in sources}
    unbound_ids = [cid for cid in cited if cid not in source_ids]
    unbound = [cid for cid in unbound_ids for _ in range(all_marks.count(cid))]
    no_citation = bool(sources) and not cited

    # ③ 材料新旧：材料日期范围与历史材料计数
    dated = [parse_year_month(s.get("date")) for s in sources]
    dated = [d for d in dated if d]
    freshness = None
    old_count = 0
    if dated:
        freshness = {
            "min": min(dated),
            "max": max(dated),
            "old_count": sum(1 for y, _ in dated if y <= generated_at.year - 3),
        }

    # ⑤ 交付前检查：由 --self-check-file 或 JSON 的 self_check 传入，未传入如实显示未记录
    self_check_raw = None
    for holder in (payload, payload.get("content") if isinstance(payload.get("content"), dict) else {}):
        self_check_raw = self_check_raw or holder.get("selfCheck") or holder.get("self_check")
    self_items = normalize_self_check(self_check_raw)
    self_check = None
    if self_items:
        passed = sum(1 for status, _ in self_items.values() if status == "pass")
        self_check = {"items": self_items, "passed": passed, "total": len(self_items),
                      "status": "pass" if passed == len(self_items) else "fail"}
    else:
        self_check = {"items": {}, "passed": 0, "total": len(SELF_CHECK_ITEMS), "status": "missing"}

    # 政策效力：无法自动判定现行效力，列出建议人工复核
    policy_count = len(used_sources)

    # 交付状态约束：核验报告是交付物，交付时必须为核验通过状态。
    # Agent 可修正的问题（无角标/未绑定/自检未过）在生成前已被硬校验拦截；
    # 仅接口未返回原文链接、政策效力无法自动判定等不可抗因素以温和提示呈现，
    # 不作为核验失败。
    binding_ok = (not unbound) and not no_citation
    overall_passed = bool(sources) and binding_ok

    reasons = []
    if not sources:
        reasons.append("未识别到来源材料")
    if no_citation:
        reasons.append("答案未包含来源角标，无法建立引用-材料对应")
    if unbound:
        reasons.append(f"{len(unbound)} 处答案角标未绑定材料")
    if self_check["status"] == "fail":
        reasons.append("交付前检查存在未通过项")

    return {
        "overall": {
            "passed": overall_passed,
            "label": "核验完成，答案依据逐条对过原文" if overall_passed else "核验未完全通过",
            "reasons": reasons,
        },
        "traceability": {"total": len(sources), "passed": trace_passed,
                         "missing_links": missing_links, "missing_excerpts": missing_excerpts},
        "binding": {"total": len(all_marks), "bound": len(all_marks) - len(unbound), "unbound": unbound_ids, "no_citation": no_citation},
        "freshness": freshness,
        "self_check": self_check,
        "policy_count": policy_count,
        "manual_checks": [str(x) for x in (payload.get("verificationChecks") or payload.get("verification_checks") or []) if str(x).strip()],
    }


# ============================================================
# 正文解析与分节
# ============================================================

def render_inline_markdown(text: str, citation_repl) -> str:
    body = esc(text)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"__(.+?)__", r"<strong>\1</strong>", body)
    body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", body)
    body = re.sub(r"(?<!_)_([^_\n]+_)(?!_)", r"<em>\1</em>", body)
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
    return f'<div class="tbl-wrap"><table class="data-tbl"><thead><tr>{head_html}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def render_excerpt_html(text: str) -> str:
    value = str(text or "")
    if "<table" not in value.lower():
        return f'<div class="sc-excerpt plain">{esc(value)}</div>'
    cleaned = re.sub(r"(?is)<script.*?</script>", "", value)
    cleaned = re.sub(r"(?is)<style.*?</style>", "", value)
    cleaned = re.sub(r"\s+on\w+\s*=\s*(['\"]).*?\1", "", cleaned)
    cleaned = re.sub(r"\s+(href|src)\s*=\s*(['\"]).*?\2", "", cleaned)
    allowed = {"table", "thead", "tbody", "tr", "td", "th", "br"}

    def tag_repl(match: re.Match[str]) -> str:
        closing, name = match.group(1), match.group(2).lower()
        if name not in allowed:
            return ""
        return f"<{closing}{name}>"

    cleaned = re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", tag_repl, cleaned)
    return f'<div class="sc-excerpt rich">{cleaned}</div>'


def parse_answer_blocks(answer: str, valid_ids: set) -> Tuple[List[Dict[str, Any]], set]:
    """把正文 Markdown 解析为结构化块；同时收集全部角标。"""
    def repl(match: re.Match[str]) -> str:
        cid = match.group(1)
        cls = "cite" if cid in valid_ids else "cite unresolved"
        label = cid if cid in valid_ids else f"{cid}未绑定"
        return f'<button class="{cls}" data-cite="{esc(cid)}" type="button" title="核验依据 [{esc(label)}]">[{esc(label)}]</button>'

    blocks: List[Dict[str, Any]] = []
    lines = answer.split("\n")
    idx = 0
    while idx < len(lines):
        block = lines[idx].strip()
        if not block:
            idx += 1
            continue
        ids = citation_ids(block)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading_match:
            blocks.append({"kind": "heading", "level": len(heading_match.group(1)),
                           "text": heading_match.group(2).strip(), "cites": ids, "repl": repl})
            idx += 1
        elif "|" in block and idx + 1 < len(lines) and is_markdown_table_separator(lines[idx + 1]):
            table_lines = [block, lines[idx + 1].strip()]
            idx += 2
            while idx < len(lines) and "|" in lines[idx].strip() and lines[idx].strip():
                table_lines.append(lines[idx].strip())
                idx += 1
            blocks.append({"kind": "table", "html": render_markdown_table(table_lines, repl), "cites": citation_ids("\n".join(table_lines))})
        elif block in {"---", "***"}:
            blocks.append({"kind": "hr", "html": '<hr class="doc-divider">', "cites": []})
            idx += 1
        elif re.match(r"^[-*]\s+", block):
            body = render_inline_markdown(re.sub(r"^[-*]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": False, "html": body, "cites": ids})
            idx += 1
        elif re.match(r"^\d+[.)]\s+", block):
            number = re.match(r"^(\d+)[.)]\s+", block).group(1)
            body = render_inline_markdown(re.sub(r"^\d+[.)]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": True, "number": number, "html": body, "cites": ids})
            idx += 1
        else:
            blocks.append({"kind": "para", "html": render_inline_markdown(block, repl), "cites": ids})
            idx += 1
    return blocks, valid_ids


def split_heading_number(text: str) -> Tuple[Optional[str], str]:
    m = re.match(r"^\s*([一二三四五六七八九十]+|\d+)\s*[、.．]\s*(.+)$", text)
    if m:
        return m.group(1), m.group(2)
    return None, text


def group_sections(blocks: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """按标题层级切分章节卡。返回（报告标题, 章节列表）。

    规则：最浅层级标题若唯一且居文首，视为报告标题提出；其下一级为卡片边界。
    无标题的短公文整篇一卡。
    """
    if not blocks:
        return None, [{"title": None, "blocks": []}]
    heading_indexes = [i for i, b in enumerate(blocks) if b["kind"] == "heading"]
    if not heading_indexes:
        return None, [{"title": None, "blocks": blocks}]

    levels = sorted({blocks[i]["level"] for i in heading_indexes})
    shallow = levels[0]
    shallow_indexes = [i for i in heading_indexes if blocks[i]["level"] == shallow]

    doc_title = None
    boundary = shallow
    if len(shallow_indexes) == 1 and heading_indexes[0] == shallow_indexes[0]:
        doc_title = blocks[shallow_indexes[0]]["text"]
        blocks = blocks[shallow_indexes[0] + 1:]
        if len(levels) > 1:
            boundary = levels[1]

    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {"title": None, "blocks": []}
    for b in blocks:
        if b["kind"] == "heading" and b["level"] <= boundary:
            if current["title"] is not None or current["blocks"]:
                sections.append(current)
            current = {"title": b["text"], "blocks": []}
        else:
            current["blocks"].append(b)
    if current["title"] is not None or current["blocks"]:
        sections.append(current)
    return doc_title, sections


# ============================================================
# 各部分渲染
# ============================================================

def render_evidence_chips(ids: List[str], sources: List[Dict[str, str]]) -> str:
    source_map = {source["id"]: source for source in sources}
    chips = []
    for cid in ids:
        source = source_map.get(cid)
        if not source:
            continue
        meta = " | ".join(v for v in [source.get("agency"), source.get("date")] if v)
        excerpt = source.get("excerpt") or "接口返回中未识别到可展示的摘录。"
        links = render_source_links(source.get("url"), source.get("policy_url", ""))
        chips.append(
            f"""
            <details class="ev-chip" data-cite="{esc(cid)}">
              <summary><b>[{esc(cid)}]</b>{esc(short(source.get("title"), 64))}</summary>
              <div class="ev-panel">
                <div class="ev-title">{esc(source.get("title"))}</div>
                <div class="ev-meta">{esc(meta)}</div>
                <p>{esc(excerpt)}</p>
                {links}
              </div>
            </details>
            """
        )
    if not chips:
        return ""
    return f'<div class="ev-row">{"".join(chips)}</div>'


def render_source_links(url: str, policy_url: str = "") -> str:
    links = []
    if url and url != "接口未返回":
        links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">查看原文 ↗</a>')
    if policy_url:
        links.append(f'<a href="{esc(policy_url)}" target="_blank" rel="noopener">知识专库原文 ↗</a>')
    if not links:
        return ""
    return '<div class="sc-links">' + "".join(f"<span>{link}</span>" for link in links) + "</div>"


def render_verify_panel(v: Dict[str, Any]) -> str:
    """核验报告单：报告级核验结论 + 五项指标。"""
    manual_checks_html = "".join("<br>· " + esc(x) for x in v.get("manual_checks", []))
    ov = v["overall"]
    state = "ok" if ov["passed"] else "fail"
    stamp = '<span class="v-stamp">已核验</span>' if ov["passed"] else '<span class="v-stamp bad">核验未通过</span>'
    reasons_html = ""
    if ov["reasons"]:
        reasons_html = '<div class="v-reasons">' + "；".join(esc(r) for r in ov["reasons"]) + "</div>"

    tr = v["traceability"]
    if not tr["total"]:
        tr_html = ('<div class="vi"><span class="s fail">✗ 依据溯源 0/0</span>'
                   '<span class="d">未识别到来源材料</span></div>')
    elif tr["passed"] == tr["total"]:
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">每条素材可回看原文</span></div>')
    else:
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">{tr["total"] - tr["passed"]} 条材料接口未返回原文链接，可经摘录与知识专库回看</span></div>')

    bd = v["binding"]
    if bd.get("no_citation"):
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 0/0</span>'
                   f'<span class="d">正文未包含来源角标，{v["traceability"]["total"]} 条素材无法与正文对应</span></div>')
    elif not bd["total"]:
        bd_html = '<div class="vi"><span class="s none">— 引用对应 0/0</span><span class="d">正文未包含来源角标</span></div>'
    elif not bd["unbound"]:
        bd_html = (f'<div class="vi"><span class="s ok">✓ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">正文引用全部对应素材</span></div>')
    else:
        unbound_text = "、".join(f"[{esc(x)}]" for x in bd["unbound"][:8])
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">未绑定角标 {unbound_text}</span></div>')

    fr = v["freshness"]
    if fr:
        rng = f"{fr['min'][0]}-{fr['min'][1]:02d}～{fr['max'][0]}-{fr['max'][1]:02d}"
        old = f"（{fr['old_count']} 条历史材料，已按参考口径处理）" if fr["old_count"] else ""
        fr_html = f'<div class="vi"><span class="s ok">✓ 材料新旧 完成</span><span class="d">材料日期 {esc(rng)}{esc(old)}</span></div>'
    else:
        fr_html = '<div class="vi"><span class="s none">— 材料新旧 未记录</span><span class="d">素材未标注发布日期</span></div>'

    sc = v["self_check"]
    if sc["status"] == "pass":
        notes = "；".join(note for _, note in sc["items"].values() if note)
        title_attr = f' title="{esc(notes)}"' if notes else ""
        sc_html = (f'<div class="vi"><span class="s ok"{title_attr}>✓ 交付前检查 {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">角标/绑定/核验/一致/清单{esc(" · 悬停查看核验说明" if notes else "")}</span></div>')
    elif sc["status"] == "fail":
        failed_parts = []
        for label, (status, note) in sc["items"].items():
            if status != "pass":
                suffix = f"（{note[:40]}…）" if len(note) > 40 else (f"（{note}）" if note else "")
                failed_parts.append(label + suffix)
        sc_html = (f'<div class="vi"><span class="s fail">✗ 交付前检查 {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">未通过：{esc("、".join(failed_parts))}</span></div>')
    else:
        sc_html = '<div class="vi"><span class="s none">— 交付前检查 未记录</span><span class="d">本次未传入自检结果</span></div>'

    manual = ""
    if v["policy_count"]:
        manual = (f'<div class="vi"><span class="s man">◐ 现行效力</span>'
                  f'<span class="d">{v["policy_count"]} 条材料建议按官方发布复核现行效力</span></div>')

    return f"""
    <div class="verify {state}">
      <div class="v-head"><span class="v-shield">{'✓' if ov['passed'] else '!'}</span>{esc(ov['label'])}{stamp}</div>
      {reasons_html}
      <div class="v-grid">
        {tr_html}{bd_html}{fr_html}{sc_html}{manual}
      </div>
      <div class="v-note">核验方法：深知可信统一问答召回权威来源 → 逐条溯源（摘录比对 + 原文链接 + 知识专库回看）→ 答案引用对应 → 交付前检查。政策现行效力以官方发布为准。{manual_checks_html}</div>
    </div>"""


def render_section_cards(sections: List[Dict[str, Any]], sources: List[Dict[str, str]]) -> str:
    source_ids = {s["id"] for s in sources}
    cards = []
    for sec in sections:
        sec_cites: List[str] = []
        for b in sec["blocks"]:
            for cid in b.get("cites", []):
                if cid not in sec_cites:
                    sec_cites.append(cid)
        unbound_count = sum(1 for cid in sec_cites if cid not in source_ids)
        number, title_text = split_heading_number(sec["title"] or "")
        no_html = f'<span class="sec-no">{esc(number)}</span>' if number else ""
        title_html = f"<h3>{esc(title_text)}</h3>" if title_text else ""
        if sec_cites:
            badge_state = "bad" if unbound_count else ""
            badge_text = f"本章引用 {len(sec_cites)} 处" + (f" · {unbound_count} 处未绑定" if unbound_count else " · 已核验")
            badge_html = f'<span class="sec-badge {badge_state}">{esc(badge_text)}</span>'
        else:
            badge_html = ""
        head_html = f'<div class="sec-head">{no_html}{title_html}{badge_html}</div>' if (no_html or title_html or badge_html) else ""

        body_parts = []
        for b in sec["blocks"]:
            if b["kind"] == "heading":
                inner_level = min(b["level"] + 1, 5)
                body_parts.append(f'<h{inner_level} class="doc-sub">{esc(b["text"])}</h{inner_level}>')
            elif b["kind"] == "list_item":
                marker = f'{esc(b.get("number", "•"))}.' if b.get("numbered") else "•"
                body_parts.append(
                    f'<div class="doc-item"><span class="doc-bullet">{marker}</span>'
                    f'<div><p>{b["html"]}</p>{render_evidence_chips(b["cites"], sources)}</div></div>'
                )
            else:
                body_parts.append(f'<div class="doc-block"><p>{b["html"]}</p>{render_evidence_chips(b["cites"], sources)}</div>')
        cards.append(f'<section class="doc-sec">{head_html}<div class="sec-body">{"".join(body_parts)}</div></section>')
    return "\n".join(cards)


def render_source_card(source: Dict[str, str], used: bool = True) -> str:
    if source.get("verified"):
        note = source.get("verify_note") or "摘录可比对，原文链接与云端存档可回看"
        vk = f'<span class="sc-vk ok" title="{esc(note)}">✓ 已核验</span>'
        note_html = f'<div class="sc-vnote">{esc(short(note, 90))}</div>' if source.get("verify_note") else ""
    else:
        reason = "接口未返回原文链接" if not source.get("has_link") else "摘录待补"
        vk = f'<span class="sc-vk warn" title="接口未提供，非核验失败">◐ {reason}</span>'
        note_html = ""
    links = render_source_links(source.get("url"), source.get("policy_url", ""))
    meta = " | ".join(v for v in [source.get("agency"), source.get("date"), source.get("area")] if v)
    # 标题链：段落标题即该段在原文件中的章节位置（悬停见含文章标题的完整链）；无则如实不显示
    chain_html = ""
    if source.get("doc_section"):
        chain_html = (f'<div class="sc-chain" title="{esc("原文中的位置：" + source["chain_full"])}">'
                      f'标题：{esc(source["doc_section"])}</div>')
    section_html = f'<div class="sc-section">支撑：{esc(source["section"])}</div>' if source.get("section") else ""
    # 高可信徽标：仅"发布日期可信度=高"（模型治理入库、标题模型精抽）；其余不标
    conf_badge = ""
    if source.get("conf") == "高":
        conf_badge = ('<span class="sc-conf" title="发布日期可信度：高。内容经模型治理入库，'
                      '标题为模型从原文动态抽取，非规则提取">高可信</span>')
    # 摘录上方标注：内容为接口返回的原文原段，非 AI 生成
    excerpt_tag = '<div class="sc-extag">▍ 原文原段（非 AI 生成）</div>'
    # 已引用材料显示角标编号；未引用召回材料显示"未引用"灰标（不占正文角标号）
    id_html = f'<span class="sc-id">[{esc(source["id"])}]</span>' if used else '<span class="sc-unused">未引用</span>'
    unused_attr = "" if used else ' data-unused="1"'
    return (
        f'<article class="scard" id="src-{esc(source["id"])}" data-cite-id="{esc(source["id"])}"{unused_attr}>'
        f'<div class="sc-head">{id_html}{conf_badge}{vk}</div>'
        f'<h4>{esc(source.get("title"))}</h4>'
        f'<div class="sc-meta">{esc(meta)}</div>'
        f'{chain_html}{section_html}{note_html}'
        f'{excerpt_tag}'
        f'{render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")}'
        f'<div class="sc-more" role="button" tabindex="0"></div>'
        f'{links}</article>'
    )


def render_sources_panel(sources: List[Dict[str, str]], used: List[str], archive_zone: str = "") -> str:
    if not sources:
        return '<aside class="sources"><h3>核验材料</h3><p class="empty">接口返回中未识别到可展示的材料。</p></aside>'
    used_set = set(used)
    cited_sources = sorted((s for s in sources if s["id"] in used_set), key=lambda s: int(s["id"]))
    cited_cards = [render_source_card(s, used=True) for s in cited_sources]
    uncited = sorted((s for s in sources if s["id"] not in used_set), key=lambda s: int(s["id"]))
    uncited_html = ""
    if uncited:
        uncited_cards = "".join(render_source_card(s, used=False) for s in uncited)
        # 不用 <details> 折叠：部分宿主（WorkBuddy 等）的 HTML 预览服务会改写折叠区导致卡片丢失
        uncited_html = (
            '<div class="uncited-group"><div class="ug-title">未引用素材（'
            f'{len(uncited)} 条 · 接口召回但答案未采用，供比对参考，不计入核验结论）</div>'
            f'<div class="uncited-list">{uncited_cards}</div></div>'
        )
    # "已核验"只统计正文引用材料：未引用召回未进入正文核验流程
    verified_count = sum(1 for s in cited_sources if s.get("verified"))
    badge = "全部已核验" if verified_count == len(cited_sources) else f"{verified_count}/{len(cited_sources)} 已核验"
    return (
        '<aside class="sources" id="sources-panel" aria-label="核验材料面板">'
        '<a class="back-doc" href="#doc-top">↑ 返回核验报告单</a>'
        f'<h3>核验材料（{len(cited_sources)} 条已引用 · {esc(badge)}）</h3>'
        '<div class="src-tip">点击正文角标 [1] 定位材料原文并核对</div>'
        '<input class="src-search" type="search" placeholder="搜索标题 / 来源 / 摘录…" aria-label="搜索来源">'
        f'<div class="src-list">{"".join(cited_cards)}{uncited_html}</div>'
        f'{archive_zone}'
        '</aside>'
    )


def render_archive_zone(archive_urls: List[str], source_count: int) -> str:
    """云端溯源存档区：统一问答场景自行设计，不复用搜索版"原始召回存档"文案。

    统一问答接口返回的 traceUrl 是云平台为本次问答生成的接口侧可信溯源
    报告，定位为云端存档：本地报告便于离线查阅与打印归档，云端存档适合
    向他人出示查验，也可在本地文件遗失时兜底；逐条核验以来源卡原文链接为准。
    """
    if not archive_urls:
        return ""
    chips = []
    for index, url in enumerate(archive_urls):
        count_text = f"对应 {source_count} 条来源" if not index else "云端留存"
        chips.append(
            f'<a class="kb-chip" href="{esc(url)}" target="_blank" rel="noopener">'
            f'<span class="kb-label">本次问答 · 接口侧可信溯源报告</span>'
            f'<span class="kb-count">{esc(count_text)} · 云端存档</span>'
            '<span class="kb-arrow">打开 ↗</span></a>'
        )
    return (
        '<div class="kb-zone"><div class="kb-title">云端溯源存档（接口可信溯源报告）</div>'
        '<div class="kb-desc">以下链接为深知云平台对本次问答留存的接口侧可信溯源报告，与本核验报告内容对应：'
        '本地报告便于离线查阅与打印归档；云端存档适合向他人出示查验，也可在本地文件遗失时兜底。'
        '逐条材料的核验仍以来源卡上的"查看原文"直达官方页面为准。</div>'
        f'<div class="kb-list">{"".join(chips)}</div></div>'
    )


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_consulting", suffix_ext: str = ".html") -> str:
    raw = question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    suffix = timestamp.strftime("%Y%m%d_%H%M")
    stem = normalized[:24].strip("._-") or fallback
    return f"{stem}_可信核验报告_{suffix}{suffix_ext}"


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "",
                generated_at: Optional[datetime] = None, sources_override: Optional[List[Dict[str, str]]] = None) -> str:
    payload = unwrap(payload)
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    sources = sources_override if sources_override is not None else extract_sources(payload)
    answer, sources, _ = renumber_citations(answer, sources)
    sources = align_sources_to_answer(answer, sources)
    used = citation_ids(answer)
    kb_urls = extract_trace_archives(payload)
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")

    verification = compute_verification(answer, sources, payload, generated_at)
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warn-box"><b>生成检查未通过：答案没有来源角标。</b>'
            '本报告无法建立"结论-素材"核验对应，仅作素材清单参考。'
            '请修正最终答案文件：在关键结论后标注 [1]、[2] 等角标并逐条对应来源材料，'
            '然后重新运行 render_trace_html.py 生成核验报告。</div>'
        )
    blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources})
    doc_title, sections = group_sections(blocks)
    display_title = doc_title or title
    kb_zone = render_archive_zone(kb_urls, len(sources))

    meta_bits = []
    if sources:
        meta_bits.append(f"共 {len(sources)} 条")
    meta_bits.append("点击答案角标 [1] 定位材料原文")
    meta_line = " ｜ ".join(meta_bits)
    question = question_override.strip() or extract_question(payload)
    question_html = (
        f'<div class="q-line"><b>咨询问题：</b>{esc(question)}</div>' if question else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display_title)} · 可信核验报告</title>
<style>
:root{{
  --navy:#0b1f3a; --ink:#172236; --muted:#667085; --line:#dce4ef; --line-strong:#b9c6d9;
  --brand:#1559c7; --brand-soft:#e8f0ff;
  --policy:#0c9b78; --policy-soft:#e2f6ef;
  --case:#b26a00; --case-soft:#fff4e0;
  --ref:#4b5563; --ref-soft:#eef1f6;
  --warn:#b26a00; --danger:#b93939; --ok:#0c9b78;
}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  color:var(--ink);background:#f4f7fb;line-height:1.75;font-size:14.5px}}
a{{color:var(--brand)}}
.topbar{{position:sticky;top:0;z-index:10;display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:10px 22px;background:var(--navy);color:#fff;font-size:13px}}
.topbar .tb-title{{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.topbar .tags{{display:flex;align-items:center;gap:6px;flex:none}}
.topbar .tags span{{padding:2px 10px;border:1px solid rgba(255,255,255,.3);border-radius:999px;font-size:11.5px}}
.layout{{display:grid;grid-template-columns:minmax(0,760px) minmax(340px,420px);gap:26px;
  max-width:1240px;margin:0 auto;padding:26px 18px 60px}}
/* 左栏 */
.report{{min-width:0}}
.r-head{{padding:22px 26px;background:#fff;border:1px solid var(--line);border-radius:12px;margin-bottom:16px;text-align:center}}
.r-head h1{{margin:0 0 8px;font-size:22px;color:var(--navy);line-height:1.5}}
.q-line{{margin:0 auto 10px;max-width:92%;font-size:13.5px;color:#3b4a61;background:#f5f8fc;
  border:1px solid var(--line);border-radius:8px;padding:8px 12px;text-align:left;line-height:1.7}}
.r-head .sub{{color:var(--muted);font-size:12.5px}}
.warn-box{{margin:0 0 16px;padding:13px 16px;border:1.5px solid var(--danger);border-radius:10px;
  background:#fdf3f3;color:#8f2626;font-size:13.5px;line-height:1.7}}
.verify{{margin:0 0 16px;background:#fff;border:1px solid #bfe5d6;border-radius:12px;padding:16px 20px}}
.verify.fail{{border-color:#f2c4c4;background:#fffafa}}
.v-head{{display:flex;align-items:center;gap:9px;font-size:15px;font-weight:800;color:var(--ok)}}
.verify.fail .v-head{{color:var(--danger)}}
.v-shield{{display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--ok);color:#fff;
  align-items:center;justify-content:center;font-size:12px;flex:none}}
.verify.fail .v-shield{{background:var(--danger)}}
.v-stamp{{margin-left:auto;font-size:11px;border:1.5px solid var(--ok);color:var(--ok);border-radius:5px;
  padding:1px 8px;letter-spacing:2px;flex:none}}
.v-stamp.bad{{border-color:var(--danger);color:var(--danger)}}
.v-reasons{{margin-top:6px;font-size:12.5px;color:var(--danger)}}
.v-grid{{display:grid;grid-template-columns:1fr 1fr;gap:4px 20px;margin-top:10px}}
.vi{{display:flex;gap:7px;align-items:baseline;font-size:12.5px;color:#35445c;line-height:1.7;min-width:0}}
.vi .s{{font-weight:800;flex:none}}
.vi .s.ok{{color:var(--ok)}}
.vi .s.warn{{color:var(--warn)}}
.vi .s.fail{{color:var(--danger)}}
.vi .s.man{{color:var(--case)}}
.vi .s.none{{color:var(--muted)}}
.vi .d{{color:var(--muted);min-width:0}}
.v-note{{margin-top:11px;padding-top:9px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--muted);line-height:1.7}}
/* 正文章节卡 */
.doc-sec{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin-bottom:16px}}
.sec-head{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:10px;
  padding-bottom:10px;border-bottom:1px solid var(--line)}}
.sec-no{{display:inline-flex;width:26px;height:26px;border-radius:7px;background:var(--brand);color:#fff;
  align-items:center;justify-content:center;font-size:13.5px;font-weight:700;flex:none}}
.sec-head h3{{margin:0;font-size:16.5px;color:var(--navy);line-height:1.5}}
.sec-badge{{margin-left:auto;font-size:11.5px;color:var(--ok);background:var(--policy-soft);
  border-radius:6px;padding:2px 9px;font-weight:700;flex:none}}
.sec-badge.bad{{color:var(--danger);background:#fdecea}}
.doc-sub{{margin:16px 0 8px;color:var(--navy);font-size:14.5px;font-weight:700}}
h5.doc-sub{{font-size:13.5px}}
.doc-block,.doc-item{{margin:0 0 12px}}
.doc-block p,.doc-item p{{margin:0;font-size:14px;line-height:1.9}}
.doc-item{{display:grid;grid-template-columns:22px minmax(0,1fr);gap:8px}}
.doc-item.numbered{{grid-template-columns:28px minmax(0,1fr)}}
.doc-bullet{{padding-top:1px;color:#111827;font-size:15px;line-height:1.85}}
.doc-divider{{border:0;border-top:1px solid var(--line);margin:18px 0}}
code{{padding:1px 5px;border-radius:4px;background:#f3f4f6;color:#374151;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}}
.tbl-wrap{{max-width:100%;overflow-x:auto;margin:8px 0}}
.data-tbl{{width:100%;border-collapse:collapse;border:1px solid var(--line);font-size:13px}}
.data-tbl th,.data-tbl td{{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;line-height:1.65}}
.data-tbl th{{background:#f2f5fb;font-weight:700;color:#374151}}
/* 角标 */
.cite{{margin:0 1px;padding:0 5px;border:0;border-radius:4px;background:var(--brand-soft);color:var(--brand);
  font-weight:800;font-size:10.5px;cursor:pointer;vertical-align:super;font-family:monospace}}
.cite:hover,.cite:focus-visible{{background:var(--brand);color:#fff;outline:none}}
.cite.unresolved{{background:#fdecea;color:var(--danger)}}
/* 段落级证据 chips */
.ev-row{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 2px}}
.ev-chip{{max-width:100%}}
.ev-chip summary{{display:inline-flex;align-items:center;max-width:100%;border-radius:999px;padding:3px 10px;
  color:#4b5563;background:#f3f4f6;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  list-style:none;font-size:11.5px}}
.ev-chip summary::-webkit-details-marker{{display:none}}
.ev-chip summary::after{{content:"核验";margin-left:7px;color:#9ca3af;font-size:10.5px}}
.ev-chip[open] summary::after{{content:"收起"}}
.ev-chip summary b{{color:var(--brand);margin-right:5px}}
.ev-panel{{margin:7px 0 6px;padding:12px 14px;border:1px solid var(--line);border-radius:9px;background:#fbfcfe;
  box-shadow:0 8px 24px rgba(15,23,42,.06)}}
.ev-title{{font-weight:700;font-size:13.5px;margin-bottom:4px;color:var(--navy)}}
.ev-meta{{color:var(--muted);font-size:12px;margin-bottom:6px}}
.ev-panel p{{margin:0 0 8px;color:#374151;font-size:12.8px;line-height:1.7}}
.sc-links{{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}}
.sc-links span{{display:inline-flex}}
.sc-links a{{display:inline-flex;align-items:center;min-height:24px;padding:3px 9px;border-radius:6px;
  background:var(--brand-soft);color:var(--brand);font-weight:700;text-decoration:none;font-size:12px}}
/* 右栏 核验材料 */
.sources{{position:sticky;top:56px;align-self:start;max-height:calc(100vh - 76px);overflow:auto;
  background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px}}
.sources h3{{margin:0 0 3px;font-size:15px;color:var(--navy)}}
.src-tip{{font-size:11.5px;color:var(--muted);margin-bottom:10px}}
.src-search{{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:7px;font-size:12.5px;margin-bottom:12px}}
.scard{{border:1px solid var(--line);border-radius:10px;padding:11px 13px;margin-bottom:10px;
  background:#fff;transition:box-shadow .25s}}
.scard.hl{{box-shadow:0 0 0 3px var(--brand)}}
.scard.hide{{display:none}}
.sc-head{{display:flex;align-items:center;gap:7px;margin-bottom:4px}}
.sc-id{{font-family:monospace;font-weight:800;font-size:11px;color:var(--brand);background:var(--brand-soft);
  border-radius:4px;padding:1px 7px}}
.sc-vk{{margin-left:auto;font-size:11px;font-weight:800;color:var(--ok)}}
.sc-vk.warn{{color:var(--warn)}}
.scard h4{{margin:0 0 4px;font-size:13px;color:var(--navy);line-height:1.55}}
.sc-meta{{font-size:11.5px;color:var(--muted)}}
.sc-section{{font-size:11.5px;color:var(--brand);margin-top:3px;font-weight:600}}
.sc-vnote{{margin-top:5px;font-size:11.3px;color:var(--ok);line-height:1.6}}
.sc-unused{{font-size:10.5px;font-weight:800;color:var(--muted);background:#eef1f6;border-radius:4px;
  padding:1px 7px;flex:none}}
.scard[data-unused]{{opacity:.86}}
.sc-conf{{font-size:10.5px;font-weight:800;color:#8a5a00;background:var(--case-soft);border:1px solid #e8c98a;
  border-radius:4px;padding:0 7px;flex:none}}
.sc-extag{{margin-top:8px;padding-top:7px;border-top:1px dashed var(--line-strong);font-size:11px;color:#0b6e4f;font-weight:700}}
.sc-chain{{font-size:11.5px;color:var(--brand);margin-top:3px;font-weight:600;line-height:1.6;cursor:help}}
.sc-more{{display:none;margin:-3px 2px 4px;text-align:right;font-size:11px;color:var(--brand);font-weight:700;cursor:pointer;user-select:none}}
.scard.clampable .sc-more{{display:block}}
.scard.clampable .sc-more::before{{content:"展开全文 ▾"}}
.scard.clampable.open .sc-more::before{{content:"收起 ▴"}}
.cmp{{margin:0 0 10px;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.cmp-tag{{font-size:11px;font-weight:800;padding:3px 10px}}
.cmp-side{{padding:9px 12px;font-size:12.8px;line-height:1.7}}
.cmp-side p{{margin:0}}
.cmp-ai{{background:#fbfcfe;color:#374151}}
.cmp-ai .cmp-tag{{background:#eef1f6;color:var(--ref)}}
.cmp-src{{background:#f4faf7;color:#2f4a3e;border-top:1px dashed var(--line-strong)}}
.cmp-src .cmp-tag{{background:var(--policy-soft);color:#0b6e4f}}
.cmp-src .sc-excerpt{{display:block;-webkit-line-clamp:unset;background:#fff;cursor:auto;font-size:12px;padding:8px 10px;margin:0}}
.sc-excerpt{{margin:7px 0;padding:9px 10px;border-radius:7px;background:#f8fafc;color:#42566f;font-size:12px;line-height:1.7;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;cursor:pointer}}
.scard.open .sc-excerpt{{display:block;-webkit-line-clamp:unset}}
.sc-excerpt.rich{{overflow-x:auto}}
.sc-excerpt.rich table{{width:max-content;min-width:100%;border-collapse:collapse;background:#fff;font-size:12px}}
.sc-excerpt.rich td,.sc-excerpt.rich th{{min-width:92px;max-width:220px;padding:7px 8px;border:1px solid var(--line);
  vertical-align:top;word-break:break-word}}
.sc-excerpt.rich thead td,.sc-excerpt.rich th{{background:#f3f4f6;color:#374151;font-weight:700}}
.scard .sc-links a{{font-size:12px}}
.scard .sc-links{{margin-top:4px}}
.no-link{{font-size:11.5px;color:var(--muted)}}
.uncited-group{{margin-top:12px;border-top:1px dashed var(--line-strong);padding-top:10px}}
.ug-title{{font-size:12.5px;color:var(--muted);font-weight:700;line-height:1.6}}
.uncited-group .uncited-list{{margin-top:10px}}
/* 知识专库 */
.kb-zone{{margin-top:14px;border-top:1px dashed var(--line-strong);padding-top:12px}}
.kb-title{{font-size:12.5px;font-weight:800;color:var(--navy)}}
.kb-desc{{font-size:11.3px;color:var(--muted);line-height:1.65;margin:3px 0 8px}}
.kb-list{{display:flex;flex-direction:column;gap:7px}}
.kb-chip{{display:flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;
  background:#fbfcfe;text-decoration:none;font-size:11.5px}}
.kb-chip:hover{{border-color:var(--brand);background:var(--brand-soft)}}
.kb-label{{font-weight:700;color:#374151;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.kb-count{{padding-left:8px;border-left:1px solid var(--line);color:var(--muted);white-space:nowrap}}
.kb-arrow{{margin-left:auto;color:var(--brand);font-weight:700;white-space:nowrap}}
.empty{{color:var(--muted)}}
.foot{{text-align:center;color:var(--muted);font-size:11.5px;padding:16px 0 4px;line-height:1.8}}
@media (max-width:1020px){{
  .layout{{grid-template-columns:1fr}}
  .sources{{position:static;max-height:none}}
}}
/* —— 移动端专项适配（手机阅读核验报告） —— */
.mobile-nav{{display:none}}
.back-doc{{display:none}}
/* 移动端材料底部弹层：点角标就地弹出材料卡，不跳转打断阅读 */
.sheet-mask{{display:none}}
.sheet{{display:none}}
@media (max-width:680px){{
  body{{font-size:14px;line-height:1.8}}
  .layout{{grid-template-columns:1fr;padding:12px 10px 40px;gap:14px}}
  .topbar{{padding:8px 12px;font-size:12px;gap:4px;flex-wrap:wrap}}
  .topbar .tags span{{font-size:10.5px;padding:1px 8px;margin-left:4px}}
  .r-head{{padding:16px 14px;border-radius:10px}}
  .r-head h1{{font-size:18px}}
  .r-head .sub{{font-size:11.5px;line-height:1.6}}
  .verify{{padding:13px 14px;border-radius:10px}}
  .v-head{{font-size:14px}}
  .v-grid{{grid-template-columns:1fr;gap:2px 0}}
  .vi{{flex-wrap:wrap;gap:4px 8px}}
  .vi .d{{min-width:0}}
  .warn-box{{font-size:12.5px;padding:11px 12px}}
  .doc-sec{{padding:14px;border-radius:10px}}
  .sec-no{{width:22px;height:22px;font-size:12px;border-radius:6px}}
  .sec-head{{gap:7px;padding-bottom:8px;margin-bottom:8px}}
  .sec-head h3{{font-size:15px}}
  .sec-badge{{margin-left:0;font-size:11px}}
  .doc-block p,.doc-item p{{font-size:13.5px;line-height:1.95}}
  .doc-sub{{font-size:14px;margin:12px 0 6px}}
  .data-tbl{{font-size:12px}}
  .data-tbl th,.data-tbl td{{padding:6px 7px;line-height:1.55}}
  .cite{{font-size:11px;padding:0 4px}}
  .ev-chip summary{{font-size:11px}}
  .sources{{padding:12px;border-radius:10px}}
  .scard{{padding:10px 11px}}
  .sc-excerpt{{font-size:11.5px}}
  .sc-extag{{font-size:10.5px}}
  .sc-chain{{font-size:11px}}
  .cmp-tag{{font-size:11px;font-weight:800;padding:3px 10px}}
  .cmp-side{{padding:9px 12px;font-size:12.8px;line-height:1.7}}
  .kb-chip{{flex-wrap:wrap}}
  .kb-label{{white-space:normal}}
  .mobile-nav{{display:block;margin:0 0 14px;padding:11px 14px;border:1.5px solid var(--brand);
    border-radius:10px;background:var(--brand-soft);color:var(--brand);font-weight:800;
    font-size:13.5px;text-decoration:none;text-align:center}}
  .back-doc{{display:inline-block;margin:0 0 8px;font-size:12px;color:var(--brand);
    font-weight:700;text-decoration:none}}
  .sheet-mask{{display:block;position:fixed;inset:0;background:rgba(11,31,58,.45);z-index:99;opacity:0;
    pointer-events:none;transition:opacity .2s}}
  .sheet-mask.show{{opacity:1;pointer-events:auto}}
  .sheet{{display:block;position:fixed;left:0;right:0;bottom:0;z-index:100;background:#fff;
    border-radius:14px 14px 0 0;box-shadow:0 -8px 30px rgba(11,31,58,.25);
    max-height:68vh;overflow-y:auto;-webkit-overflow-scrolling:touch;
    padding:10px 16px 22px;transform:translateY(105%);transition:transform .25s ease}}
  .sheet.show{{transform:translateY(0)}}
  .sheet-grab{{width:38px;height:4px;border-radius:2px;background:#c9d4e2;margin:2px auto 8px}}
  .sheet-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}}
  .sheet-head b{{font-size:13.5px;color:var(--navy)}}
  .sheet-close{{border:1px solid var(--line);background:#f5f8fc;border-radius:8px;color:#3b4a61;
    font-size:12.5px;font-weight:700;padding:5px 14px;cursor:pointer}}
  .sheet .scard{{box-shadow:none;margin-bottom:0}}
  .sheet .sc-excerpt{{display:block;-webkit-line-clamp:unset;cursor:auto}}
}}
@media print{{
  .topbar,.src-search{{display:none!important}}
  .layout{{grid-template-columns:1fr;max-width:none;padding:0;gap:14px}}
  body{{background:#fff;font-size:12.5px}}
  .sources{{position:static;max-height:none;border:0;padding:0;overflow:visible}}
  .r-head,.verify,.doc-sec{{border-color:#bbb;box-shadow:none;break-inside:avoid}}
  .sc-excerpt{{display:block;-webkit-line-clamp:unset;cursor:auto}}
  .uncited-group[open] .uncited-list,.uncited-group{{break-inside:avoid}}
  .scard{{break-inside:avoid}}
  .cite{{background:#eee;color:#333}}
}}
</style>
</head>
<body>

<header class="topbar">
  <div class="tb-title">{esc(display_title)} · 可信核验报告</div>
  <div class="tags">
    <span>生成于 {esc(generated)}</span>
    <span>材料来源：深知可信统一问答</span>
  </div>
</header>

<div class="layout">
  <main class="report" aria-label="核验报告正文">
    <div class="r-head" id="doc-top">
      <h1>{esc(display_title)}</h1>
      {question_html}
      <div class="sub">{esc(meta_line)}</div>
    </div>
    {citation_warning}
    {render_verify_panel(verification)}
    <a class="mobile-nav" href="#sources-panel">查看核验材料（{len(sources)} 条 · 点击角标可定位原文）↓</a>
    {render_section_cards(sections, sources)}
    <div class="foot">深知可信咨询 · 可信核验报告 ｜ 核验方法：统一问答召回 → 逐条溯源 → 引用对应 → 交付前检查 ｜ 内容由 AI 生成，仅供参考，政策现行效力以官方发布为准</div>
  </main>
  {render_sources_panel(sources, used, kb_zone)}
</div>

<div class="sheet-mask" aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-label="依据对照">
  <div class="sheet-grab"></div>
  <div class="sheet-head"><b>依据对照</b><button class="sheet-close" type="button">收起</button></div>
  <div class="sheet-body"></div>
</div>

<script>
(function () {{
  "use strict";
  var cards = Array.prototype.slice.call(document.querySelectorAll(".scard"));
  var byId = {{}};
  cards.forEach(function (c) {{
    var id = c.getAttribute("data-cite-id");
    if (id) byId[id] = c;
  }});

  /* 移动端底部弹层：点角标就地展示材料卡，不打断正文阅读 */
  var sheet = document.querySelector(".sheet");
  var mask = document.querySelector(".sheet-mask");
  function isMobile() {{
    return window.matchMedia("(max-width:680px)").matches;
  }}
  function escHtml(s) {{
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }}
  function sentenceOf(el) {{
    var para = el && el.closest ? el.closest(".doc-block,.doc-item") : null;
    return para && para.querySelector("p") ? para.querySelector("p").innerText.trim() : "";
  }}
  function openSheet(card, sentence) {{
    if (!sheet) return;
    var body = sheet.querySelector(".sheet-body");
    body.innerHTML = "";
    if (sentence) {{
      var excerpt = card.querySelector(".sc-excerpt");
      var cmp = document.createElement("div");
      cmp.className = "cmp";
      cmp.innerHTML =
        '<div class="cmp-side cmp-ai"><div class="cmp-tag">正文表述（AI 生成）</div><p>' + escHtml(sentence) + '</p></div>' +
        '<div class="cmp-side cmp-src"><div class="cmp-tag">原文原段（非 AI 生成）</div>' +
        '<div class="sc-excerpt">' + (excerpt ? excerpt.innerHTML : "") + '</div></div>';
      body.appendChild(cmp);
    }}
    var clone = card.cloneNode(true);
    clone.removeAttribute("id");
    clone.classList.remove("hide");
    clone.classList.add("open");
    var sheetMore = clone.querySelector(".sc-more");
    if (sheetMore) sheetMore.remove();
    body.appendChild(clone);
    sheet.classList.add("show");
    mask.classList.add("show");
    document.body.style.overflow = "hidden";
    sheet.scrollTop = 0;
  }}
  function closeSheet() {{
    if (!sheet) return;
    sheet.classList.remove("show");
    mask.classList.remove("show");
    document.body.style.overflow = "";
  }}
  if (sheet && mask) {{
    mask.addEventListener("click", closeSheet);
    var closeBtn = sheet.querySelector(".sheet-close");
    if (closeBtn) closeBtn.addEventListener("click", closeSheet);
  }}

  /* 角标 → 来源卡：精确 ID 匹配，缺失即红色警示，绝不按位置猜测。
     手机单栏下不滚动定位（会跳到页面底部打断阅读），改为底部弹层就地查看。 */
  document.querySelectorAll(".data-cite,[data-cite]").forEach(function (btn) {{
    if (btn.classList.contains("sheet-close")) return;
    btn.addEventListener("click", function () {{
      var card = byId[btn.getAttribute("data-cite")];
      if (!card) {{
        btn.classList.add("unresolved");
        if (console.error) console.error("[核验] 未绑定角标:", btn.getAttribute("data-cite"));
        return;
      }}
      if (isMobile()) {{
        openSheet(card, sentenceOf(btn));
        return;
      }}
      card.classList.remove("hide", "open");
      card.classList.add("hl", "open");
      card.scrollIntoView({{ block: "center", behavior: "smooth" }});
      setTimeout(function () {{ card.classList.remove("hl"); }}, 2200);
    }});
  }});

  /* 摘录点击展开/收起：内容被截断（超出 4 行）的卡片显示"展开全文"引导，
     未截断的短摘录不显示，避免误导 */
  cards.forEach(function (c) {{
    var ex = c.querySelector(".sc-excerpt");
    if (!ex) return;
    if (ex.scrollHeight > ex.clientHeight + 4) c.classList.add("clampable");
    var more = c.querySelector(".sc-more");
    function toggleExcerpt() {{ c.classList.toggle("open"); }}
    ex.addEventListener("click", function (e) {{
      if (e.target.closest("a")) return;
      toggleExcerpt();
    }});
    if (more) {{
      more.addEventListener("click", toggleExcerpt);
      more.addEventListener("keydown", function (e) {{
        if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); toggleExcerpt(); }}
      }});
    }}
  }});

  /* 证据 chips（灰框）：桌面端点击就地展开并高亮右栏来源卡；手机端不就地展开，点击直接弹出底部材料弹层 */
  document.querySelectorAll(".ev-chip").forEach(function (chip) {{
    var summary = chip.querySelector("summary");
    if (summary) {{
      summary.addEventListener("click", function (e) {{
        if (!isMobile()) return;
        e.preventDefault();
        var card = byId[chip.getAttribute("data-cite")];
        if (card) openSheet(card, sentenceOf(chip));
      }});
    }}
    chip.addEventListener("toggle", function () {{
      if (!chip.open || isMobile()) return;
      var card = byId[chip.getAttribute("data-cite")];
      if (!card) return;
      cards.forEach(function (c) {{ c.classList.remove("hl"); }});
      card.classList.add("hl");
      setTimeout(function () {{ card.classList.remove("hl"); }}, 2200);
    }});
  }});

  /* 搜索 */
  var kw = "";
  function apply() {{
    cards.forEach(function (c) {{
      var okKw = !kw || (c.textContent || "").toLowerCase().indexOf(kw) !== -1;
      c.classList.toggle("hide", !okKw);
    }});
  }}
  var search = document.querySelector(".src-search");
  if (search) search.addEventListener("input", function () {{ kw = search.value.trim().toLowerCase(); apply(); }});
}})();
</script>
</body>
</html>"""


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


def main() -> None:
    parser = argparse.ArgumentParser(description="生成深知可信咨询可信核验报告 HTML")
    parser.add_argument("input_json", help="gov_chat.py 的 --json-only 输出 JSON（位于 official-docs/search-results/）")
    parser.add_argument("--output", help="输出 HTML 路径；不传时根据问题自动生成短文件名到 official-docs/output/")
    parser.add_argument("--title", default="深知可信咨询核验报告", help="页面标题")
    parser.add_argument("--answer-file", help="最终回答正文文件。整理综合后必须传入，确保 HTML 展示的答案与聊天答案一致。")
    parser.add_argument("--self-check-file", help="交付前检查结果 JSON（五项：角标存在/角标对应来源/结论可核验/答案一致/来源清单覆盖），值支持 通过/pass/✓ 等写法。")
    parser.add_argument("--clean-md-output", help="输出干净 Markdown 路径；内容来自同一份最终答案，并移除 [1]、【1】等溯源角标。")
    parser.add_argument("--question", default="", help="用户问题，用于生成咨询问题行与文件名。")
    args = parser.parse_args()

    payload = load_json(_resolve_input(args.input_json))
    if args.self_check_file:
        self_check_data = load_json(_resolve_input(args.self_check_file))
        holder = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        holder.setdefault("selfCheck", self_check_data)
    answer_override = ""
    if args.answer_file:
        answer_override = _resolve_input(args.answer_file).read_text(encoding="utf-8")
    base_answer = strip_trailing_source_list(answer_override or extract_answer(unwrap(payload)))
    base_answer = normalize_citations(base_answer)

    # 生成前硬校验：核验报告是交付物，交付时必须为核验通过状态。
    # Agent 可修正的问题在这里一律拒绝生成，倒逼先修正再交付；
    # 仅接口未返回原文链接、政策效力无法自动判定等不可抗因素由报告温和提示。
    pre_sources = extract_sources(unwrap(payload))
    pre_source_ids = {s["id"] for s in pre_sources}
    pre_cited = citation_ids(base_answer)
    if pre_sources and not pre_cited:
        print(
            "错误：接口返回了来源材料，但最终答案中没有 [n] 角标，无法建立核验对应，已拒绝生成。\n"
            "请先修正最终答案（或答案文件）：在关键结论后标注 [1]、[2] 等角标并逐条对应来源材料，再重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    unbound = [cid for cid in pre_cited if cid not in pre_source_ids]
    if unbound:
        print(
            f"错误：最终答案中的角标 {'、'.join('[' + c + ']' for c in unbound)} 未对应任何来源材料，已拒绝生成。\n"
            "请先修正最终答案：删除该角标，或改挂到真实支撑该结论的材料编号上，再重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    self_check_items = normalize_self_check(payload.get("data", payload).get("selfCheck") if isinstance(payload.get("data"), dict) else payload.get("selfCheck"))
    if not self_check_items:
        print(
            "错误：缺少交付前检查结果（--self-check-file），已拒绝生成。\n"
            "请先完成交付前检查并把五项结果写入自检 JSON，再重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    failed_checks = [label for label, (status, _) in self_check_items.items() if status != "pass"]
    if failed_checks:
        print(
            f"错误：交付前检查存在未通过项（{'、'.join(failed_checks)}），已拒绝生成。\n"
            "请先修正答案或自检结果至全部通过，再重新运行本脚本；不得带未通过项交付核验报告。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = args.question.strip() or extract_question(unwrap(payload))
    generated_at = datetime.now()

    # 角标重编号（与报告一致的单一样本源）：被引用角标按首次出现顺序映射为 1..n。
    # 重编号结果同步输出给 Agent：答案文件 + 现成的对话来源清单 + 映射表，
    # 保证"对话回复、核验报告、干净 Markdown"三处编号一致。
    prepared_sources = [dict(s) for s in pre_sources]
    final_answer, prepared_sources, mapping = renumber_citations(base_answer, prepared_sources)
    final_answer_path = SEARCH_RESULTS_DIR / "dknowc_consulting_answer_final.txt"
    final_answer_path.parent.mkdir(parents=True, exist_ok=True)
    final_answer_path.write_text(final_answer, encoding="utf-8")

    source_map = {}
    for source in prepared_sources:
        source_map.setdefault(source["id"], source)
    source_list_lines = []
    for cid in citation_ids(final_answer):
        source = source_map.get(cid)
        if not source:
            continue
        bits = [f"[{cid}]《{source.get('title') or '未命名材料'}》"]
        meta = " · ".join(v for v in [source.get("agency"), source.get("date")] if v)
        if meta:
            source_list_lines.append(f"{bits[0]} · {meta}")
        else:
            source_list_lines.append(bits[0])
    mapping_pairs = [f"[{old}]→[{new}]" for old, new in mapping.items() if old != new]

    if args.output:
        output = _resolve_output(args.output)
    else:
        output = _resolve_output(safe_output_filename(question, generated_at))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payload, args.title, answer_override=final_answer, question_override=args.question, generated_at=generated_at, sources_override=prepared_sources), encoding="utf-8")
    print(f"已生成：{output}")
    if args.clean_md_output:
        clean_output = _resolve_output_md(args.clean_md_output)
    else:
        clean_output = _resolve_output_md(output.with_suffix(".clean.md").name)
    clean_output.parent.mkdir(parents=True, exist_ok=True)
    clean_answer = strip_citation_markers(final_answer)
    clean_output.write_text(clean_answer, encoding="utf-8")
    print(f"已生成干净 Markdown：{clean_output}")

    print(f"已生成重编号答案（对话回复请使用此文件内容）：{final_answer_path}")
    if mapping_pairs:
        print("角标重编号映射：" + "；".join(mapping_pairs))
    print("对话来源清单（已重编号，只含被引用材料，直接用于回复末尾）：")
    for line in source_list_lines:
        print(line)


if __name__ == "__main__":
    main()
