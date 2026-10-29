#!/usr/bin/env python3
"""校验溯源核验报告 JSON 的完整性，防止"素材脱离检索结果、字段残缺、核验单失真"。

背景：防止模型手写脚本人工挑拣材料、脱离合并产物，以及手写溯源 JSON 缺失
self_check / recalled_materials / 标准字段，导致核验报告单多项"未记录"。本脚本在生成 HTML 前强制校验：

  1. 材料来源可回溯：每条 materials / recalled_materials 的标题/源网址能在
     合并产物（merged_all.json 或等价 --clean 同构文件）中找到对应；
  2. 字段完整性：materials 必须带 excerpts / type（source_url 允许缺省——接口未返回时
     按规则不填、不猜测），recalled_materials 非空；
  3. 角标对应：document_content 的 [n] 角标与 materials 一一对应，无越界；
  4. self_check 完整：五项检查结果必须全部写入（不得缺失导致"未记录"）；
  5. 文号只认字段：正文每个文号必须能在 materials 的 `发文字号` 字段找到，
     禁止从段落正文提取；
  6. 篇幅：只校验用户明确要求或模板规定的字数；用户未提字数时不设默认区间。

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


def _cm_ws_root() -> "Path":
    """dsh：会话工作区根（与各脚本的 WS_ROOT 同源解析）。"""
    import os as _os
    _ws = _os.environ.get("DKNWOC_WS_ROOT")
    if not _ws:
        _sid = _os.environ.get("DSH_SESSION_ID", "")
        _ws = str(Path.cwd() / "dknowc-output" / (_sid[:8] if _sid else "_default"))
    return Path(_ws).resolve()


def build_source_index(merged: dict) -> tuple:
    """从合并产物构建（标题索引, 全量 URL 集合）。

    标题索引：{去空格标题: {title, url}}——同标题多来源变体只留首条（仅作
    "标题兜底"展示用）；URL 集合收录**全部变体 URL**（含 policyFiles）。
    按标题 setdefault 只保留首条 URL 时，同一文件在门户栏目页与部门页各有 URL 变体（如 zhengcefagui 与 gdj），引用非首条变体的材料会被误报"source_url 不在合并产物中（可能编造）"，校验卡死写作链。"""
    index: dict = {}
    urls: set = set()

    def _norm_url(u) -> str:
        return re.sub(r"\s+", "", str(u or "")).rstrip("/")

    for art in merged.get("articles") or []:
        title = first_value(art, SOURCE_TITLE_FIELDS)
        if not title:
            continue
        key = re.sub(r"\s+", "", title)
        index.setdefault(key, {"title": title, "url": first_value(art, SOURCE_URL_FIELDS)})
        for f in SOURCE_URL_FIELDS:
            if art.get(f):
                urls.add(_norm_url(art[f]))
    # policyFiles 也纳入（文号匹配用；部分材料可能只出现在 policyFiles）
    for pf in merged.get("policyFiles") or []:
        title = first_value(pf, ("title", "writtenText"))
        if title:
            key = re.sub(r"\s+", "", title)
            index.setdefault(key, {"title": title, "url": first_value(pf, ("sourceUrl", "url"))})
        for f in ("sourceUrl", "url"):
            if pf.get(f):
                urls.add(_norm_url(pf[f]))
    return index, urls


def check_material_source(mat: dict, index: dict, source_urls: set, mat_no: int) -> list[str]:
    """校验单条材料能否在合并产物中回溯到来源（URL 按全量变体集合判定）。"""
    errors = []
    title = first_value(mat, MAT_TITLE_FIELDS)
    url = first_value(mat, MAT_URL_FIELDS)
    if not title and not url:
        return [f"材料[{mat_no}] 无标题且无 source_url，无法回溯来源"]

    if url:
        # 源网址必须能在合并产物中找到（或为空待补，不得是编造的）；
        # 归一化（去空白、去尾斜杠）后对全量 URL 变体集合判定
        norm = re.sub(r"\s+", "", str(url)).rstrip("/")
        if norm not in source_urls:
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
    （按 `len(materials)` + `range(1, n+1)` 校验，只要素材清单里存在
    未被正文引用的条目，就必然误报"角标越界"且校验永远无法通过，只能被迫裁清单、重编号角标。）
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


DOCNUM_RE = re.compile(r"[〔\[【（(［]\s*(\d{4})\s*[〕\]】）)］]\s*(\d+)\s*号")
LONG_FORM_MARKERS = ("总结报告", "调研报告", "研究报告", "分析报告", "政策研究",
                     "产业研究", "工作总结", "汇报材料", "综合性总结")


def _docnum_key(text) -> tuple:
    """提取文号的年份+序号（忽略发文机关前缀），用于字段与正文的严格比对。"""
    m = DOCNUM_RE.search(str(text or ""))
    return (m.group(1), m.group(2)) if m else None


def check_doc_numbers(content: str, materials: list) -> list[str]:
    """文号只认 materials 的 `发文字号` 字段，正文不得从段落正文提取文号。

    检查中出现过整批文章 `发文字号` 全为空、正文却写了文号的情况，且文号来自召回段落。按用户口径"只接受接口返回"，这种情况必须拦截。
    """
    errors = []
    field_keys = set()
    for mat in materials or []:
        key = _docnum_key(mat.get("发文字号"))
        if key:
            field_keys.add(key)
    seen = set()
    for m in DOCNUM_RE.finditer(content or ""):
        key = (m.group(1), m.group(2))
        if key in field_keys or key in seen:
            continue
        seen.add(key)
        token = re.sub(r"\s+", "", m.group(0))
        errors.append(
            f"正文文号“{token}”在 materials 的 发文字号 字段中找不到"
            f"（不得从段落正文提取；字段为空时正文只写文件名）"
        )
    return errors


def count_body_chars(content: str) -> int:
    """正文汉字数：排除 Markdown 标题行，只统计正文汉字。"""
    lines = [line for line in str(content or "").splitlines()
             if not line.lstrip().startswith("#")]
    return len(re.findall(r"[一-鿿]", "\n".join(lines)))


def resolve_length_range(trace: dict):
    """篇幅区间：只认 trace.length_target 或用户问题里的明确字数；没有则返回 None。

    用户未提字数时不设默认下限/上限，按素材充分度自然收束。
    """
    target = trace.get("length_target")
    if isinstance(target, (list, tuple)) and len(target) == 2:
        try:
            lo, hi = int(target[0]), int(target[1])
            if lo > 0 and hi >= lo:
                return lo, hi
        except (TypeError, ValueError):
            pass
    if isinstance(target, dict):
        try:
            lo, hi = int(target.get("min")), int(target.get("max"))
            if lo > 0 and hi >= lo:
                return lo, hi
        except (TypeError, ValueError):
            pass
    question = str(trace.get("question") or "")
    m = re.search(r"(\d{3,5})\s*[-—至~～]\s*(\d{3,5})\s*字", question)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > 0 and hi >= lo:
            return lo, hi
    m = re.search(r"(\d{3,5})\s*字", question)
    if m:
        n = int(m.group(1))
        return int(n * 0.8), int(n * 1.2)
    return None


def check_length(trace: dict) -> list[str]:
    """用户明确要求字数时，研究型/综合长篇正文汉字数必须落在要求区间内。"""
    doc_type = str(trace.get("doc_type") or "")
    if not any(marker in doc_type for marker in LONG_FORM_MARKERS):
        return []
    length_range = resolve_length_range(trace)
    if length_range is None:
        return []
    lo, hi = length_range
    count = count_body_chars(trace.get("document_content") or "")
    if count < lo or count > hi:
        return [
            f"正文汉字数 {count} 不在用户要求的 {lo}–{hi} 范围（doc_type={doc_type}）——"
            "低于下限先补已召回事实，仍不足则交短稿并说明缺口；高于上限先压缩重复与铺垫，"
            "必保内容不得删。"
        ]
    return []


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
    if not str(trace.get("question") or "").strip():
        errors.append(
            "question 为空——溯源报告必须展示用户原问题全文；"
            "多行/长 prompt 请用 build_trace_json --question-file 传入，禁止只传首行"
        )
    index, source_urls = build_source_index(merged)

    materials = trace.get("materials") or []
    recalled = trace.get("recalled_materials") or []

    # ① 材料来源可回溯
    for i, mat in enumerate(materials, 1):
        errors.extend(check_material_source(mat, index, source_urls, i))
    for i, mat in enumerate(recalled, 1):
        errors.extend(check_material_source(mat, index, source_urls, i))

    # ② 字段完整性
    # 注：source_url **允许缺省** —— search_guide.md 明确"接口未返回原网址时不填、不猜测"，
    # 此处若强制报错就与规则直接冲突（接口未返回源网址、材料被正文引用后校验必然失败，只能移出正文清单）。
    # 来源可回溯性由上面的 check_material_source 用"合并产物标题/URL 反查"保证；报告端对
    # 无源网址的材料会在卡片上如实标注"待补链接"。
    for i, mat in enumerate(materials, 1):
        if not first_value(mat, MAT_EXCERPT_FIELDS):
            errors.append(f"材料[{i}] 缺摘录（excerpts/摘录，正文引用须可比对原文）")
        if not first_value(mat, MAT_TYPE_FIELDS):
            errors.append(f"材料[{i}] 缺 type（四分类：政策依据型/数据支撑型/参考案例型/表述参考型）")
    if not recalled:
        # 未执行检索的写作任务不做此项校验；执行过检索却缺 recalled 才是错误
        searched = bool(trace.get("检索记录") or trace.get("search_summary") or trace.get("检索通道"))
        if searched:
            errors.append("recalled_materials 为空——执行过搜索的任务必须包含全部未引用召回材料")

    # ③ 角标对应
    errors.extend(check_citations(trace.get("document_content") or "", materials))

    # ③b 文号只认接口字段（禁止从段落正文提取）
    errors.extend(check_doc_numbers(trace.get("document_content") or "", materials))

    # ③c 篇幅（仅用户明确要求字数时校验）
    errors.extend(check_length(trace))

    # ④ self_check 完整
    errors.extend(check_self_check(trace.get("self_check")))

    # ⑤ 研究资料 gate：研究型与综合长篇文种必须落盘研究资料底稿
    # （见 reference/research_notes.md：分类自检时初版、确认清单后定稿）。该层是
    # 研究型文种分析深度与数据密度的来源，曾因只写在散文段而整层被跳过
    # （无层 2509 字 vs 有层 9045 字）——此处在渲染前强制拦截。
    doc_type = str(trace.get("doc_type") or "")
    if any(k in doc_type for k in ("调研报告", "研究报告", "政策研究", "产业研究", "工作总结", "汇报材料")):
        input_dir = Path(args.trace_json).expanduser().resolve().parent
        notes = [p for p in input_dir.glob("*研究资料*.md")
                 if p.is_file() and p.stat().st_size > 500]
        if not notes:
            errors.append(
                f"doc_type={doc_type} 属研究型/综合长篇文种，但未找到研究资料文件"
                f"（{input_dir}/*研究资料*.md）——按 reference/research_notes.md 先生成研究资料"
                f"（初版：核心事实总表+数据口径表；定稿：角标与素材清单对齐，正文基于定稿写作），"
                f"缺少该层会导致正文过短")

    if errors:
        print(json.dumps({"ok": False, "errors": errors, "file": str(Path(args.trace_json))},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "ok": True,
        "file": str(Path(args.trace_json)),
        "materials": len(materials),
        "recalled_materials": len(recalled),
        "body_chars": count_body_chars(trace.get("document_content") or ""),
        "self_check": "完整" if trace.get("self_check") else "缺失",
        "note": "校验通过，可生成溯源核验报告 HTML",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
