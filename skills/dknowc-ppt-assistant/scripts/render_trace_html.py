#!/usr/bin/env python3
"""深知可信PPT 可信溯源核验报告渲染器：把检索素材 JSON + 答案文件渲染为单文件可核验 HTML。

双版支持（--stage）：
- outline 提纲版：结构方案确认门前的提纲答案文件（页面规划表 + 口径事项清单）→ 事前核验
- final   成稿版：交付时的页面级结论文本 → 事后溯源

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。
三个核验层次：
- 报告级：核验报告单（依据溯源 / 引用绑定 / 时效检查 / 类型覆盖 / 自检）
- 材料级：每条来源卡核验链标记（摘录可比对 + 原文可打开 + 知识专库可回溯）
- 引用级：答案正文角标与来源卡一一绑定，未绑定角标红色警示

诚实原则：脚本真实计算的结果才打勾；政策现行效力等无法自动判定项归入
"建议人工复核"；self_check 未传入时显示"未记录"，不假装通过。

输入：trusted_search.py / 合并后的检索 JSON（检索文章，材料级「角标」编号优先，
全库无材料级编号时按数组位置 1..N 兜底）+ --answer-file 答案文件（提纲版
<项目短名>_outline.md / 成稿版 <项目短名>_answer.txt，关键事实后标 [N] 角标）。

布局：深色顶栏 + 左栏报告正文（分节卡片）+ 右栏核验材料面板（类型筛选/搜索）；
打印归档模式（@media print 单栏全展开）；移动端适配（680px 断点：密度压缩、
「查看核验材料」跳转与「返回核验报告单」锚点、角标/证据 chips 点击改底部弹层
就地查看，不打断正文阅读，PC 双栏保留右栏定位高亮）。
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

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 产物根：dsh 会话隔离 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/；DKNWOC_WS_ROOT 显式优先；无会话回退 _default
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"

STAGE_LABELS = {"outline": "提纲版", "final": "成稿版"}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_input_path(value: str, allowed_suffixes: set) -> Path:
    """把待读取文件定位到 skill 的 official-docs/search-results/ 内。"""
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (SEARCH_RESULTS_DIR / raw.name).resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"只允许读取 {', '.join(sorted(allowed_suffixes))} 文件: {value}")
    if not _is_within(resolved, SEARCH_RESULTS_DIR.resolve()):
        raise ValueError(f"输入文件必须位于 official-docs/search-results/ 内: {SEARCH_RESULTS_DIR}")
    return resolved


def _safe_output_path(value: str, allowed_suffixes: set, default_suffix: str) -> Path:
    """把输出文件定位到 skill 的 official-docs/output/ 内。"""
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (OUTPUT_DIR / raw.name).resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        resolved = resolved.with_suffix(default_suffix)
    if not _is_within(resolved, OUTPUT_DIR.resolve()):
        raise ValueError(f"输出文件必须位于 official-docs/output/ 内: {OUTPUT_DIR}")
    return resolved


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
# 素材四分类
# ============================================================

KIND_CATALOG = {
    "policy": ("政策依据", "pol"),
    "data": ("数据支撑", "dat"),
    "case": ("参考案例", "cas"),
    "reference": ("表述参考", "ref"),
    "material": ("材料", "mat"),
}


def normalize_kind(raw: str) -> Tuple[str, str, str]:
    """把来源类型文本归一化为（类型键, 中文标签, css 类名）。"""
    text = str(raw or "")
    if "政策" in text or "法规" in text or "依据" in text or "policy" in text.lower():
        key = "policy"
    elif "数据" in text or "统计" in text or "指标" in text or "data" in text.lower():
        key = "data"
    elif "案例" in text or "经验" in text or "做法" in text or "case" in text.lower():
        key = "case"
    elif "表述" in text or "行文" in text or "reference" in text.lower():
        key = "reference"
    else:
        key = "material"
    label, css = KIND_CATALOG[key]
    return key, label, css


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


# ============================================================
# 素材提取（数据层：材料级编号优先 + 位置兜底）
# ============================================================

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


def source_from_article(item: Dict[str, Any], index: int, segment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
    segment = segment or {}
    # 材料级编号（角标/编号/materialIndex 等）优先；段落 id 是文章内段落序号
    # （各文章独立从 1 计数，全局无意义），仅作最后兜底，避免覆盖材料角标。
    explicit_id = first_str(
        item.get("角标"),
        item.get("编号"),
        item.get("materialIndex"),
        item.get("referenceIndex"),
        item.get("serialNo"),
        item.get("引用编号"),
        item.get("index"),
        item.get("idx"),
        item.get("seq"),
        vo.get("index"),
        vo.get("idx"),
        segment.get("id"),
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
        "excerpt": segment.get("text") or paragraph_text(item),
        "section": first_str(segment.get("title"), item.get("正文对应"), item.get("section")),
        "kind": first_str(item.get("类型"), item.get("type"), item.get("素材类型"), vo.get("typeName"), "材料"),
        "verify_note": first_str(item.get("核验"), item.get("verification"), item.get("核验说明")),
        "area": first_str(item.get("intentionArea"), item.get("area"), item.get("地域")),
    }
    key, label, css = normalize_kind(source["kind"])
    source["type_key"] = key
    source["type_label"] = label
    source["type_css"] = css
    source["has_link"] = bool(source["url"] and source["url"] != "接口未返回") or bool(source["policy_url"])
    # 数据缺口（无原文链接）不改变核验状态，仅在来源卡与核验单上温和提醒
    source["verified"] = bool(source["excerpt"])
    return source


def extract_articles_from_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 兼容两种形态：原始接口的 content.data.检索文章（嵌套）与手工合并 JSON 的
    # 顶层 检索文章（Agent 合并时常剥掉接口包装，与 knowledgeBase/self_check 平级）。
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else content.get("data")
    articles: List[Dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("检索文章"), list):
        articles.extend(x for x in data["检索文章"] if isinstance(x, dict))
    if isinstance(payload.get("检索文章"), list):
        articles.extend(x for x in payload["检索文章"] if isinstance(x, dict))
    return articles


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


def material_level_id(item: Dict[str, Any]) -> str:
    return first_str(
        item.get("角标"),
        item.get("编号"),
        item.get("materialIndex"),
        item.get("referenceIndex"),
        item.get("serialNo"),
        item.get("引用编号"),
    )


def extract_sources(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    raw_sources: List[Dict[str, Any]] = []
    raw_sources.extend(extract_reference_materials(payload))
    raw_sources.extend(extract_articles_from_search(payload))
    raw_sources.extend(extract_articles_from_deep(payload))

    sources: List[Dict[str, str]] = []
    seen = set()
    # 任一材料带材料级编号（角标等）即视为「已按素材清单编号」；
    # 全库都没有时按合并数组位置 1..N 自动编号（一条材料一张卡），
    # 与答案文件按合并顺序书写 [N] 角标的约定对齐。
    has_material_ids = any(material_level_id(item) for item in raw_sources)
    for item in raw_sources:
        segments = content_segments(item)
        # 有材料级编号（角标等）时整条材料只出一张来源卡（摘录为全文段落拼接），
        # 与素材清单「一条材料一个编号」对齐；无材料级编号时按段落拆分。
        single_card = bool(material_level_id(item)) or not has_material_ids
        candidates = [None] if single_card else (segments or [None])
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


def extract_knowledge_bases(payload: Dict[str, Any]) -> List[str]:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    values: List[str] = []
    for value in (payload.get("knowledgeBases"), content.get("knowledgeBases"),
                  payload.get("knowledgeBase"), content.get("knowledgeBase"), data.get("knowledgeBase")):
        if isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            values.append(value.strip())
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
    ("fact_basis", "事实有据"),
    ("quality", "质检通过"),
    ("placeholders", "无占位残留"),
    ("chart_sources", "图表有来源注"),
    ("caliber", "口径一致"),
]

SELF_CHECK_LABELS = dict(SELF_CHECK_ITEMS)
SELF_CHECK_LABELS.update({
    "事实有据": "事实有据", "质检通过": "质检通过", "无占位残留": "无占位残留",
    "图表有来源注": "图表有来源注", "口径一致": "口径一致",
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

    # ① 依据溯源：摘录可比对 + 原文链接/知识专库可回看。
    # 数据缺口（接口偶发不返回链接/摘录）降级为提醒，不参与核验判定。
    missing_links = [s["title"] for s in sources if not s.get("has_link")]
    missing_excerpts = [s["title"] for s in sources if not (s.get("excerpt") or "").strip()]

    # ② 引用绑定：正文角标与来源卡一一对应（按角标出现次数计，与用户在正文中数到的一致）
    cited = citation_ids(answer)
    all_marks = re.findall(r"\[(\d+)\]", answer)
    source_ids = {s["id"] for s in sources}
    unbound_ids = [cid for cid in cited if cid not in source_ids]
    unbound = [cid for cid in unbound_ids for _ in range(all_marks.count(cid))]
    no_citation = bool(sources) and not cited

    # ③ 时效检查：材料日期范围与历史材料计数
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

    # ④ 类型覆盖：素材四分类分布
    coverage = {key: 0 for key in KIND_CATALOG}
    for s in sources:
        coverage[s.get("type_key", "material")] = coverage.get(s.get("type_key", "material"), 0) + 1

    # ⑤ 自检：由检索/溯源 JSON 的 self_check 传入，未传入如实显示未记录
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
    policy_count = coverage.get("policy", 0)

    # 核验判定：只有真实错误才判不通过（无素材 / 正文无角标 / 角标未绑定）；
    # 数据缺口（缺链/缺摘录）只提醒不影响判定
    trace_ok = bool(sources)
    binding_ok = (not unbound) and not no_citation
    overall_passed = trace_ok and binding_ok

    reasons = []
    if not sources:
        reasons.append("未识别到来源材料")
    if no_citation:
        reasons.append("正文未包含来源角标，无法建立引用-素材对应")
    if unbound:
        reasons.append(f"{len(unbound)} 处正文角标未绑定素材")
    if self_check["status"] == "fail":
        reasons.append("自检存在未通过项")

    return {
        "overall": {
            "passed": overall_passed,
            "label": "核验完成，正文依据可交付" if overall_passed else "核验未完全通过",
            "reasons": reasons,
        },
        "traceability": {"total": len(sources), "passed": len(sources),
                         "missing_links": missing_links, "missing_excerpts": missing_excerpts},
        "binding": {"total": len(all_marks), "bound": len(all_marks) - len(unbound), "unbound": unbound_ids, "no_citation": no_citation},
        "freshness": freshness,
        "coverage": coverage,
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
    body = re.sub(r"\[(\d+)\]", citation_repl, body)
    return body


def is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    # GFM 语义：分隔行每格只需 1 个及以上短横线（允许 : 对齐标记）。
    # 兼容按表头宽度对齐写出的 "--" 等短分隔，避免整表退化为普通段落。
    return all(re.fullmatch(r":?-+:?", cell or "") for cell in cells)


def split_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown_table(lines: List[str], citation_repl) -> str:
    header = split_markdown_table_row(lines[0])
    body_lines = lines[2:] if len(lines) > 1 and is_markdown_table_separator(lines[1]) else lines[1:]
    head_html = "".join(f"<th>{render_inline_markdown(cell, citation_repl)}</th>" for cell in header)
    rows = []
    for line in body_lines:
        cells = split_markdown_table_row(line)
        if len(cells) < len(header):  # 行内缺格时补空，保持列对齐
            cells = cells + [""] * (len(header) - len(cells))
        rows.append("<tr>" + "".join(f"<td>{render_inline_markdown(cell, citation_repl)}</td>" for cell in cells) + "</tr>")
    wide_cls = " wide" if len(header) >= 4 else ""
    return f'<div class="tbl-wrap"><table class="data-tbl{wide_cls}"><thead><tr>{head_html}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


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
                           "text": heading_match.group(2).strip(), "cites": ids})
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
    无标题的短正文整篇一卡。
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


def render_verify_panel(v: Dict[str, Any], stage: str = "final") -> str:
    """核验报告单：报告级核验结论 + 五项指标。"""
    stage_label = STAGE_LABELS.get(stage, "成稿版")
    check_name = "提纲自检" if stage == "outline" else "成稿自检"
    check_hint = "事实/口径/占位/素材清单/类型标注" if stage == "outline" else "事实/质检/占位/来源注/口径"
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
    elif tr["missing_links"] or tr["missing_excerpts"]:
        gap_n = len(set(tr["missing_links"]) | set(tr["missing_excerpts"]))
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["total"]}/{tr["total"]}</span>'
                   f'<span class="d">素材摘录可比对；{gap_n} 条无原文链接，汇报前请注意核对</span></div>')
    else:
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">每条素材可回看原文</span></div>')

    bd = v["binding"]
    if bd.get("no_citation"):
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用绑定 0/0</span>'
                   f'<span class="d">正文未包含来源角标，{v["traceability"]["total"]} 条素材无法与正文对应</span></div>')
    elif not bd["total"]:
        bd_html = '<div class="vi"><span class="s none">— 引用绑定 0/0</span><span class="d">正文未包含来源角标</span></div>'
    elif not bd["unbound"]:
        bd_html = (f'<div class="vi"><span class="s ok">✓ 引用绑定 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">正文引用全部对应素材</span></div>')
    else:
        unbound_text = "、".join(f"[{esc(x)}]" for x in bd["unbound"][:8])
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用绑定 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">未绑定角标 {unbound_text}</span></div>')

    fr = v["freshness"]
    if fr:
        rng = f"{fr['min'][0]}-{fr['min'][1]:02d}～{fr['max'][0]}-{fr['max'][1]:02d}"
        old = f"（{fr['old_count']} 条历史材料，已按参考口径处理）" if fr["old_count"] else ""
        fr_html = f'<div class="vi"><span class="s ok">✓ 时效检查 完成</span><span class="d">材料日期 {esc(rng)}{esc(old)}</span></div>'
    else:
        fr_html = '<div class="vi"><span class="s none">— 时效检查 未记录</span><span class="d">素材未标注发布日期</span></div>'

    cov = v["coverage"]
    parts = [f"{KIND_CATALOG[k][0]} {cov[k]}" for k in ("policy", "data", "case", "reference") if cov.get(k)]
    cov_state = "ok" if cov.get("policy") or cov.get("data") or cov.get("case") else "none"
    cov_html = (f'<div class="vi"><span class="s {cov_state}">{"✓" if cov_state == "ok" else "—"} 类型覆盖</span>'
                f'<span class="d">{esc(" · ".join(parts)) if parts else "未标注素材类型（合并 JSON 可加「类型」字段）"}</span></div>')

    sc = v["self_check"]
    if sc["status"] == "pass":
        notes = "；".join(note for _, note in sc["items"].values() if note)
        title_attr = f' title="{esc(notes)}"' if notes else ""
        sc_html = (f'<div class="vi"><span class="s ok"{title_attr}>✓ {esc(check_name)} {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">{esc(check_hint)}{esc(" · 悬停查看核验说明" if notes else "")}</span></div>')
    elif sc["status"] == "fail":
        failed_parts = []
        for label, (status, note) in sc["items"].items():
            if status != "pass":
                suffix = f"（{note[:40]}…）" if len(note) > 40 else (f"（{note}）" if note else "")
                failed_parts.append(label + suffix)
        sc_html = (f'<div class="vi"><span class="s fail">✗ {esc(check_name)} {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">未通过：{esc("、".join(failed_parts))}</span></div>')
    else:
        sc_html = (f'<div class="vi"><span class="s none">— {esc(check_name)} 未记录</span>'
                   f'<span class="d">检索 JSON 未写入 self_check 字段</span></div>')

    manual = ""
    if v["policy_count"]:
        manual = (f'<div class="vi"><span class="s man">◐ 效力复核</span>'
                  f'<span class="d">{v["policy_count"]} 条政策依据建议按官方发布复核现行效力</span></div>')

    return f"""
    <div class="verify {state}">
      <div class="v-head"><span class="v-shield">{'✓' if ov['passed'] else '!'}</span>{esc(ov['label'])}（{esc(stage_label)}）{stamp}</div>
      {reasons_html}
      <div class="v-grid">
        {tr_html}{bd_html}{fr_html}{cov_html}{sc_html}{manual}
      </div>
      <div class="v-note">核验方法：深知可信搜索召回权威来源 → 逐条溯源（摘录比对 + 原文链接 + 知识专库回看）→ {'提纲/页面结论' if stage == 'outline' else '页面级结论'}引用绑定 → {esc(check_name)}。政策现行效力以官方发布为准。{manual_checks_html}</div>
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
            badge_text = f"本节引用 {len(sec_cites)} 处" + (f" · {unbound_count} 处未绑定" if unbound_count else " · 已核验")
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


