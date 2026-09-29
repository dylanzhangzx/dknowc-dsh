#!/usr/bin/env python3
"""校验溯源核验报告 JSON 的完整性，防止"素材脱离检索结果、字段残缺、核验单失真"。

背景（3.7.5 修复）：2026-09-24 WorkBuddy 实测——模型手写脚本人工挑拣 25 条材料、
脱离 82 篇合并产物，且手写溯源 JSON 缺 self_check / recalled_materials / 标准字段，
导致核验报告单三项"未记录"、依据溯源 0/24。本脚本在生成 HTML 前强制校验：

  1. 材料来源可回溯：每条 materials / recalled_materials 的标题/源网址能在
     合并产物（merged_all.json 或等价 --clean 同构文件）中找到对应；
  2. 字段完整性：materials 必须带 excerpts / type（source_url 允许缺省——接口未返回时
     按规则不填、不猜测），recalled_materials 非空；
  3. 角标对应：document_content 的 [n] 角标与 materials 一一对应，无越界；
  4. self_check 完整：五项检查结果必须全部写入（不得缺失导致"未记录"）。

用法：
  python3 scripts/check_materials.py <溯源JSON> <合并产物JSON>
  python3 scripts/check_materials.py --list-fields <溯源JSON>   # 只打印字段清单，不校验

通过输出 {"ok": true, ...}；失败输出 {"ok": false, "errors": [...]} 并以非 0 退出码结束，
阻断后续渲染（模型必须修正溯源 JSON 后重跑）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
SELF_CHECK_ITEMS = ["事实有据", "结构完整", "无占位残留", "无AI味", "格式合规"]
# 兼容键名空格差异（"无 AI 味" vs "无AI味"）
SELF_CHECK_KEYS = {
    "无AI味": ("无AI味", "无 AI 味"),
    "无AI味_alt": ("无AI味", "无 AI 味"),
}

# 合并产物中可定位材料的字段（--clean 同构，deep_convert / merge 产物均含）
SOURCE_TITLE_FIELDS = ("文章标题", "标题", "title")
SOURCE_URL_FIELDS = ("源网址", "原文链接", "sourceUrl", "source_url", "url")

# 溯源 JSON 中材料标题/链接的字段（与 source_note_html.py 读取口径一致）
MAT_TITLE_FIELDS = ("material_name", "材料名称", "title", "文章标题", "标题")
MAT_URL_FIELDS = ("source_url", "sourceUrl", "源网址", "原文链接", "url")
MAT_EXCERPT_FIELDS = ("excerpt", "摘录", "支撑内容", "support", "excerpts")
MAT_TYPE_FIELDS = ("type", "素材类型")


def _cm_ws_root() -> "Path":
    """dsh：会话工作区根（与各脚本的 WS_ROOT 同源解析）。"""
    import os as _os
    _ws = _os.environ.get("DKNWOC_WS_ROOT")
    if not _ws:
        _sid = _os.environ.get("DSH_SESSION_ID", "")
        _ws = str(Path.cwd() / "dknowc-output" / (_sid[:8] if _sid else "_default"))
    return Path(_ws).resolve()


def first_value(d: dict, keys: tuple) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v) if not isinstance(v, list) else str(v[0])
    return ""


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"错误：无法读取 {path}（{exc}）")


def build_source_index(merged: dict) -> dict:
    """从合并产物构建 {标题: {url, ...}} 索引（标题去规范化空格）。"""
    index = {}
    for art in merged.get("articles") or []:
        title = first_value(art, SOURCE_TITLE_FIELDS)
        if not title:
            continue
        key = re.sub(r"\s+", "", title)
        index.setdefault(key, {"title": title, "url": first_value(art, SOURCE_URL_FIELDS)})
    # policyFiles 也纳入（文号匹配用；部分材料可能只出现在 policyFiles）
    for pf in merged.get("policyFiles") or []:
        title = first_value(pf, ("title", "writtenText"))
        if title:
            key = re.sub(r"\s+", "", title)
            index.setdefault(key, {"title": title, "url": first_value(pf, ("sourceUrl", "url"))})
    return index


def check_material_source(mat: dict, index: dict, mat_no: int) -> list[str]:
    """校验单条材料能否在合并产物中回溯到来源。"""
    errors = []
    title = first_value(mat, MAT_TITLE_FIELDS)
    url = first_value(mat, MAT_URL_FIELDS)
    if not title and not url:
        return [f"材料[{mat_no}] 无标题且无 source_url，无法回溯来源"]

    if url:
        # 源网址必须能在合并产物中找到（或为空待补，不得是编造的）
        found = any(i.get("url") and (url == i["url"] or url.rstrip("/") == i["url"].rstrip("/"))
                    for i in index.values())
        if not found:
            errors.append(f"材料[{mat_no}] 的 source_url 不在合并产物中（可能编造）：{url[:60]}")
    if title:
        key = re.sub(r"\s+", "", title)
        if key not in index and not url:
            errors.append(f"材料[{mat_no}] 标题未在合并产物中找到且无 source_url：{title[:50]}")
    return errors


def check_citations(content: str, materials: list) -> list[str]:
    """校验 document_content 的 [n] 角标与 materials 一一对应。

    角标 n 是**素材清单中的位置序号**：写作时按清单顺序标 [n]，清单里未被正文引用的条目
    会移入 recalled_materials，因此 `build_trace_json.py` 产出的 materials **只装配被引用
    的那些，id 天然是稀疏的**（如清单 65 篇中未引用第 30 篇，则 id = 1..29、31..65）。
    故此处不能用 `len(materials)` 当上界、也不能要求 id 从 1 连续。
    （2026-09-29 修复：此前按 `len(materials)` + `range(1, n+1)` 校验，只要素材清单里存在
    未被正文引用的条目，就必然误报"角标越界"且校验永远无法通过——成都实测踩到，绕行方案
    是裁清单、重编号角标，属被迫绕过。）
    """
    errors = []
    if not content:
        return ["document_content 为空"]
    cites = {int(m.group(1)) for m in re.finditer(r"[\[【]\s*(\d+)\s*[\]】]", content)}
    if not cites:
        return [f"document_content 没有任何 [n] 角标（materials 共 {len(materials)} 条，无法核验对应）"]
    ids = {int(m["id"]) for m in materials if str(m.get("id", "")).strip().isdigit()}
    if not ids:
        return ["materials 缺 id 字段（应为该材料在素材清单中的位置序号），无法核验角标对应"]
    out_of_range = sorted(c for c in cites if c not in ids)
    if out_of_range:
        errors.append(f"角标在 materials 中找不到对应条目（现有 id：{sorted(ids)}）：{out_of_range}")
    unused = sorted(ids - cites)
    if unused:
        errors.append(f"以下材料未被正文引用（如确未引用应移入 recalled_materials）：{unused}")
    return errors


def _norm_key(k: str) -> str:
    """键名归一：去空格（'无 AI 味' → '无AI味'），用于宽容匹配。"""
    return re.sub(r"\s+", "", str(k))


def check_self_check(sc_raw) -> list[str]:
    """校验 self_check 五项齐全（渲染层能读到、不出现'未记录'）。

    兼容三种值形态（与 render_trace_html.py classify_check_value 一致）：
      ① 字符串 "通过：说明" / "未通过：说明"（渲染器主格式，build_trace_json 骨架即此）
      ② dict {"通过": true, "说明": "..."}
      ③ 简单字符串 "通过" / "未通过"
    兼容两种键名写法：'无AI味' 与 '无 AI 味'。
    """
    errors = []
    if sc_raw is None:
        return ["self_check 缺失（渲染层将显示五项'未记录'，必须如实写入五项结果）"]
    if isinstance(sc_raw, dict):
        present = {_norm_key(k) for k in sc_raw.keys()}
        missing = [k for k in SELF_CHECK_ITEMS if _norm_key(k) not in present]
        if missing:
            errors.append(f"self_check 缺 {len(missing)} 项：{missing}")
        for k in SELF_CHECK_ITEMS:
            item = next((sc_raw[kk] for kk in sc_raw if _norm_key(kk) == _norm_key(k)), None)
            if item is None or (isinstance(item, str) and not item.strip()):
                errors.append(f"self_check[{k}] 为空（渲染层会显示'未记录'，请写入'通过：说明'或'未通过：说明'）")
            elif isinstance(item, dict) and "通过" not in item and "passed" not in item and "pass" not in item:
                errors.append(f"self_check[{k}] 缺'通过/passed'字段")
            elif isinstance(item, str) and not any(p in item for p in ("通过", "未通过", "pass", "fail")):
                errors.append(f"self_check[{k}] 值未标明'通过/未通过'（渲染层按'未记录'处理）")
    elif isinstance(sc_raw, list):
        keys = {_norm_key(str(x.get("name") or x.get("项") or "")) for x in sc_raw if isinstance(x, dict)}
        missing = [k for k in SELF_CHECK_ITEMS if _norm_key(k) not in keys]
        if missing:
            errors.append(f"self_check 列表缺 {len(missing)} 项：{missing}")
    else:
        errors.append("self_check 类型异常（应为 dict 或 list）")
    return errors


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="校验溯源核验报告 JSON 完整性")
    parser.add_argument("trace_json", help="溯源核验报告 JSON（official-docs/input/）")
    parser.add_argument("merged_json", nargs="?", default=None,
                        help="合并产物 JSON（merged_all.json 或 --clean 同构文件）；缺省尝试 auto 查找")
    parser.add_argument("--list-fields", action="store_true", help="只打印溯源 JSON 字段清单")
    args = parser.parse_args()

    trace = load_json(Path(args.trace_json).expanduser())

    if args.list_fields:
        print(json.dumps({
            "顶层": list(trace.keys()),
            "materials数": len(trace.get("materials") or []),
            "recalled数": len(trace.get("recalled_materials") or []),
            "self_check": trace.get("self_check"),
            "materials字段样例": list((trace.get("materials") or [{}])[0].keys()),
        }, ensure_ascii=False, indent=2))
        return 0

    merged_path = args.merged_json
    if not merged_path:
        # 自动查找最近合并产物
        candidates = sorted(
            (_cm_ws_root() / "official-docs" / "search-results").glob("merged*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not candidates:
            raise SystemExit("错误：未找到合并产物 JSON，请显式传入 <合并产物JSON>")
        merged_path = str(candidates[0])
    merged = load_json(Path(merged_path).expanduser())

    errors = []
    index = build_source_index(merged)

    materials = trace.get("materials") or []
    recalled = trace.get("recalled_materials") or []

    # ① 材料来源可回溯
    for i, mat in enumerate(materials, 1):
        errors.extend(check_material_source(mat, index, i))
    for i, mat in enumerate(recalled, 1):
        errors.extend(check_material_source(mat, index, i))

    # ② 字段完整性
    # 注：source_url **允许缺省** —— search_guide.md 明确"接口未返回原网址时不填、不猜测"，
    # 此处若强制报错就与规则直接冲突（2026-09-29 修复：成都实测中《2025年成都市提振消费
    # 专项行动实施方案》接口未返回源网址，一旦被正文引用就必然校验失败，只能移出正文清单）。
    # 来源可回溯性由上面的 check_material_source 用"合并产物标题/URL 反查"保证；报告端对
    # 无源网址的材料会在卡片上如实标注"待补链接"。
    for i, mat in enumerate(materials, 1):
        if not first_value(mat, MAT_EXCERPT_FIELDS):
            errors.append(f"材料[{i}] 缺摘录（excerpts/摘录，正文引用须可比对原文）")
        if not first_value(mat, MAT_TYPE_FIELDS):
            errors.append(f"材料[{i}] 缺 type（四分类：政策依据型/数据支撑型/参考案例型/表述参考型）")
    if not recalled:
        errors.append("recalled_materials 为空——执行过搜索的任务必须包含全部未引用召回材料")

    # ③ 角标对应
    errors.extend(check_citations(trace.get("document_content") or "", materials))

    # ④ self_check 完整
    errors.extend(check_self_check(trace.get("self_check")))

    if errors:
        print(json.dumps({"ok": False, "errors": errors, "file": str(Path(args.trace_json))},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "ok": True,
        "file": str(Path(args.trace_json)),
        "materials": len(materials),
        "recalled_materials": len(recalled),
        "self_check": "完整" if trace.get("self_check") else "缺失",
        "note": "校验通过，可生成溯源核验报告 HTML",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
