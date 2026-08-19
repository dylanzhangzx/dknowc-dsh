#!/usr/bin/env python3
"""深知可信搜索：基于结构化 JSON/CSV 生成可交互政策可视化 HTML 报告（可选 SVG 快照）。

输入：Agent 基于已核验的可信搜索材料整理的结构化 JSON（见 SKILL.md「可视化」章节），
每个数据点需携带 sources 来源绑定。
输出：自包含可交互 HTML 报告（主交付）写入 official-docs/output/；--svg 追加同名静态 SVG 快照。
纯本地离线：仅 stdlib，内嵌 CSS/JS，无 CDN/外部字体。
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"

SCENARIOS = {"city_compare", "amount_compare", "process_steps", "timeline"}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_input_path(value: str, allowed_suffixes: set) -> Path:
    """把待读取数据文件定位到 skill 的 official-docs/search-results/ 内。"""
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (SEARCH_RESULTS_DIR / raw.name).resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"只允许读取 {', '.join(sorted(allowed_suffixes))} 文件: {value}")
    if not _is_within(resolved, SEARCH_RESULTS_DIR.resolve()):
        raise ValueError(f"输入文件必须位于 official-docs/search-results/ 内: {SEARCH_RESULTS_DIR}")
    return resolved


def _safe_output_path(value: str, allowed_suffixes: set, default_suffix: str = "") -> Path:
    """把输出文件定位到 skill 的 official-docs/output/ 内。"""
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (OUTPUT_DIR / raw.name).resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        if default_suffix and not resolved.suffix:
            resolved = resolved.with_suffix(default_suffix)
        else:
            raise ValueError(f"输出文件后缀必须是 {', '.join(sorted(allowed_suffixes))}: {value}")
    if not _is_within(resolved, OUTPUT_DIR.resolve()):
        raise ValueError(f"输出文件必须位于 official-docs/output/ 内: {OUTPUT_DIR}")
    return resolved


# 调色板：采纳 dataviz 校验参考值（浅/深两套），图表标记专用
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"]
HEAT_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5"]
PALETTE = PALETTE_LIGHT  # 保留旧 SVG 默认（浅色）
NAME_KEYS = ["name", "city", "region", "area", "对象", "名称", "城市", "地市", "地区", "区域"]
POSITION_KEYS = ["positioning", "特色定位", "定位", "说明", "summary", "description", "核心要点"]
KEYWORD_KEYS = ["keywords", "标签", "关键词", "特色标签"]
SKIP_NUMERIC_KEYS = set(NAME_KEYS + POSITION_KEYS + KEYWORD_KEYS + ["x", "y", "经度", "纬度"])


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def svg_esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=False)


def to_float(value: Any, default: float = 0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "").replace("，", "").strip())
    except (TypeError, ValueError):
        return default


def first_value(row: Dict[str, Any], keys: Iterable[str], default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def split_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    for sep in ["|", "、", "，", ",", ";", "；"]:
        text = text.replace(sep, "|")
    return [x.strip() for x in text.split("|") if x.strip()]


def load_data(path: Path) -> Dict[str, Any]:
    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {"items": data, "metadata": {"source_note": path.name}}
        if isinstance(data, dict):
            if isinstance(data.get("cities"), list) and not isinstance(data.get("items"), list):
                data["items"] = data["cities"]
            has_any = any(isinstance(data.get(key), list) for key in ("items", "time", "steps", "materials"))
            if has_any:
                data.setdefault("metadata", {})
                return data
        raise ValueError("JSON input must be a list, or contain items/cities/time/steps/materials.")

    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return {"items": list(csv.DictReader(f)), "metadata": {"source_note": f"CSV: {path.name}"}}

    raise ValueError("Input must be a .json or .csv file.")


def is_number_like(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        float(str(value).replace(",", "").replace("，", ""))
        return True
    except ValueError:
        return False


def _detect_unit(key: str) -> str:
    if "亿元" in key:
        return "亿元"
    if "万元" in key:
        return "万元"
    if "%" in key or "百分比" in key or "比例" in key or "率" in key:
        return "%"
    if any(token in key for token in ["数", "量", "项", "家"]):
        return "项"
    if "年" in key or "月" in key or "日" in key:
        return "年"
    return ""


def detect_metrics(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """自动识别数值列，返回显式 metric schema 元组（auto=True）。"""
    keys: List[str] = []
    for row in rows:
        for key, value in row.items():
            if key in keys or key in SKIP_NUMERIC_KEYS or isinstance(value, (dict, list)):
                continue
            if is_number_like(value):
                keys.append(key)
    metrics = []
    for key in keys:
        metrics.append({
            "code": key,
            "label": key,
            "unit": _detect_unit(key),
            "scale": None,
            "kind": "number",
            "direction": "higher_better",
            "auto": True,
        })
    return metrics


def build_metric_schema(data: Dict[str, Any], items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """显式 metrics 数组优先；缺省时自动识别数值列。返回 (schema, warnings)。"""
    warnings: List[str] = []
    declared = data.get("metrics")
    if isinstance(declared, list) and declared:
        schema = []
        for idx, item in enumerate(declared):
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("label") or "").strip()
            if not code:
                continue
            schema.append({
                "code": code,
                "label": str(item.get("label") or code),
                "unit": str(item.get("unit") or ""),
                "scale": to_float(item.get("scale"), 0) or None,
                "kind": str(item.get("kind") or "number"),
                "direction": str(item.get("direction") or "higher_better"),
                "auto": False,
            })
        if not schema:
            warnings.append("metrics 声明无效，已回退为自动识别数值列")
    else:
        schema = detect_metrics(items)
        if schema:
            warnings.append("指标为自动识别列，未做跨口径校准，请以政策原文为准")
    return schema, warnings


def normalize_metric(value: float, metric: Dict[str, Any], all_values: List[float]) -> float:
    """按 scale 或组内 min-max 归一化到 0-100；lower_better 反向。"""
    if metric.get("scale"):
        norm = min(100.0, value / float(metric["scale"]) * 100.0)
    else:
        values = [v for v in all_values if v is not None]
        if not values:
            return 0.0
        max_v = max(values)
        min_v = min(values)
        if max_v == min_v:
            norm = 75.0
        else:
            norm = (value - min_v) / (max_v - min_v) * 100.0
    if metric.get("direction") == "lower_better":
        norm = 100.0 - norm
    return round(max(0.0, min(100.0, norm)), 1)


def normalize_radar_score(value: float, all_values: List[float]) -> float:
    if not all_values:
        return 0.0
    max_v = max(all_values)
    if max_v <= 10:
        return round(max(0.0, min(100.0, value / 10 * 100)), 1)
    if max_v <= 100:
        return round(max(0.0, min(100.0, value)), 1)
    values = [v for v in all_values if v is not None]
    if not values:
        return 0.0
    lo, hi = min(values), max(values)
    if hi == lo:
        return 75.0
    return round(max(0.0, min(100.0, (value - lo) / (hi - lo) * 100)), 1)


def coerce_sources(value: Any) -> List[Dict[str, str]]:
    """把 sources（URL 字符串或 {url,title} 对象）统一为 [{url,title}]。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [{"url": value.strip(), "title": ""}] if value.strip() else []
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                out.append({"url": item.strip(), "title": ""})
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url:
                out.append({"url": url, "title": str(item.get("title") or "").strip()})
    return out