def render_source_card(source: Dict[str, str]) -> str:
    vk_parts = []
    if source.get("verified"):
        fallback = "摘录可比对，原文链接与知识专库可回看" if source.get("has_link") else "摘录可比对；本条无原文链接，请留意核对"
        note = source.get("verify_note") or fallback
        vk_parts.append(f'<span class="sc-vk ok" title="{esc(note)}">✓ 已核验</span>')
        note_html = f'<div class="sc-vnote">{esc(short(note, 90))}</div>' if source.get("verify_note") else ""
    else:
        note_html = ""
    # 数据缺口（缺链/缺摘录）以温和提醒并列展示，不改变核验状态
    if not source.get("has_link"):
        vk_parts.append('<span class="sc-vk warn">◐ 无原文链接</span>')
    if not (source.get("excerpt") or "").strip():
        vk_parts.append('<span class="sc-vk warn">◐ 无摘录</span>')
    vk = "".join(vk_parts)
    links = render_source_links(source.get("url"), source.get("policy_url", ""))
    meta = " | ".join(v for v in [source.get("agency"), source.get("date"), source.get("area")] if v)
    section_html = f'<div class="sc-section">支撑：{esc(source["section"])}</div>' if source.get("section") else ""
    return (
        f'<article class="scard {source["type_css"]}" id="src-{esc(source["id"])}" data-type="{esc(source["type_key"])}" data-cite-id="{esc(source["id"])}">'
        f'<div class="sc-head"><span class="sc-id">[{esc(source["id"])}]</span>'
        f'<span class="sc-type">{esc(source["type_label"])}</span>{vk}</div>'
        f'<h4>{esc(source.get("title"))}</h4>'
        f'<div class="sc-meta">{esc(meta)}</div>'
        f'{section_html}{note_html}'
        f'{render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")}'
        f'{links}</article>'
    )


