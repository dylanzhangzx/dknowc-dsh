#!/usr/bin/env python3
"""图表渲染模块（1.4.0）：ECharts 内联渲染 + 图表数据规范化。

被 `render_trace_html.py` 使用：核验报告内嵌图表（一体化，`--charts-json` 传入图表 JSON）。
**本 Skill 只有这一条图表路径**——不再另出独立可视化报告（1.4.0 起）。

设计要点：
- **零网络依赖**：echarts 源码来自包内 `resources/echarts.custom.min.js`（定制版，仅折线/柱状/饼图 +
  网格/提示框/图例/标题 + Canvas），渲染时内联进 HTML——交付物仍是单文件、离线可开。
- **数据可复核**：每个数据点带来源 url，图表项可点击跳转来源。
- **失败可降级**：资源缺失或数据不足时调用方整章略过（报告其余部分照常产出）；
  运行时异常由初始化脚本 try/catch 隐藏容器，不留空白图。
- **option 全 JSON 序列化**：不放任何函数（避免序列化失败），单位由坐标轴名与标题承担。

图表数据结构：
    {
      "items":   [{"name": ..., "metrics": {...}, "sources": [...]}],   # 对象×指标 → 每指标一个柱状图
      "metrics": [{"code": ..., "label": ..., "unit": ...}],            # 指标 schema（显式或自动识别）
      "trend":   {"x_labels": [...], "series": [{"name","values","unit","sources"}]},   # → 折线
      "compare": {"x_labels": [...], "series": [...]},                                  # → 分组柱状
      "share":   [{"name": ..., "value": ..., "unit": ..., "sources": [...]}]           # → 环形占比
    }
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent
ECHARTS_RESOURCE = SKILL_ROOT / "resources" / "echarts.custom.min.js"

# 分类色（浅色主题，与可视化报告一致）
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

EC_SOURCE_CACHE: Optional[str] = None


# ============================================================
# 基础工具
# ============================================================

def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def to_float(value: Any, default: float = 0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "").replace("，", "").strip())
    except (TypeError, ValueError):
        return default


def coerce_sources(value: Any) -> List[Dict[str, str]]:
    """把 sources（URL 字符串或 {url,title} 对象）统一为 [{url,title}]。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [{"url": value.strip(), "title": ""}] if value.strip() else []
    if not isinstance(value, list):
        return []
    out: List[Dict[str, str]] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                out.append({"url": item.strip(), "title": ""})
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("链接") or "").strip()
            if url:
                out.append({"url": url, "title": str(item.get("title") or item.get("标题") or "").strip()})
    return out


def load_echarts_source() -> Optional[str]:
    """读取包内定制版 echarts；缺失返回 None（调用方回退纯 SVG）。"""
    global EC_SOURCE_CACHE
    if EC_SOURCE_CACHE is not None:
        return EC_SOURCE_CACHE or None
    try:
        EC_SOURCE_CACHE = ECHARTS_RESOURCE.read_text(encoding="utf-8")
    except OSError:
        EC_SOURCE_CACHE = ""
    return EC_SOURCE_CACHE or None


# ============================================================
# 数据规范化
# ============================================================

def normalize_xy_series(block: Any) -> Optional[Dict[str, Any]]:
    """规范化 trend/compare 数据块：{x_labels, series:[{name, values, unit, sources}]}。

    兼容简写：x 与 labels/x_labels；values 支持 [数字] 与 [{value:数字}]；
    长度不齐按最短截齐（宁可少画不造假）；NaN/非数字剔除（否则折线断点/坐标非法）。
    """
    if not isinstance(block, dict):
        return None
    xs = block.get("x_labels") or block.get("x") or block.get("labels") or []
    xs = [str(x).strip() for x in xs if str(x).strip()]
    raw_series = [s for s in (block.get("series") or []) if isinstance(s, dict)]
    if not xs or not raw_series:
        return None
    series = []
    for s in raw_series:
        values = []
        for v in (s.get("values") or []):
            value = to_float(v.get("value") if isinstance(v, dict) else v, default=float("nan"))
            if value != value:  # NaN 剔除
                continue
            values.append(value)
        series.append({
            "name": str(s.get("name") or "").strip() or "系列",
            "values": values,
            "unit": str(s.get("unit") or "").strip(),
            "sources": coerce_sources(s.get("sources")),
        })
    width = min([len(xs)] + [len(s["values"]) for s in series]) if series else 0
    if width < 2:
        return None
    return {"x_labels": xs[:width], "series": [{**s, "values": s["values"][:width]} for s in series]}


