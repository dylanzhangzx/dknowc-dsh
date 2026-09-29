#!/usr/bin/env python3
"""从「素材清单 + 正文（带角标）+ 合并产物」装配溯源核验报告 JSON。

背景（3.7.5 修复）：此前模型写完正文才反查"正文 [n] 对应哪篇素材"，再手写临时脚本拼
溯源 JSON——写作时引用情况无保障，溯源核验沦为"事后圆场"。修复后强制顺序：
  素材四分类 → 素材清单落盘（materials_<任务>.json）→ 用户确认 → 基于清单写正文（边写边标 [n]）
本脚本只做**装配**（不反查、不挑拣）：
  - materials：按正文 [n] 角标序号，从素材清单取对应篇，补标准字段（从合并产物映射段落/可信度/快照）
  - recalled_materials：清单中未被正文引用 + 合并产物中未选入清单的全部召回材料
  - self_check：骨架（五项待模型填写检查结果）
  - document_content：正文（带角标）原样写入

用法：
  python3 scripts/build_trace_json.py <素材清单> <正文文件> <合并产物JSON> \
      --title "<报告标题>" --output <溯源JSON>
  python3 scripts/build_trace_json.py --sample <合并产物JSON>   # 打印素材清单示例结构

输入：
  <素材清单>  = official-docs/input/materials_<任务>.json
    结构: { "task": "...", "selected": [ {"type":"政策依据型","标题":"...","源网址":"..."}, ... ] }
    （selected 每篇至少含 type + 标题 或 源网址；标准字段会从合并产物自动映射）
  <正文文件>  = 写作正文 .md/.txt，含 [1][2] 角标
  <合并产物>  = official-docs/search-results/merged_all.json（或等价 --clean 同构文件）

输出：
  溯源 JSON（与 check_materials.py / source_note_html.py 字段契约一致）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
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
INPUT_DIR = WS_ROOT / "official-docs" / "input"

# 合并产物文章字段（--clean 同构，deep_convert / merge 产物均含）
ART_TITLE_FIELDS = ("文章标题", "标题", "title")
ART_URL_FIELDS = ("源网址", "原文链接", "sourceUrl", "source_url", "url")
ART_PARAGRAPH_FIELDS = ("段落", "segments")
ART_CONFIDENCE_FIELDS = ("发布日期可信度", "可信度", "date_confidence", "confidence")
ART_SNAPSHOT_FIELDS = ("快照链接", "screenShotPath", "snapshot")

# 素材清单 selected 条目的定位/类型字段
SEL_TYPE_FIELDS = ("type", "素材类型", "类型")
SEL_TITLE_FIELDS = ("标题", "文章标题", "title", "material_name")
SEL_URL_FIELDS = ("源网址", "source_url", "sourceUrl", "原文链接", "url")
# 分组键兜底链不含"搜索地域"（3.7.6 修复）：地域名（"中国"/"浙江省"）做分组键无意义，
# 杭州实测 75/295 篇因"搜索目的"为空退化成地域胶囊；全部落空时归"其他检索"。
SEL_SEARCH_KEY_FIELDS = ("search_key", "搜索条件", "deep_group")

SELF_CHECK_ITEMS = ["事实有据", "结构完整", "无占位残留", "无AI味", "格式合规"]


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


def norm_key(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def build_article_index(merged: dict) -> dict:
    """合并产物 → {规范化标题: 文章} 与 {规范化源网址: 文章} 双索引。"""
    by_title, by_url = {}, {}
    for art in merged.get("articles") or []:
        t = first_value(art, ART_TITLE_FIELDS)
        u = first_value(art, ART_URL_FIELDS)
        if t:
            by_title.setdefault(norm_key(t), art)
        if u:
            by_url.setdefault(norm_key(u.rstrip("/")), art)
    for pf in merged.get("policyFiles") or []:
        t = first_value(pf, ("title", "writtenText"))
        if t:
            by_title.setdefault(norm_key(t), {"title": t, "源网址": first_value(pf, ("sourceUrl", "url"))})
    return by_title, by_url


def map_article_fields(art: dict) -> dict:
    """从合并产物文章映射溯源 JSON 标准字段。"""
    return {
        "material_name": first_value(art, ART_TITLE_FIELDS),
        "title": first_value(art, ART_TITLE_FIELDS),
        "source_url": first_value(art, ART_URL_FIELDS),
        "段落": art.get("段落") if isinstance(art.get("段落"), list) else (art.get("segments") or []),
        "发布日期": first_value(art, ("发布日期", "date", "日期")),
        "发布日期可信度": first_value(art, ART_CONFIDENCE_FIELDS),
        "快照链接": first_value(art, ART_SNAPSHOT_FIELDS),
        # search_key：知识专库分组胶囊的依据，必须用"搜索目的"（真实搜索路数，如
        # "查找两地现行人才落户政策…"），不能用 deep_group/搜索地域（那是服务端子查询
        # 或地域组合，会把 7 路真实搜索展成几十个碎片胶囊，2026-09-24 渝沪实测 29 个）。
        "search_key": (first_value(art, ("搜索目的", "purpose"))
                       or first_value(art, SEL_SEARCH_KEY_FIELDS)
                       or "其他检索"),
    }


def extract_citations(content: str) -> list[int]:
    """提取正文 [n] / 【n】 角标序号（按出现顺序去重保序）。"""
    seen, out = set(), []
    for m in re.finditer(r"[\[【]\s*(\d+)\s*[\]】]", content):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_selected_index(selected: list, by_title: dict, by_url: dict) -> list:
    """为清单每条定位合并产物文章；返回 (条目, 文章或None)。"""
    resolved = []
    for item in selected:
        t = first_value(item, SEL_TITLE_FIELDS)
        u = first_value(item, SEL_URL_FIELDS)
        art = None
        if u:
            art = by_url.get(norm_key(u.rstrip("/")))
        if art is None and t:
            art = by_title.get(norm_key(t))
        if art is None and t:
            # 标题前缀匹配（政策文件名常带"关于印发…的通知"变体）
            tk = norm_key(t)
            for k, a in by_title.items():
                if tk[:8] and (tk[:8] in k or k[:8] in tk):
                    art = a
                    break
        resolved.append((item, art))
    return resolved


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="从素材清单+正文+合并产物装配溯源 JSON")
    parser.add_argument("materials_list", nargs="?", help="素材清单 JSON（official-docs/input/materials_<任务>.json）")
    parser.add_argument("body_file", nargs="?", help="正文文件（带 [n] 角标）")
    parser.add_argument("merged_json", nargs="?", help="合并产物 JSON（merged_all.json 或 --clean 同构）")
    parser.add_argument("--title", default="", help="报告标题（用于溯源 JSON 的 title 字段）")
    parser.add_argument("--output", "-o", help="输出溯源 JSON 文件名（写入 official-docs/input/）")
    parser.add_argument("--sample", action="store_true", help="打印素材清单示例结构")
    args = parser.parse_args()

    if args.sample:
        print(json.dumps({
            "task": "任务名",
            "selected": [
                {"type": "政策依据型", "标题": "国务院关于印发新一代人工智能发展规划的通知", "源网址": "https://..."},
                {"type": "数据支撑型", "标题": "北京市人工智能产业发展报告", "源网址": "https://..."},
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    if not (args.materials_list and args.body_file and args.merged_json):
        raise SystemExit("用法：python3 scripts/build_trace_json.py <素材清单> <正文文件> <合并产物JSON> --title <标题> --output <溯源JSON>")

    materials_list = load_json(Path(args.materials_list).expanduser())
    body_path = Path(args.body_file).expanduser()
    body = body_path.read_text(encoding="utf-8")
    merged = load_json(Path(args.merged_json).expanduser())

    selected = materials_list.get("selected") or []
    if not selected:
        raise SystemExit("错误：素材清单 selected 为空，请先完成素材四分类并落盘素材清单")

    by_title, by_url = build_article_index(merged)
    resolved = resolve_selected_index(selected, by_title, by_url)

    # ① materials：按正文角标序取清单对应篇
    citations = extract_citations(body)
    by_pos = {n: item for n, item in enumerate(resolved, 1)}
    materials = []
    for n in citations:
        if n < 1 or n > len(resolved):
            # 角标越界：不装配该序号（check_materials 会报错），但仍记录
            continue
        item, art = resolved[n - 1]
        mat = map_article_fields(art) if art else {}
        mat["material_name"] = mat.get("material_name") or first_value(item, SEL_TITLE_FIELDS)
        mat["title"] = mat.get("title") or first_value(item, SEL_TITLE_FIELDS)
        mat["source_url"] = mat.get("source_url") or first_value(item, SEL_URL_FIELDS)
        mat["type"] = first_value(item, SEL_TYPE_FIELDS) or "材料"
        mat["id"] = n
        # 摘录：优先清单内 excerpt/support，否则取文章首段
        excerpt = first_value(item, ("excerpt", "摘录", "支撑内容", "support"))
        if not excerpt and mat.get("段落"):
            excerpt = mat["段落"][0].get("内容", "") if isinstance(mat["段落"][0], dict) else str(mat["段落"][0])
        mat["excerpt"] = excerpt[:400]
        mat["excerpts"] = [excerpt[:400]] if excerpt else []
        mat["search_key"] = first_value(item, SEL_SEARCH_KEY_FIELDS) or mat.get("search_key", "")
        materials.append(mat)

    if not materials:
        raise SystemExit("错误：正文没有任何 [n] 角标对应素材清单，请先基于清单写作并标注角标")

    # ② recalled_materials：清单未引用 + 合并产物未选入 materials 的全部
    used_urls = {norm_key(m.get("source_url", "")).rstrip("/") for m in materials if m.get("source_url")}
    used_titles = {norm_key(m.get("material_name", "")) for m in materials if m.get("material_name")}
    recalled = []
    seen_keys = set()
    for item, art in resolved:
        if art is None:
            continue
        u = first_value(art, ART_URL_FIELDS)
        t = first_value(art, ART_TITLE_FIELDS)
        key = norm_key(u or t)
        if key in used_urls or key in used_titles or key in seen_keys:
            continue
        seen_keys.add(key)
        rm = map_article_fields(art)
        rm["type"] = first_value(item, SEL_TYPE_FIELDS) or "材料"
        recalled.append(rm)
    # 合并产物中未被清单覆盖的剩余材料
    for art in merged.get("articles") or []:
        u = first_value(art, ART_URL_FIELDS)
        t = first_value(art, ART_TITLE_FIELDS)
        key = norm_key(u or t)
        if not key or key in used_urls or key in used_titles or key in seen_keys:
            continue
        seen_keys.add(key)
        rm = map_article_fields(art)
        rm["type"] = "材料"
        recalled.append(rm)

    # ③ self_check 骨架（五项待模型填写）
    # 注意：渲染器（render_trace_html.py normalize_self_check / classify_check_value）
    # 期望 self_check 的值为**字符串**（"通过：说明" / "未通过：说明"），不是 dict——
    # dict 会 str() 成 "{'通过': True...}" 无法匹配"通过"前缀，导致核验单显示"未记录"。
    # 骨架用空字符串占位，模型填写时写"通过：..."或"未通过：..."。
    self_check = {k: "" for k in SELF_CHECK_ITEMS}

    trace = {
        "title": args.title or (materials_list.get("task") or "溯源核验报告"),
        "doc_type": materials_list.get("doc_type", ""),
        "issue_org": materials_list.get("issue_org", ""),
        "publish_date": materials_list.get("publish_date", ""),
        "document_content": body,
        "materials": materials,
        "recalled_materials": recalled,
        "self_check": self_check,
    }

    out_path = args.output
    if not out_path:
        safe = re.sub(r"[^\w一-鿿-]+", "_", args.title or "溯源核验报告")[:80] or "溯源核验报告"
        out_path = f"{safe}_溯源核验报告.json"
    output = Path(out_path).expanduser()
    if not output.is_absolute():
        output = (INPUT_DIR / output.name).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "output": str(output.relative_to(SKILL_ROOT)) if output.is_relative_to(SKILL_ROOT) else str(output),
        "materials": len(materials),
        "recalled_materials": len(recalled),
        "citations": citations,
        "note": "溯源 JSON 已装配。请填写 self_check 五项检查结果，再运行 check_materials.py 校验、source_note_html.py 渲染。",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