def aggregate_sources(data: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """汇总全部数据点来源，按 url 去重，记录被引用位置。"""
    refs: Dict[str, Dict[str, Any]] = {}
    groups = [
        ("对象", items, "name"),
        ("时间线", data.get("time") or [], "label"),
        ("流程步骤", data.get("steps") or [], "title"),
        ("材料", data.get("materials") or [], "name"),
    ]
    for kind, rows, label_key in groups:
        for row in rows:
            if not isinstance(row, dict):
                continue
            sources = coerce_sources(row.get("sources"))
            label = row.get(label_key) or row.get("name") or ""
            for src in sources:
                entry = refs.setdefault(src["url"], {"url": src["url"], "title": src["title"], "refs": []})
                if not entry["title"] and src["title"]:
                    entry["title"] = src["title"]
                entry["refs"].append({"kind": kind, "label": label})
    return list(refs.values())


def detect_scenario(data: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    explicit = str(metadata.get("scenario") or "").strip()
    if explicit in SCENARIOS:
        return explicit
    if isinstance(data.get("steps"), list) and data["steps"]:
        return "process_steps"
    if isinstance(data.get("materials"), list) and data["materials"] and not data.get("items"):
        return "process_steps"
    if isinstance(data.get("time"), list) and len(data["time"]) >= 2:
        return "timeline"
    if isinstance(data.get("items"), list) and data["items"]:
        if len(data["items"]) >= 2:
            return "city_compare"
        return "amount_compare"
    return "city_compare"


def _parse_date_key(value: Any) -> str:
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})年?(\d{1,2})?月?(\d{1,2})?日?$", text.replace("-", "年"))
    if not m:
        return text
    year = m.group(1)
    month = m.group(2) or "01"
    day = m.group(3) or "01"
    return f"{year}-{int(month):02d}-{int(day):02d}"