def render_sources_panel(sources: List[Dict[str, str]], used: List[str], kb_zone: str = "") -> str:
    if not sources:
        return '<aside class="sources"><h3>核验材料</h3><p class="empty">接口返回中未识别到可展示的材料。</p></aside>'
    used_set = set(used)
    cited_cards = [render_source_card(s) for s in sources if s["id"] in used_set]
    uncited = [s for s in sources if s["id"] not in used_set]
    uncited_html = ""
    if uncited:
        uncited_cards = "".join(render_source_card(s) for s in uncited)
        # 不用 <details> 折叠：部分宿主（WorkBuddy 等）的 HTML 预览服务会改写折叠区导致卡片丢失
        uncited_html = (
            '<div class="uncited-group"><div class="ug-title">未引用素材（'
            f'{len(uncited)} 条核心依据未在正文角标引用；完整召回可通过下方知识专库链接回看）</div>'
            f'<div class="uncited-list">{uncited_cards}</div></div>'
        )
    verified_count = sum(1 for s in sources if s.get("verified"))
    types_present = {s["type_key"] for s in sources}
    filters_html = ""
    if len(types_present) >= 2:
        buttons = ['<button class="on" data-f="all" type="button">全部</button>']
        for key in ("policy", "data", "case", "reference"):
            if key in types_present:
                buttons.append(f'<button data-f="{key}" type="button">{KIND_CATALOG[key][0]}</button>')
        filters_html = f'<div class="filters" role="group" aria-label="类型筛选">{"".join(buttons)}</div>'
    badge = "全部已核验" if verified_count == len(sources) else f"{verified_count}/{len(sources)} 已核验"
    return (
        '<aside class="sources" id="sources-panel" aria-label="核验材料面板">'
        '<a class="back-doc" href="#doc-top">↑ 返回核验报告单</a>'
        f'<h3>核验材料（{len(sources)} 条 · {esc(badge)}）</h3>'
        '<div class="src-tip">点击正文角标 [1] 定位材料原文并核对</div>'
        f'{filters_html}'
        '<input class="src-search" type="search" placeholder="搜索标题 / 来源 / 摘录…" aria-label="搜索来源">'
        f'<div class="src-list">{"".join(cited_cards)}{uncited_html}</div>'
        f'{kb_zone}'
        '</aside>'
    )