def normalize_share(block: Any) -> Optional[List[Dict[str, Any]]]:
    """规范化占比数据：[{name, value, unit, sources}]，负值/非数剔除。"""
    if not isinstance(block, list):
        return None
    rows = []
    for r in block:
        if not isinstance(r, dict):
            continue
        value = to_float(r.get("value"), default=float("nan"))
        if value != value or value < 0:
            continue
        rows.append({
            "name": str(r.get("name") or "").strip() or "构成",
            "value": value,
            "unit": str(r.get("unit") or "").strip(),
            "sources": coerce_sources(r.get("sources")),
        })
    return rows if len(rows) >= 2 else None


def normalize_items(data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """对象×指标：返回 (items, metrics)。items 保留 sources 供点击溯源。"""
    raw_items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
    items = []
    metric_keys: List[str] = []
    metric_units: Dict[str, str] = {}
    for row in raw_items:
        sub = row.get("metrics")
        metrics = sub if isinstance(sub, dict) else {
            k: v for k, v in row.items()
            if not isinstance(v, (dict, list)) and to_float(v, default=float("nan")) == to_float(v, default=float("nan"))
            and str(v).strip() != ""
        }
        clean: Dict[str, float] = {}
        for k, v in (metrics or {}).items():
            fv = to_float(v, default=float("nan"))
            if fv != fv:
                continue
            key = str(k)
            clean[key] = fv
            if key not in metric_keys:
                metric_keys.append(key)
                metric_units[key] = ""
        items.append({
            "name": str(row.get("name") or row.get("名称") or f"对象{len(items) + 1}"),
            "metrics": clean,
            "sources": coerce_sources(row.get("sources")),
        })
    declared = data.get("metrics") if isinstance(data.get("metrics"), list) else []
    metrics: List[Dict[str, Any]] = []
    for m in declared:
        if not isinstance(m, dict):
            continue
        code = str(m.get("code") or m.get("label") or "").strip()
        if not code:
            continue
        metrics.append({"code": code, "label": str(m.get("label") or code), "unit": str(m.get("unit") or "")})
    if not metrics:
        metrics = [{"code": k, "label": k, "unit": metric_units.get(k, "")} for k in metric_keys]
    return items, metrics


# ============================================================
# option 构建
# ============================================================

def _ec_color(i: int) -> str:
    return PALETTE_LIGHT[i % len(PALETTE_LIGHT)]


def _ec_series_data(series: Dict[str, Any], labels: List[str]) -> List[Dict[str, Any]]:
    """ECharts data 项：{value, name, url}——url 供点击跳转来源。"""
    out = []
    for i, v in enumerate(series["values"]):
        item: Dict[str, Any] = {"value": v, "name": str(labels[i])}
        if series.get("sources"):
            url = series["sources"][0].get("url")
            if url:
                item["url"] = url
        out.append(item)
    return out


def _ec_base(title: str, unit: str) -> Dict[str, Any]:
    # option 整体 JSON 序列化，不得放函数；单位由 yAxis.name / 图标题承担。
    return {
        "title": {"text": title, "left": "center", "top": 4, "textStyle": {"fontSize": 14}},
        "tooltip": {"trigger": "axis", "confine": True},
        "grid": {"left": 48, "right": 24, "top": 46, "bottom": 40, "containLabel": True},
    }


def _ec_xy_option(kind: str, chart: Dict[str, Any], title: str, unit: str) -> Dict[str, Any]:
    """折线/柱状共用 option（trend→line，compare→bar 分组）。"""
    opt = _ec_base(title, unit)
    opt["legend"] = {"top": 26, "left": "center", "itemWidth": 14, "textStyle": {"fontSize": 11}}
    opt["xAxis"] = {"type": "category", "data": chart["x_labels"], "axisLabel": {"fontSize": 11}}
    opt["yAxis"] = {"type": "value", "name": unit, "nameTextStyle": {"fontSize": 10}, "axisLabel": {"fontSize": 10}}
    opt["series"] = []
    for i, s in enumerate(chart["series"]):
        opt["series"].append({
            "name": s["name"],
            "type": kind,
            "data": _ec_series_data(s, chart["x_labels"]),
            "barGap": "20%",
            "barWidth": 34,
            "symbolSize": 7,
            "label": {"show": True, "position": "top", "fontSize": 10, "formatter": "{c}"},
            "lineStyle": {"width": 2.2},
            "itemStyle": {"color": _ec_color(i)},
        })
    return opt


def _ec_pie_option(share: List[Dict[str, Any]], title: str) -> Dict[str, Any]:
    """环形占比 option（中心总量 + 图例右侧）。"""
    total = sum(r["value"] for r in share) or 1
    unit = share[0].get("unit", "")
    opt = _ec_base(title, unit)
    opt["tooltip"] = {"trigger": "item", "confine": True,
                      "formatter": "{b}：" + f"{{c}} {unit}" + "（{d}%）"}
    opt["legend"] = {"orient": "vertical", "right": 8, "top": "middle", "textStyle": {"fontSize": 11}}
    opt["series"] = [{
        "type": "pie",
        "radius": ["42%", "68%"],
        "center": ["38%", "54%"],
        "avoidLabelOverlap": True,
        "label": {"show": False},
        "emphasis": {"label": {"show": True, "formatter": "{b}：{c}（{d}%）"}},
        "data": [{"name": r["name"], "value": r["value"],
                  "url": r["sources"][0]["url"] if r.get("sources") else None}
                 for r in share],
        "color": [_ec_color(i) for i in range(len(share))],
    }]
    opt["graphic"] = [{"type": "text", "left": "38%", "top": "52%", "style": {
        "text": f"{total}", "textAlign": "center", "fontSize": 18, "fontWeight": 600}}]
    return opt


def _ec_items_bars(items: List[Dict[str, Any]], metrics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """对象×指标 → 每指标一个柱状图 option（单点不成图，与"≥2 可比对象"判据一致）。"""
    charts = []
    for idx, m in enumerate(metrics):
        data = []
        for item in items:
            value = item["metrics"].get(m["code"])
            if value is None:
                continue
            entry: Dict[str, Any] = {"value": value, "name": item["name"]}
            if item.get("sources"):
                url = item["sources"][0].get("url")
                if url:
                    entry["url"] = url
            data.append(entry)
        if len(data) < 2:  # 只有一个对象的柱状图没有对比意义，不成图
            continue
        opt = _ec_base(m["label"], m.get("unit", ""))
        opt["xAxis"] = {"type": "category", "data": [d["name"] for d in data], "axisLabel": {"fontSize": 11}}
        opt["yAxis"] = {"type": "value", "name": m.get("unit", ""), "axisLabel": {"fontSize": 10}}
        opt["series"] = [{"name": m["label"], "type": "bar", "data": data,
                          "barWidth": 42, "label": {"show": True, "position": "top", "fontSize": 10},
                          "itemStyle": {"color": _ec_color(idx)}}]
        charts.append({"id": f"chart_metric_{idx}", "title": m["label"], "option": opt})
    return charts


def build_charts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把图表数据映射为 ECharts 图表清单 [{id, title, option}]，覆盖四类图型。"""
    charts: List[Dict[str, Any]] = []
    items, metrics = normalize_items(data)
    if items and metrics:
        charts.extend(_ec_items_bars(items, metrics))
    trend = normalize_xy_series(data.get("trend"))
    if trend:
        unit = trend["series"][0].get("unit", "") if trend["series"] else ""
        charts.append({"id": "chart_trend", "title": "趋势变化", "option": _ec_xy_option("line", trend, "趋势变化", unit)})
    compare = normalize_xy_series(data.get("compare"))
    if compare:
        unit = compare["series"][0].get("unit", "") if compare["series"] else ""
        charts.append({"id": "chart_compare", "title": "并列对比", "option": _ec_xy_option("bar", compare, "并列对比", unit)})
    share = normalize_share(data.get("share"))
    if share:
        charts.append({"id": "chart_share", "title": "构成占比", "option": _ec_pie_option(share, "构成占比")})
    return charts


# ============================================================
# 渲染
# ============================================================

def render_blocks(charts: List[Dict[str, Any]], container_id: str = "") -> str:
    """图表容器 div（ECharts 初始化用 id 定位）。

    container_id 非空时给容器加 id（供核验报告章节锚点用），图表内部 id 不变。
    """
    blocks = []
    for c in charts:
        blocks.append(f'<div class="viz-panel"><h3>{esc(c["title"])}</h3>'
                      f'<div id="{c["id"]}" style="width:100%;height:360px"></div></div>')
    duo = " viz-duo" if len(charts) >= 2 else ""
    anchor = f' id="{container_id}"' if container_id else ""
    return f'<div class="card{duo}"{anchor}>{"".join(blocks)}</div>'


def render_script(charts: List[Dict[str, Any]], echarts_src: str) -> str:
    """内联 echarts 源码 + 初始化脚本（点击数据项跳转来源）。

    运行时异常兜底：初始化抛异常时隐藏该容器，不留空白图。
    """
    opts = json.dumps({c["id"]: c["option"] for c in charts}, ensure_ascii=False)
    opts = opts.replace("</", "<\\/")
    return (f"<script>{echarts_src}</script>\n"
            f"<script>(function(){{"
            f"var O={opts};"
            f"for(var id in O){{"
            f"var el=document.getElementById(id);if(!el||!window.echarts)continue;"
            f"var ec=window.echarts.default||window.echarts;"
            f"try{{var ch=ec.init(el);ch.setOption(O[id]);"
            f"ch.on('click',function(p){{if(p&&p.data&&p.data.url)window.open(p.data.url,'_blank');}});}}"
            f"catch(e){{el.style.display='none';}}"
            f"}}"
            f"}})();</script>")