def build_report(data: Dict[str, Any], input_path: Path, metric_names: List[str] | None, scenario: Optional[str] = None) -> Dict[str, Any]:
    """编排全流程，返回 Report dict。"""
    metadata = dict(data.get("metadata") or {})
    metadata.setdefault("source_note", input_path.name)
    raw_items = [x for x in data.get("items", []) if isinstance(x, dict)]

    if not raw_items and not (data.get("steps") or data.get("materials") or data.get("time")):
        raise ValueError("Input contains no usable data: provide items/time/steps/materials.")

    metric_schema, schema_warnings = build_metric_schema(data, raw_items)
    warnings: List[str] = list(schema_warnings)

    items = []
    for idx, row in enumerate(raw_items, start=1):
        radar_scores = row.get("radar_scores") or row.get("雷达评分") or {}
        if not isinstance(radar_scores, dict):
            radar_scores = {}
        item = {
            "name": first_value(row, NAME_KEYS, f"对象{idx}"),
            "positioning": first_value(row, POSITION_KEYS, ""),
            "keywords": split_keywords(first_value(row, KEYWORD_KEYS, "")),
            "metrics": {},
            "radar_scores": {str(k): to_float(v) for k, v in radar_scores.items()},
            "note": str(row.get("note") or ""),
            "sources": coerce_sources(row.get("sources")),
        }
        for metric in metric_schema:
            if metric["code"] in row:
                item["metrics"][metric["code"]] = to_float(row.get(metric["code"]))
            elif metric["code"] in row.get("metrics", {}) if isinstance(row.get("metrics"), dict) else False:
                item["metrics"][metric["code"]] = to_float(row["metrics"].get(metric["code"]))
        items.append(item)

    for metric in metric_schema:
        values = [item["metrics"].get(metric["code"]) for item in items if item["metrics"].get(metric["code"]) is not None]
        for item in items:
            if metric["code"] in item["metrics"]:
                item.setdefault("normalized_metrics", {})[metric["code"]] = normalize_metric(
                    item["metrics"][metric["code"]], metric, values
                )
            else:
                item.setdefault("normalized_metrics", {})[metric["code"]] = 0.0

    radar_dims: List[str] = []
    for item in items:
        for dim in item["radar_scores"]:
            if dim not in radar_dims:
                radar_dims.append(dim)
    if radar_dims:
        for dim in radar_dims:
            raw_values = [item["radar_scores"].get(dim, 0) for item in items]
            for item in items:
                item["radar_scores"][dim] = normalize_radar_score(item["radar_scores"].get(dim, 0), raw_values)
    else:
        radar_dims = [metric["label"] for metric in metric_schema[:5]]
        for item in items:
            item["radar_scores"] = {label: item["normalized_metrics"].get(metric["code"], 0)
                                    for metric, label in zip(metric_schema[:5], radar_dims)}

    if scenario and scenario in SCENARIOS:
        final_scenario = scenario
    else:
        final_scenario = detect_scenario(data, metadata)

    time_rows = [r for r in (data.get("time") or []) if isinstance(r, dict)]
    for row in time_rows:
        row.setdefault("sources", coerce_sources(row.get("sources")))
    time_rows.sort(key=lambda r: _parse_date_key(r.get("date")))

    steps = [r for r in (data.get("steps") or []) if isinstance(r, dict)]
    for row in steps:
        row.setdefault("sources", coerce_sources(row.get("sources")))
    materials = [r for r in (data.get("materials") or []) if isinstance(r, dict)]
    for row in materials:
        row.setdefault("sources", coerce_sources(row.get("sources")))

    report = {
        "metadata": metadata,
        "scenario": final_scenario,
        "metrics": metric_schema,
        "items": items,
        "radar_dims": radar_dims,
        "time": time_rows,
        "steps": steps,
        "materials": materials,
        "sources_footer": aggregate_sources(data, items),
        "warnings": warnings,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return report


def metric_value(item: Dict[str, Any], key: str) -> float:
    return to_float(item["metrics"].get(key))


def _source_data_attr(sources: List[Dict[str, str]]) -> str:
    return html.escape(json.dumps(sources, ensure_ascii=False), quote=True)


def source_chips(sources: List[Dict[str, str]]) -> str:
    """行级来源入口：合并为一个 chip（悬停/点击展开全部来源），避免逐格撒点。"""
    if not sources:
        return ""
    data = _source_data_attr(sources)
    label = f"来源 {len(sources)}" if len(sources) > 1 else "来源"
    return f'<button type="button" class="src-chip" data-srcs="{data}" aria-label="查看来源">{label}</button>'


def module_intro(title: str, body: str) -> str:
    return f'<div class="module-head"><h2>{esc(title)}</h2><p>{esc(body)}</p></div>'


def render_data_table(report: Dict[str, Any]) -> str:
    """主视图：对象×指标数据表，原始值+单位，行级来源收敛。"""
    items = report["items"]
    metrics = report["metrics"]
    if not items or not metrics:
        return ""
    header = "".join(f"<th>{esc(m['label'])}<small>{esc(m['unit'])}</small></th>" for m in metrics)
    rows = []
    for item in items:
        cells = "".join(f"<td>{metric_value(item, m['code']):g}{esc(m['unit'])}</td>" for m in metrics)
        src = source_chips(item.get("sources", []))
        note = f'<span class="row-note">{esc(item["note"])}</span>' if item.get("note") else ""
        rows.append(
            f"<tr><th>{esc(item['name'])}</th>{cells}<td class='src-cell'>{src}{note}</td></tr>"
        )
    return f"""
    <div class="table-wrap">
      <table class="matrix data-view"><thead><tr><th>对象</th>{header}<th>来源</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    </div>
    """


def render_simple_bars(report: Dict[str, Any]) -> str:
    """简单柱状图：每指标一张横向柱，不带来源（来源已在数据表）。"""
    items = report["items"]
    metrics = report["metrics"]
    parts = []
    for m in metrics:
        ranked = sorted(items, key=lambda item: metric_value(item, m["code"]), reverse=True)
        max_value = max([metric_value(item, m["code"]) for item in ranked] + [1])
        bars = []
        for item in ranked:
            raw = metric_value(item, m["code"])
            width = 8 + 92 * raw / max(max_value, 1)
            bars.append(
                f"""
                <div class="hbar-row">
                  <span>{esc(item["name"])}</span>
                  <div class="hbar"><i style="width:{width:.1f}%"></i></div>
                  <b>{raw:g}{esc(m["unit"])}</b>
                </div>
                """
            )
        parts.append(f'<article class="metric-block"><h3>{esc(m["label"])}<small>{esc(m["unit"])}</small></h3>{"".join(bars)}</article>')
    return "\n".join(parts)


def render_timeline(report: Dict[str, Any]) -> str:
    rows = report["time"]
    if not rows:
        return ""
    tracks: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        track = str(row.get("area") or row.get("kind") or "全部")
        tracks.setdefault(track, []).append(row)
    parts = []
    for track, events in tracks.items():
        items_html = []
        for ev in events:
            items_html.append(
                f"""
                <div class="tl-item">
                  <div class="tl-date">{esc(ev.get("date", ""))}</div>
                  <div class="tl-title">{esc(ev.get("title") or ev.get("label", ""))}</div>
                </div>
                """
            )
        parts.append(f'<section class="tl-track"><h3>{esc(track)}</h3><div class="tl-line">{"".join(items_html)}</div></section>')

    hist = _timeline_histogram(rows)
    if hist:
        parts.append(f'<section class="hist"><h3>按年度分布</h3><div class="hist-bars">{"".join(hist)}</div></section>')
    return "\n".join(parts)


def _timeline_histogram(rows: List[Dict[str, Any]]) -> List[str]:
    years: Dict[str, int] = {}
    for row in rows:
        text = str(row.get("date") or "")
        m = re.match(r"^(\d{4})", text.replace("-", ""))
        if m:
            years[m.group(1)] = years.get(m.group(1), 0) + 1
    if not years:
        return []
    max_count = max(years.values()) or 1
    out = []
    for year in sorted(years):
        count = years[year]
        height = 20 + 80 * count / max_count
        out.append(
            f'<div class="hist-bar"><b style="height:{height:.0f}%"></b><span>{year}</span><em>{count}</em></div>'
        )
    return out


def render_steps(report: Dict[str, Any]) -> str:
    steps = report["steps"]
    if not steps:
        return ""
    parts = []
    for idx, step in enumerate(steps, start=1):
        meta = []
        if step.get("duration"):
            meta.append(f'<span class="step-meta">时限：{esc(step["duration"])}</span>')
        if step.get("owner"):
            meta.append(f'<span class="step-meta">受理：{esc(step["owner"])}</span>')
        parts.append(
            f"""
            <div class="step">
              <div class="step-no">{idx}</div>
              <div class="step-body">
                <div class="step-title">{esc(step.get("title") or f"步骤 {idx}")}</div>
                {f'<div class="step-detail">{esc(step["detail"])}</div>' if step.get("detail") else ''}
                <div class="step-meta-row">{"".join(meta)}</div>
              </div>
            </div>
            """
        )
    return f'<section class="stepper">{"".join(parts)}</section>'


def render_materials(report: Dict[str, Any]) -> str:
    materials = report["materials"]
    if not materials:
        return ""
    rows = []
    for item in materials:
        badge = '<span class="req req-yes">必需</span>' if item.get("required") else '<span class="req req-no">可选</span>'
        rows.append(
            f"<tr><td>{badge}</td><td>{esc(item.get('name', ''))}</td><td>{esc(item.get('note') or '')}</td></tr>"
        )
    return f"""
    <div class="table-wrap">
      <table class="matrix materials"><thead><tr><th>要求</th><th>材料名称</th><th>备注</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
    </div>
    """


def render_sources_footer(report: Dict[str, Any]) -> str:
    footer = report.get("sources_footer") or []
    if not footer:
        return '<p class="footer-empty">本报告未绑定任何来源链接。</p>'
    items = []
    for i, src in enumerate(footer, start=1):
        refs = "；".join(f"{r['kind']}·{esc(r['label'])}" for r in src["refs"][:4])
        title = src["title"] or src["url"]
        items.append(
            f'<li><span class="src-no">{i}</span><a href="{html.escape(src["url"], quote=True)}" target="_blank" rel="noopener">{esc(title)}</a><span class="src-refs">{esc(refs)}</span></li>'
        )
    return f'<ol class="source-list">{"".join(items)}</ol>'


CSS_STYLE = r"""<style>
:root {
  --surface-page:#fcfcfb; --surface-card:#ffffff; --border:#e6e4e0;
  --text-1:#0b0b0b; --text-2:#52514e; --text-3:#8a8781;
  --brand:#17324d; --brand-ink:#cfe6ff;
  --warn-bg:#fff7e6; --warn-ink:#8a5a00; --warn-border:#f3d9a4;
  --radius:12px; --shadow:0 1px 3px rgba(16,24,40,.06);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif;background:var(--surface-page);color:var(--text-1);line-height:1.65}
.page{max-width:1280px;margin:0 auto;padding:24px}
header.brand{background:var(--brand);color:#fff;border-radius:var(--radius);padding:20px 24px;display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between}
header.brand h1{font-size:22px;font-weight:800;letter-spacing:.02em}
header.brand .meta{color:var(--brand-ink);font-size:13px;margin-top:6px}
header.brand .hdr-actions{display:flex;gap:10px;align-items:center}
.btn{background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer;text-decoration:none}
.btn:hover{background:rgba(255,255,255,.22)}
.kb-link{background:rgba(255,255,255,.14);color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px 12px;font-size:13px;text-decoration:none}
.module-head{margin:8px 0 12px}
.module-head h2{font-size:20px;font-weight:800}
.module-head p{color:var(--text-3);font-size:13px}
.card{background:var(--surface-card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px;box-shadow:var(--shadow)}
.warn{border:1px solid var(--warn-border);background:var(--warn-bg);color:var(--warn-ink);border-radius:8px;padding:8px 12px;font-size:13px;margin:10px 0}
.table-wrap{overflow-x:auto}
table.matrix{border-collapse:collapse;width:100%;font-size:13px;min-width:480px}
table.matrix th,table.matrix td{border:1px solid var(--border);padding:8px 10px;text-align:left;white-space:nowrap}
table.matrix thead th{background:var(--surface-page);font-weight:700}
table.matrix thead th small{display:block;color:var(--text-3);font-weight:400}
table.matrix tbody th{font-weight:600}
table.matrix .src-cell{font-size:12px}
.row-note{display:block;color:var(--text-3);font-size:11px;margin-top:2px}
.metric-block{display:grid;gap:10px;margin-bottom:16px}
.metric-block h3{font-size:15px;font-weight:700}
.metric-block h3 small{color:var(--text-3);font-weight:400;margin-left:4px}
.hbar-row{display:flex;align-items:center;gap:10px;font-size:13px}
.hbar-row>span{width:110px;flex-shrink:0;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hbar{flex:1;height:18px;background:var(--border);border-radius:999px;overflow:hidden}
.hbar i{display:block;height:100%;background:#2a78d6;border-radius:999px}
.hbar-row b{width:80px;flex-shrink:0;text-align:right;font-weight:800}
.tl-track{margin-bottom:18px}
.tl-track h3{font-size:14px;color:var(--text-2);margin-bottom:8px}
.tl-line{display:flex;gap:0;position:relative;flex-wrap:nowrap;overflow-x:auto;padding-bottom:8px}
.tl-item{min-width:220px;max-width:260px;flex-shrink:0;border-left:3px solid #2a78d6;padding:4px 0 4px 14px;margin-right:8px}
.tl-date{font-size:12px;color:var(--text-3)}
.tl-title{font-size:14px;font-weight:700}
.hist-bars{display:flex;align-items:flex-end;gap:14px;height:160px;padding-top:10px}
.hist-bar{display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;height:100%;width:52px}
.hist-bar b{width:100%;background:#2a78d6;border-radius:6px 6px 0 0;display:block}
.hist-bar span{font-size:11px;color:var(--text-3)}
.hist-bar em{font-size:11px;color:var(--text-2);font-style:normal}
.step{display:flex;gap:14px;padding:12px 0}
.step-no{width:30px;height:30px;border-radius:50%;background:var(--brand);color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.step-body{flex:1}
.step-title{font-weight:700}
.step-detail{color:var(--text-2);font-size:13px}
.step-meta-row{display:flex;align-items:center;gap:10px;margin-top:4px;flex-wrap:wrap}
.step-meta{font-size:12px;color:var(--text-3)}
.req{display:inline-block;font-size:11px;border-radius:999px;padding:1px 8px;font-weight:600}
.req-yes{background:#e7f3ea;color:#1b7a3d}
.req-no{background:var(--border);color:var(--text-2)}
.src-chip{font-size:11px;color:#2a78d6;background:#eaf2fd;border:1px solid #c9ddf7;border-radius:999px;padding:1px 8px;cursor:pointer;margin-left:4px}
#source-pop{position:fixed;max-width:360px;background:var(--surface-card);color:var(--text-1);border:1px solid var(--border);border-radius:10px;padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.16);display:none;z-index:100}
#source-pop h4{font-size:13px;margin-bottom:6px}
#source-pop a{display:block;color:#2a78d6;font-size:13px;word-break:break-all;margin-top:4px}
.source-list{list-style:none;counter-reset:src}
.source-list li{display:flex;gap:10px;align-items:baseline;padding:6px 0;border-bottom:1px dashed var(--border)}
.source-list .src-no{counter-increment:src;color:var(--text-3);font-size:12px;flex-shrink:0}
.source-list a{color:#2a78d6;text-decoration:none;word-break:break-all}
.source-list .src-refs{color:var(--text-3);font-size:11px;margin-left:auto;text-align:right}
.footer-empty{color:var(--text-3);font-size:13px}
footer.note{color:var(--text-3);font-size:12px;margin-top:24px;border-top:1px solid var(--border);padding-top:14px}
</style>"""


JS_SCRIPT = r"""<script>
(function(){
  var pop=document.getElementById('source-pop');
  function closePop(){pop.style.display='none';}
  document.addEventListener('click',function(ev){
    var chip=ev.target.closest('.src-chip');
    if(chip){ev.stopPropagation();var srcs=JSON.parse(chip.getAttribute('data-srcs')||'[]');
      pop.innerHTML='<h4>来源</h4>'+srcs.map(function(s,i){return '<a href="'+s.url+'" target="_blank" rel="noopener">'+(s.title||('来源 '+(i+1)))+'</a>';}).join('');
      var r=chip.getBoundingClientRect();pop.style.left=Math.min(r.left,innerWidth-380)+'px';pop.style.top=(r.bottom+6)+'px';pop.style.display='block';return;}
    if(!ev.target.closest('#source-pop')){closePop();}
  });
})();
</script>"""


def render_html(report: Dict[str, Any], title: str) -> str:
    md = report["metadata"]
    sections = []

    # 数据表：主视图，对象×指标原始值
    if report["items"] and report["metrics"]:
        sections.append(module_intro("数据对比表", "搜索到的对象与指标原始数据，来源见每行右侧与页脚清单。"))
        sections.append(f'<div class="card">{render_data_table(report)}</div>')

    # 简单柱状图：每指标一张
    if report["items"] and report["metrics"]:
        sections.append(module_intro("指标对比图", "按指标分别对比，数值与上方表格一致。"))
        sections.append(f'<div class="card">{render_simple_bars(report)}</div>')

    if report["time"]:
        sections.append(module_intro("政策时间线", "按时间先后排列的事件节点。"))
        sections.append(f'<div class="card">{render_timeline(report)}</div>')

    if report["steps"]:
        sections.append(module_intro("办理流程", "按办理时序排列。"))
        sections.append(f'<div class="card">{render_steps(report)}</div>')

    if report["materials"]:
        sections.append(module_intro("材料清单", "区分必需与可选。"))
        sections.append(f'<div class="card">{render_materials(report)}</div>')

    notes = []
    if report["warnings"]:
        notes += [f'<div class="warn">{esc(w)}</div>' for w in report["warnings"]]
    if md.get("radar_note"):
        notes.append(f'<p>{esc(md["radar_note"])}</p>')
    if md.get("source_note"):
        notes.append(f'<p>数据说明：{esc(md["source_note"])}</p>')
    if notes:
        sections.append(module_intro("口径说明", "本报告的整理口径与注意事项。"))
        sections.append("<div class='card'>" + "".join(notes) + "</div>")

    main_html = "\n".join(sections)

    meta_line = " · ".join(v for v in [md.get("region"), md.get("topic"), md.get("eff_time"), f"生成时间 {report['generated_at']}"] if v)
    kb_url = md.get("knowledge_base_url")
    kb_link = f'<a class="kb-link" href="{html.escape(str(kb_url), quote=True)}" target="_blank" rel="noopener">知识专库</a>' if kb_url else ""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{CSS_STYLE}
</head>
<body>
<div class="page">
  <header class="brand">
    <div>
      <h1>{esc(title)}</h1>
      <div class="meta">{esc(meta_line)}</div>
    </div>
    <div class="hdr-actions">
      {kb_link}
    </div>
  </header>
  <main>
    {main_html}
  </main>
  <footer class="note">
    <p>本报告为 AI 基于深知可信搜索核验材料生成的综合解读，仅供参考；关键数值请以政策原文为准。</p>
    <h4 style="margin-top:10px">来源清单</h4>
    {render_sources_footer(report)}
  </footer>
</div>
<div id="tooltip" role="tooltip"></div>
<div id="source-pop"></div>
{JS_SCRIPT}
</body>
</html>"""


def cjk_width(text: Any) -> int:
    """中文字符按 2 宽、ASCII 按 1 宽估算，供 SVG 换行/截断用。"""
    total = 0
    for char in str(text or ""):
        total += 2 if ord(char) > 0x2E7F else 1
    return total


def wrap_text(text: Any, width: int = 18, max_lines: int = 2) -> List[str]:
    """按显示宽度（CJK 感知）换行，超行截断加省略号。"""
    value = str(text or "").strip()
    if not value:
        return [""]
    lines: List[str] = []
    current = ""
    current_width = 0
    for char in value:
        char_width = 2 if ord(char) > 0x2E7F else 1
        if current_width + char_width > width and current:
            lines.append(current)
            current = char
            current_width = char_width
            if len(lines) >= max_lines:
                break
        else:
            current += char
            current_width += char_width
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and cjk_width(value) > sum(cjk_width(line) for line in lines):
        lines[-1] = lines[-1].rstrip("，。；、") + "..."
    return lines


def svg_text_block(text: Any, x: float, y: float, width: int, size: int = 16, weight: int = 400, fill: str = "#334155", max_lines: int = 2) -> str:
    tspans = []
    for idx, line in enumerate(wrap_text(text, width=width, max_lines=max_lines)):
        dy = 0 if idx == 0 else size * 1.35
        tspans.append(f'<tspan x="{x:g}" dy="{dy:g}">{svg_esc(line)}</tspan>')
    return f'<text x="{x:g}" y="{y:g}" font-size="{size}" font-weight="{weight}" fill="{fill}">{"".join(tspans)}</text>'


def svg_bar(x: float, y: float, width: float, value: float, color: str, bg: str = "#e2e8f0") -> str:
    value = max(0, min(100, value))
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="10" rx="5" fill="{bg}"/>'
        f'<rect x="{x:g}" y="{y:g}" width="{width * value / 100:g}" height="10" rx="5" fill="{color}"/>'
    )


def _svg_wrap_link(html_part: str, sources: List[Dict[str, str]]) -> str:
    if not sources:
        return html_part
    return f'<a xlink:href="{html.escape(sources[0]["url"], quote=True)}" target="_blank" rel="noopener">{html_part}</a>'


def render_svg_snapshot(report: Dict[str, Any], title: str) -> str:
    items = report["items"]
    metrics = report["metrics"]
    md = report["metadata"]
    generated = report["generated_at"]
    source_note = str(md.get("source_note", "")).rstrip("。.")
    region = md.get("region") or "通用区域"
    topic = md.get("topic") or "政策研究"
    width = 1400
    height = 200 + max(len(items), 1) * 64 * max(len(metrics), 1) + 40
    font = 'font-family="system-ui,-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif"'
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{svg_esc(title)}" {font}>',
        f'<rect width="{width}" height="{height}" fill="#f4f7fb"/>',
        '<rect x="0" y="0" width="1400" height="150" fill="#17324d"/>',
        f'<text x="44" y="62" font-size="34" font-weight="800" fill="#ffffff">{svg_esc(title)}</text>',
        f'<text x="44" y="104" font-size="17" fill="#cfe6ff">{svg_esc(region)} · {svg_esc(topic)} · 生成时间 {svg_esc(generated)}</text>',
    ]

    # 每指标一张简单横向柱状图（与 HTML 表格同源，无主观评估）
    bar_x, bar_y = 44, 200
    for m_idx, m in enumerate(metrics):
        block_y = bar_y + m_idx * (max(len(items), 1) * 64 + 40)
        parts.append(f'<text x="{bar_x}" y="{block_y}" font-size="22" font-weight="800" fill="#0f172a">{svg_esc(m["label"])}（{svg_esc(m["unit"])}）</text>')
        ranked = sorted(items, key=lambda item: metric_value(item, m["code"]), reverse=True)
        max_value = max([metric_value(item, m["code"]) for item in ranked] + [1])
        for idx, item in enumerate(ranked):
            y = block_y + 44 + idx * 64
            raw = metric_value(item, m["code"])
            width_pct = 100 * raw / max(max_value, 1)
            bar = "".join([
                f'<text x="{bar_x}" y="{y+22}" font-size="16" font-weight="700" fill="#334155">{svg_esc(item["name"])}</text>',
                f'<rect x="{bar_x+170}" y="{y+4}" width="1000" height="22" rx="11" fill="#e2e8f0"/>',
                f'<rect x="{bar_x+170}" y="{y+4}" width="{10 + 990 * width_pct / 100:.1f}" height="22" rx="11" fill="#2a78d6"/>',
                f'<text x="{bar_x+170+1010}" y="{y+22}" font-size="16" font-weight="800" fill="#172033">{raw:g}{svg_esc(m["unit"])}</text>',
            ])
            parts.append(_svg_wrap_link(bar, item.get("sources", [])))

    parts.append(f'<text x="44" y="{height-20}" font-size="13" fill="#64748b">数据说明：{svg_esc(source_note)}。本图为静态快照，交互版见同名 HTML。</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _safe_output_stem(value: str) -> str:
    stem = re.sub(r"[^\w一-鿿-]+", "-", value).strip("-")
    return stem[:40] or "visualization"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成可交互政策可视化 HTML 报告（可选 SVG 快照）。")
    parser.add_argument("--input", required=True, help="结构化 JSON 或 CSV 数据路径。")
    parser.add_argument("--output", help="输出 HTML 文件名（official-docs/output/）；缺省按标题自动生成。")
    parser.add_argument("--title", default="政策研究可视化分析")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), help="场景覆盖：city_compare/amount_compare/process_steps/timeline")
    parser.add_argument("--svg", action="store_true", help="同时输出同名静态 SVG 快照。")
    parser.add_argument("--metrics", default="", help="逗号分隔的指标列名（旧格式兼容）；默认自动识别数值列。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = _safe_input_path(args.input, {".json", ".csv"})
    metric_names = [x.strip() for x in args.metrics.split(",") if x.strip()] if args.metrics else None
    data = load_data(input_path)
    report = build_report(data, input_path, metric_names, scenario=args.scenario)

    title = args.title or str(report["metadata"].get("title") or "政策研究可视化分析")
    if args.output:
        html_output = _safe_output_path(args.output, {".html", ".htm"}, ".html")
    else:
        stem = _safe_output_stem(str(report["metadata"].get("title") or report["scenario"]))
        html_output = _safe_output_path(f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M')}.html", {".html", ".htm"})

    html_output.parent.mkdir(parents=True, exist_ok=True)
    html_output.write_text(render_html(report, title), encoding="utf-8")
    print(str(html_output))

    if args.svg:
        svg_output = _safe_output_path(html_output.with_suffix(".svg").name, {".svg"})
        svg_output.write_text(render_svg_snapshot(report, title), encoding="utf-8")
        print(str(svg_output))


if __name__ == "__main__":
    main()