def render_kb_zone(kb_urls: List[str], kb_labels: List[str], source_count: int) -> str:
    if not kb_urls:
        return ""
    chips = []
    for index, url in enumerate(kb_urls):
        label = kb_labels[index] if index < len(kb_labels) else "相关搜索来源"
        chips.append(
            f'<a class="kb-chip" href="{esc(url)}" target="_blank" rel="noopener">'
            f'<span class="kb-label">{esc(label)}</span>'
            f'<span class="kb-count">{"原始召回" if index else f"{source_count} 条来源"} · 可回看</span>'
            '<span class="kb-arrow">打开 ↗</span></a>'
        )
    return (
        '<div class="kb-zone"><div class="kb-title">原始召回存档（深知知识专库）</div>'
        '<div class="kb-desc">以下链接可回看每次搜索的完整召回结果（含未写入正文的材料）；'
        '原文页面改版或下线时可回看当时召回的快照。逐条材料的核验请点击来源卡上的"查看原文"直达官方页面。</div>'
        f'<div class="kb-list">{"".join(chips)}</div></div>'
    )


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_search_trace", suffix_ext: str = ".html") -> str:
    raw = question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    suffix = timestamp.strftime("%Y%m%d_%H%M")
    stem = normalized[:32].strip("._-") or fallback
    return f"{stem}_{suffix}{suffix_ext}"


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "",
                generated_at: Optional[datetime] = None, stage: str = "final") -> str:
    # unwrap 会取出 content 包装；self_check / verification_checks / knowledgeBase 等
    # 控制字段可能写在原始 JSON 顶层（结构化写法）或 content 内（搜索返回），两边合并查。
    raw_payload = payload
    payload = unwrap(payload)
    for key in ("selfCheck", "self_check", "verificationChecks", "verification_checks",
                "knowledgeBases", "knowledgeBase", "knowledgeBaseLabels"):
        if key in raw_payload and key not in payload:
            payload[key] = raw_payload[key]
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    sources = align_sources_to_answer(answer, extract_sources(payload))
    used = citation_ids(answer)
    kb_urls = extract_knowledge_bases(payload)
    kb_labels = payload.get("knowledgeBaseLabels") if isinstance(payload.get("knowledgeBaseLabels"), list) else []
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")
    stage_label = STAGE_LABELS.get(stage, "成稿版")

    verification = compute_verification(answer, sources, payload, generated_at)
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warn-box"><b>生成检查未通过：正文没有来源角标。</b>'
            '本报告无法建立"结论-素材"核验对应，仅作素材清单参考。'
            '请修正答案文件（提纲版 _outline.md / 成稿版 _answer.txt）：在关键事实后标注 [1]、[2] 等角标'
            '并逐条对应素材清单，然后重新运行 render_trace_html.py 生成核验报告。</div>'
        )
    blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources})
    doc_title, sections = group_sections(blocks)
    display_title = doc_title or title
    report_label = f"可信溯源核验报告（{stage_label}）"
    kb_zone = render_kb_zone(kb_urls, kb_labels, len(sources))

    cov = verification["coverage"]
    meta_bits = []
    cov_bits = [f"{KIND_CATALOG[k][0]} {cov[k]}" for k in ("policy", "data", "case", "reference") if cov.get(k)]
    if cov_bits:
        meta_bits.append("素材：" + " · ".join(cov_bits))
    if sources:
        meta_bits.append(f"共 {len(sources)} 条")
    meta_bits.append("点击正文角标 [1] 定位材料原文")
    meta_line = " ｜ ".join(meta_bits)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display_title)} · {esc(report_label)}</title>
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
.data-tbl th{{background:#f2f5fb;font-weight:700;color:#374151;white-space:nowrap}}
.data-tbl tbody tr:nth-child(even) td{{background:#fafbfd}}
.data-tbl.wide{{min-width:560px}}
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
.filters{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}}
.filters button{{border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);
  padding:3px 11px;font-size:12px;cursor:pointer}}
.filters button.on{{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:700}}
.src-search{{width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:7px;font-size:12.5px;margin-bottom:12px}}
.scard{{border:1px solid var(--line);border-left-width:3px;border-radius:10px;padding:11px 13px;margin-bottom:10px;
  background:#fff;transition:box-shadow .25s}}
.scard.pol{{border-left-color:var(--policy)}}
.scard.dat{{border-left-color:var(--brand)}}
.scard.cas{{border-left-color:var(--case)}}
.scard.ref,.scard.mat{{border-left-color:var(--ref)}}
.scard.hl{{box-shadow:0 0 0 3px var(--brand)}}
.scard.hide{{display:none}}
.sc-head{{display:flex;align-items:center;gap:7px;margin-bottom:4px}}
.sc-id{{font-family:monospace;font-weight:800;font-size:11px;color:var(--brand);background:var(--brand-soft);
  border-radius:4px;padding:1px 7px}}
.sc-type{{font-size:11px;font-weight:700;border-radius:4px;padding:1px 8px;background:var(--ref-soft);color:var(--ref)}}
.scard.pol .sc-type{{background:var(--policy-soft);color:var(--policy)}}
.scard.dat .sc-type{{background:var(--brand-soft);color:var(--brand)}}
.scard.cas .sc-type{{background:var(--case-soft);color:var(--case)}}
.sc-vk{{margin-left:auto;font-size:11px;font-weight:800;color:var(--ok)}}
.sc-vk.warn{{color:var(--warn)}}
.scard h4{{margin:0 0 4px;font-size:13px;color:var(--navy);line-height:1.55}}
.sc-meta{{font-size:11.5px;color:var(--muted)}}
.sc-section{{font-size:11.5px;color:var(--brand);margin-top:3px;font-weight:600}}
.sc-vnote{{margin-top:5px;font-size:11.3px;color:var(--ok);line-height:1.6}}
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
@media (max-width:1020px){{
  .layout{{grid-template-columns:1fr}}
  .sources{{position:static;max-height:none}}
}}
@media print{{
  .topbar,.filters,.src-search{{display:none!important}}
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
  <div class="tb-title">{esc(display_title)} · {esc(report_label)}</div>
  <div class="tags">
    <span>生成于 {esc(generated)}</span>
    <span>素材来源：深知可信搜索</span>
  </div>
</header>

<div class="layout">
  <main class="report" aria-label="核验报告正文">
    <div class="r-head" id="doc-top">
      <h1>{esc(display_title)}</h1>
      <div class="sub">{esc(report_label)} ｜ {esc(meta_line)}</div>
    </div>
    {citation_warning}
    {render_verify_panel(verification, stage)}
    <a class="mobile-nav" href="#sources-panel">查看核验材料（{len(sources)} 条 · 点击角标可定位原文）↓</a>
    {render_section_cards(sections, sources)}
    <div class="foot">深知可信PPT · {esc(report_label)} ｜ 核验方法：可信搜索召回 → 逐条溯源 → 正文绑定 → {'提纲自检' if stage == 'outline' else '成稿自检'} ｜ 内容由 AI 生成，仅供参考，政策现行效力以官方发布为准</div>
  </main>
  {render_sources_panel(sources, used, kb_zone)}
</div>

<div class="sheet-mask" aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-label="核验材料">
  <div class="sheet-grab"></div>
  <div class="sheet-head"><b>核验材料</b><button class="sheet-close" type="button">收起</button></div>
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
  function openSheet(card) {{
    if (!sheet) return;
    var body = sheet.querySelector(".sheet-body");
    var clone = card.cloneNode(true);
    clone.removeAttribute("id");
    clone.classList.remove("hide");
    clone.classList.add("open");
    body.innerHTML = "";
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
        openSheet(card);
        return;
      }}
      card.classList.remove("hide", "open");
      card.classList.add("hl", "open");
      card.scrollIntoView({{ block: "center", behavior: "smooth" }});
      setTimeout(function () {{ card.classList.remove("hl"); }}, 2200);
    }});
  }});

  /* 摘录点击展开/收起 */
  cards.forEach(function (c) {{
    var ex = c.querySelector(".sc-excerpt");
    if (!ex) return;
    ex.addEventListener("click", function (e) {{
      if (e.target.closest("a")) return;
      c.classList.toggle("open");
    }});
  }});

  /* 证据 chips（灰框）：桌面端点击就地展开并高亮右栏来源卡；手机端不就地展开，点击直接弹出底部材料弹层 */
  document.querySelectorAll(".ev-chip").forEach(function (chip) {{
    var summary = chip.querySelector("summary");
    if (summary) {{
      summary.addEventListener("click", function (e) {{
        if (!isMobile()) return;
        e.preventDefault();
        var card = byId[chip.getAttribute("data-cite")];
        if (card) openSheet(card);
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

  /* 类型筛选 + 搜索 */
  var filter = "all";
  var kw = "";
  function apply() {{
    cards.forEach(function (c) {{
      var okType = filter === "all" || c.getAttribute("data-type") === filter;
      var okKw = !kw || (c.textContent || "").toLowerCase().indexOf(kw) !== -1;
      c.classList.toggle("hide", !(okType && okKw));
    }});
  }}
  document.querySelectorAll(".filters button").forEach(function (b) {{
    b.addEventListener("click", function () {{
      document.querySelectorAll(".filters button").forEach(function (x) {{ x.classList.remove("on"); }});
      b.classList.add("on");
      filter = b.getAttribute("data-f");
      apply();
    }});
  }});
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
        aligned[idx]["type_key"] = aligned[idx].get("type_key", "material")
        aligned[idx]["type_label"] = aligned[idx].get("type_label", "材料")
        aligned[idx]["type_css"] = aligned[idx].get("type_css", "mat")
    return aligned


def main() -> None:
    parser = argparse.ArgumentParser(description="生成深知可信PPT 可信溯源核验报告 HTML（提纲版/成稿版）")
    parser.add_argument("input_json", help="trusted_search.py 或合并后的检索 JSON")
    parser.add_argument("--output", help="输出 HTML 路径；不传时根据问题自动生成短文件名到 official-docs/output/")
    parser.add_argument("--title", default="可信溯源核验报告", help="演示标题；正文首行有标题时以正文为准")
    parser.add_argument("--answer-file", help="答案文件（提纲版 <项目短名>_outline.md / 成稿版 <项目短名>_answer.txt），关键事实后标 [N] 角标。")
    parser.add_argument("--clean-md-output", help="输出干净 Markdown 路径；内容来自同一份答案，并移除 [1]、【1】等溯源角标。")
    parser.add_argument("--question", default="", help="用户需求，用于自动生成文件名。")
    parser.add_argument("--stage", choices=["outline", "final"], default="final",
                        help="报告版本：outline 提纲版（确认门前事前核验）/ final 成稿版（交付时事后溯源），默认 final。")
    args = parser.parse_args()

    payload = load_json(_safe_input_path(args.input_json, {".json"}))
    answer_override = ""
    if args.answer_file:
        answer_override = _safe_input_path(args.answer_file, {".txt", ".md"}).read_text(encoding="utf-8")
    question = args.question.strip() or extract_question(unwrap(payload))

    # 生成前硬校验：有素材而正文无角标时拒绝生成，杜绝产出无核验对应的报告
    pre_answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(unwrap(payload))
    pre_sources = extract_sources(unwrap(payload))
    if pre_sources and not citation_ids(pre_answer):
        print("生成检查未通过：答案正文没有任何 [N] 来源角标，无法建立\"结论-素材\"核验对应。", file=sys.stderr)
        print(f"请修正答案文件（{'提纲版 _outline.md：页面规划表事实要点' if args.stage == 'outline' else '成稿版 _answer.txt：页面级结论文本'}"
              "的关键事实后标注 [1]、[2] 等角标并逐条对应素材清单），然后重新运行本脚本。", file=sys.stderr)
        raise SystemExit(2)
    # 生成前硬校验（反向）：正文有角标却识别不到任何素材，多为合并 JSON 结构不符
    # （渲染器识别 检索文章 的路径：顶层 或 content.data 嵌套），当场报错而非产出 0 卡报告
    if citation_ids(pre_answer) and not pre_sources:
        print("生成检查未通过：输入 JSON 未识别到任何素材，但正文包含 [N] 角标。", file=sys.stderr)
        print("请检查合并 JSON 结构：素材数组须为顶层 {\"检索文章\": [...]} 或原始接口的 content.data.检索文章 形态；"
              "knowledgeBase/self_check/verification_checks 放顶层。修正后重新运行本脚本。", file=sys.stderr)
        raise SystemExit(2)

    generated_at = datetime.now()
    if args.output:
        output = _safe_output_path(args.output, {".html", ".htm"}, ".html")
    else:
        output = _safe_output_path(safe_output_filename(question, generated_at), {".html", ".htm"}, ".html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(payload, args.title, answer_override=answer_override,
                                  question_override=args.question, generated_at=generated_at, stage=args.stage), encoding="utf-8")
    print(f"已生成：{output}")
    if args.clean_md_output:
        clean_output = _safe_output_path(args.clean_md_output, {".md"}, ".md")
    else:
        clean_output = _safe_output_path(output.with_suffix(".clean.md").name, {".md"}, ".md")
    clean_output.parent.mkdir(parents=True, exist_ok=True)
    clean_answer = strip_citation_markers(answer_override or extract_answer(unwrap(payload)))
    clean_output.write_text(clean_answer, encoding="utf-8")
    print(f"已生成干净 Markdown：{clean_output}")


if __name__ == "__main__":
    main()
