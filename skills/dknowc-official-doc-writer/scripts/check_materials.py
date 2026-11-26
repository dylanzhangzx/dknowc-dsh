#!/usr/bin/env python3
"""校验溯源核验报告 JSON 的完整性，防止"素材脱离检索结果、字段残缺、核验单失真"。

背景：防止模型手写脚本人工挑拣材料、脱离合并产物，以及手写溯源 JSON 缺失
self_check / recalled_materials / 标准字段，导致核验报告单多项"未记录"。本脚本在生成 HTML 前强制校验：

  1. 材料来源可回溯：每条 materials / recalled_materials 的标题/源网址能在
     合并产物（merged_all.json 或等价 --clean 同构文件）中找到对应；
  2. 字段完整性：materials 必须带 excerpts / type（source_url 允许缺省——接口未返回时
     按规则不填、不猜测），recalled_materials 非空；
  3. 角标对应：document_content 的 [n] 角标与 materials 一一对应，无越界；
  3a. 引用绑定：每处角标必须有对应的引用实例（quote），且 quote 能在该材料原文中逐字找到、
      sentence 能在正文中找到；外省材料只能作“借鉴”，标记“历史”的材料不得作为依据；
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
import unicodedata
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _cm_ws_root() -> "Path":
    """dsh：会话工作区根（与各脚本的 WS_ROOT 同源解析）。"""
    import os as _os
    _ws = _os.environ.get("DKNWOC_WS_ROOT")
    if not _ws:
        _sid = _os.environ.get("DSH_SESSION_ID", "")
        _ws = str(Path.cwd() / "dknowc-output" / (_sid[:8] if _sid else "_default"))
    return Path(_ws).resolve()
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


def norm_text(text) -> str:
    """比对用归一化：去空白、统一全半角括号与常见标点（只用于"是否包含"判断）。"""
    s = str(text or "")
    table = str.maketrans({"（": "(", "）": ")", "，": ",", "：": ":", "；": ";",
                           "“": '"', "”": '"', "‘": "'", "’": "'", "　": " "})
    s = s.translate(table)
    return re.sub(r"\s+", "", s)


def cmp_norm(text) -> str:
    """按“句子内容”比对用：去空白与全部标点/符号（含角标括号），只留文字与数字。"""
    s = unicodedata.normalize("NFKC", str(text or ""))
    return re.sub(r"[\s\W_]+", "", s)


SENTENCE_END = re.compile(r"[。！？!?；;\n\r]")


def mark_occurrences(body: str) -> list[tuple[int, str]]:
    """把正文按句切开，返回每处角标的 (mark, 该句归一化内容)，按正文出现顺序。

    公文习惯把角标写在句末标点之后（"……工作。[1]"），因此紧跟句末标点的
    “只含角标”的片段要并回前一句，否则会把角标自身当成一句。
    """
    parts = re.split(r"(?<=[。！？!?；;\n\r])", body)
    segs: list[str] = []
    for part in parts:
        if not part:
            continue
        residue = re.sub(r"[\[【]\s*\d+\s*[\]】]|\s", "", part)
        if segs and residue == "":
            segs[-1] += part
        else:
            segs.append(part)
    out: list[tuple[int, str]] = []
    for seg in segs:
        out.extend(_marks_in(seg))
    return out


def _marks_in(seg: str) -> list[tuple[int, str]]:
    marks = [int(x.group(1)) for x in re.finditer(r"[\[【]\s*(\d+)\s*[\]】]", seg)]
    return [(n, cmp_norm(seg)) for n in marks]


def check_mark_occurrence_binding(body: str, records: list) -> list[str]:
    """同一角标多次出现时，每条 sentence 必须对上“某一处”出现，不能多句套同一处。"""
    errors: list[str] = []
    occ: dict[int, list[str]] = {}
    for mark, seg in mark_occurrences(body):
        occ.setdefault(mark, []).append(seg)
    rec: dict[int, list[str]] = {}
    for r in records:
        try:
            mark = int(r.get("mark"))
        except (TypeError, ValueError):
            continue
        rec.setdefault(mark, []).append(cmp_norm(r.get("sentence")))
    for mark, segs in occ.items():
        sentences = list(rec.get(mark) or [])
        if len(sentences) != len(segs):
            continue  # 条数不匹配由上层的“逐处交付”检查报告
        pool = list(sentences)
        for i, seg in enumerate(segs, 1):
            if seg in pool:
                pool.remove(seg)
            else:
                errors.append(
                    f"角标 [{mark}] 第 {i} 处原句为「{seg[:26]}」，引用对照里没有对应这一处的 sentence"
                    f"（同一角标多处引用时，每处的 sentence 必须是该处自己的原句）")
        if pool:
            errors.append(f"角标 [{mark}] 有 {len(pool)} 条 sentence 与任何一处出现位置都对不上")
    return errors


def build_article_text_index(merged: dict) -> dict:
    """合并产物 → {归一化标题/URL: 全文段落拼接}，供引文逐字比对。"""
    out: dict = {}

    def add(key: str, text: str) -> None:
        if not key:
            return
        out[key] = out.get(key, "") + "\n" + text

    for art in merged.get("articles") or []:
        text = "\n".join(
            str(p.get("内容") or "") if isinstance(p, dict) else str(p)
            for p in (art.get("段落") or [])
        )
        key_t = norm_text(first_value(art, SOURCE_TITLE_FIELDS))
        key_u = norm_text(first_value(art, SOURCE_URL_FIELDS)).rstrip("/")
        add(key_t, text)
        add(key_u, text)
    return out


CIT_USAGE_VALUES = ("依据", "借鉴")
CIT_STATUS_VALUES = ("现行", "历史", "参考")
CIT_REGION_VALUES = ("本地", "上级", "外省", "全国")
CIT_QUOTE_MIN = 10
ISSUER_FIELDS = ("issue_org", "发布机关", "发文机关", "发布或实施机构")


def check_citation_binding(trace: dict, merged: dict | None = None) -> list[str]:
    """引用实例级校验：角标↔原句↔原文片段三方一致，版本与地域使用合规。

    merged 为 None 时跳过“quote 是否出现在该材料原文”的比对（没有合并产物可查），
    其余校验照常执行——渲染前的门禁正是走这条路径。
    """
    errors: list[str] = []
    body = trace.get("document_content") or ""
    counts: dict[int, int] = {}
    for m in re.finditer(r"[\[【]\s*(\d+)\s*[\]】]", body):
        n = int(m.group(1))
        counts[n] = counts.get(n, 0) + 1
    if not counts:
        return errors

    records = trace.get("citations") or []
    if not records:
        return [
            "缺 citations——正文含 [n] 角标时必须提供引用对照（每处引用一条 quote），"
            "否则无法核验“这句话是否真的出自该材料”"
        ]

    by_id = {}
    for i, mat in enumerate(trace.get("materials") or [], 1):
        mid = mat.get("id") or i
        by_id[int(mid)] = mat
    text_index = build_article_text_index(merged) if merged is not None else {}
    flat_body = norm_text(body)

    per_mark: dict[int, int] = {}
    for idx, rec in enumerate(records, 1):
        try:
            mark = int(rec.get("mark"))
            material = int(rec.get("material", mark))
        except (TypeError, ValueError):
            errors.append(f"引用[{idx}] 的 mark/material 不是整数")
            continue
        per_mark[mark] = per_mark.get(mark, 0) + 1
        quote = str(rec.get("quote") or "").strip()
        sentence = str(rec.get("sentence") or "").strip()
        usage = str(rec.get("用法") or rec.get("usage") or "").strip()
        if mark not in counts:
            errors.append(f"引用[{idx}] 的 mark={mark} 在正文中不存在")
            continue
        # ⓪ 角标号即素材清单序号：material 必须等于 mark，否则可拿别的材料顶替
        if material != mark:
            errors.append(
                f"引用[{idx}] 的 material={material} 与 mark={mark} 不一致——"
                f"角标号即素材清单序号，两者必须相同"
            )
            continue
        # ① 原句：必填、必须含该角标、必须能在正文找到
        if not sentence:
            errors.append(f"引用[{idx}]（[{mark}]）缺 sentence（正文中该角标所在的原句）")
        else:
            if not re.search(rf"[\[【]\s*{mark}\s*[\]】]", sentence):
                errors.append(
                    f"引用[{idx}]（[{mark}]）的 sentence 必须包含角标 [{mark}] 本身"
                    f"（照抄正文原句，含角标）：{sentence[:30]}"
                )
            elif flat_body and norm_text(sentence) not in flat_body:
                errors.append(f"引用[{idx}]（[{mark}]）的 sentence 在正文中找不到：{sentence[:30]}")
        # ② 引文：必填且有长度下限（过短片段会在原文中偶然命中）
        if len(norm_text(quote)) < CIT_QUOTE_MIN:
            errors.append(
                f"引用[{idx}]（[{mark}]）quote 为空或过短（须≥{CIT_QUOTE_MIN}字原文片段，"
                f"当前 {len(norm_text(quote))} 字）"
            )
        mat = by_id.get(material)
        if mat is None:
            errors.append(f"引用[{idx}]（[{mark}]）的 material={material} 不在 materials 中")
            continue
        # ③ 引文逐字落在该材料的原文段落里（有合并产物时才比对）
        if merged is not None:
            title_key = norm_text(first_value(mat, MAT_TITLE_FIELDS))
            url_key = norm_text(first_value(mat, MAT_URL_FIELDS)).rstrip("/")
            source_text = text_index.get(title_key) or text_index.get(url_key) or ""
            if not source_text.strip():
                errors.append(f"引用[{idx}]（[{mark}]）的材料在合并产物中无正文段落，无法比对引文")
            elif len(norm_text(quote)) >= CIT_QUOTE_MIN and norm_text(quote) not in norm_text(source_text):
                errors.append(
                    f"引用[{idx}]（[{mark}]）的 quote 在《{first_value(mat, MAT_TITLE_FIELDS)[:30]}》原文中找不到"
                    f"（引用须逐字取自该材料）：{quote[:40]}"
                )
        # ④ 用法与地域：外省材料只能作借鉴
        if usage not in CIT_USAGE_VALUES:
            errors.append(f"引用[{idx}]（[{mark}]）缺“用法”（依据/借鉴）")
        region = str(mat.get("region") or "").strip()
        if region == "外省" and usage == "依据":
            errors.append(
                f"引用[{idx}]（[{mark}]）把外省材料当本地依据——外省材料只能标“用法=借鉴”，"
                "并在正文写明是外地做法"
            )
        # ⑤ 效力：历史版本不得作为正文依据
        status = str(mat.get("status") or "").strip()
        if status == "历史":
            errors.append(
                f"引用[{idx}]（[{mark}]）引用了标记为“历史”的材料《{first_value(mat, MAT_TITLE_FIELDS)[:30]}》"
                "——同一事项已有更新文件时，正文不得再以旧文件为依据"
            )

    for mark, need in counts.items():
        got = per_mark.get(mark, 0)
        if got != need:
            errors.append(
                f"角标 [{mark}] 在正文出现 {need} 处，但引用对照只有 {got} 条——"
                f"同一材料被多处引用时，每处都要有自己的原文片段"
            )
    # ⑥ 出现次序绑定：同一角标多处出现时，每条 sentence 必须对上各自的第 k 处
    errors.extend(check_mark_occurrence_binding(body, records))
    return errors


def check_material_metadata(trace: dict) -> list[str]:
    """素材清单选中条目必须带 status／region／发布机关（含未被引用的 recalled）。"""
    errors: list[str] = []
    groups = (("materials", trace.get("materials") or []),
              ("recalled_materials", trace.get("recalled_materials") or []))
    for label, items in groups:
        for idx, mat in enumerate(items, 1):
            if not isinstance(mat, dict):
                continue
            # 合并产物里未被清单选中的召回材料不受此约束（from_selected=False）
            if label == "recalled_materials" and mat.get("from_selected") is False:
                continue
            mid = mat.get("id") or idx
            name = first_value(mat, MAT_TITLE_FIELDS)[:30] or f"材料{mid}"
            status = str(mat.get("status") or "").strip()
            region = str(mat.get("region") or "").strip()
            issuer = first_value(mat, ISSUER_FIELDS)
            if not status:
                errors.append(f"材料[{mid}]《{name}》缺 status（现行/历史/参考）")
            elif status not in CIT_STATUS_VALUES:
                errors.append(f"材料[{mid}]《{name}》的 status 取值不合法：{status}（现行/历史/参考）")
            if not region:
                errors.append(
                    f"材料[{mid}]《{name}》缺 region（本地/上级/外省/全国）——"
                    "缺省会让外省材料绕过“只能作借鉴”的校验"
                )
            elif region not in CIT_REGION_VALUES:
                errors.append(f"材料[{mid}]《{name}》的 region 取值不合法：{region}（本地/上级/外省/全国）")
    return errors


def collect_material_warnings(trace: dict) -> list[str]:
    """软提醒（不阻断）：素材清单条目缺发布机关——报告来源卡将不显示机构。

    接口对部分材料（新闻、案例、部分转发件）不返回发文机构；强制必填会迫使编造，
    因此只提示，不阻断。
    """
    warnings: list[str] = []
    groups = (("materials", trace.get("materials") or []),
              ("recalled_materials", trace.get("recalled_materials") or []))
    for label, items in groups:
        for idx, mat in enumerate(items, 1):
            if not isinstance(mat, dict):
                continue
            if label == "recalled_materials" and mat.get("from_selected") is False:
                continue
            if first_value(mat, ISSUER_FIELDS):
                continue
            mid = mat.get("id") or idx
            name = first_value(mat, MAT_TITLE_FIELDS)[:30] or f"材料{mid}"
            warnings.append(f"材料[{mid}]《{name}》缺发布机关——来源卡将不显示机构，如能补请补")
    return warnings


SELF_AUTHORED_MARKERS = ("台账", "专班", "责任人", "一式", "个工作日内送达",
                         "前完成", "逾期", "汇总表", "留档")


def collect_self_authored_warnings(trace: dict) -> list[str]:
    """软提醒（不阻断）：本单位的时限/分工安排属于自撰句，不应挂依据类角标。"""
    warnings: list[str] = []
    for idx, rec in enumerate(trace.get("citations") or [], 1):
        sentence = str(rec.get("sentence") or "")
        if str(rec.get("用法") or "") != "依据":
            continue
        hit = [m for m in SELF_AUTHORED_MARKERS if m in sentence]
        if hit:
            warnings.append(
                f"引用[{idx}] 所在句像是本单位安排（命中：{'、'.join(hit)}），"
                f"自撰句不应挂依据角标——请确认这句是否真有政策依据：{sentence[:36]}"
            )
    return warnings


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


def _verdict_of(item) -> str:
    """把一项自检的结论归一为 pass/fail/pending/none（口径与渲染内核一致）。"""
    if isinstance(item, dict):
        raw = item.get("verdict") or item.get("结论") or item.get("status")
    else:
        raw = item
    text = str(raw or "").strip().lower()
    if not text:
        return "none"
    for prefix in ("pending", "待定", "待确认", "待人工复核", "待复核"):
        if text.startswith(prefix):
            return "pending"
    for prefix in ("fail", "未通过", "不通过", "不合格", "false", "否"):
        if text.startswith(prefix):
            return "fail"
    for prefix in ("pass", "已通过", "通过", "合格", "ok", "true", "是"):
        if text.startswith(prefix):
            return "pass"
    return "none"


def check_self_check(sc_raw) -> list[str]:
    """校验 self_check 五项齐全且符合两轨验收结构（Agent 轨提交契约）。

    主格式（与渲染内核一致）：每项 {"verdict": "pass|fail|pending", "basis": "…", "evidence": ["…"]}；
    声明 pass 必须给非空 evidence（证据要素由渲染内核把关，此处先拦空证据）。
    兼容旧字符串 "通过：说明" / "未通过：说明"（裸"通过"无证据，按内核口径也会被拦）。
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
                errors.append(f"self_check[{k}] 为空（请按两轨验收契约写 {{verdict, basis, evidence}}）")
                continue
            verdict = _verdict_of(item)
            if verdict == "none":
                errors.append(f"self_check[{k}] 结论无法识别（verdict 须为 pass/fail/pending，或以'通过/未通过/待复核'开头）")
                continue
            evidence = ""
            if isinstance(item, dict):
                ev = item.get("evidence") or item.get("证据")
                if isinstance(ev, (list, tuple)):
                    evidence = "；".join(str(x).strip() for x in ev if str(x).strip())
                else:
                    evidence = str(ev or "").strip()
            else:
                # 旧字符串写法：证据 = 去掉"通过：/未通过：/待复核："等结论前缀后的说明；
                # 裸"通过"剥完前缀为空，与内核口径一致按证据不足拦
                text = str(item).strip()
                lowered = text.lower()
                for prefix in ("pending", "pass", "fail", "通过", "已通过", "未通过",
                               "不通过", "不合格", "合格", "待复核", "待定", "待确认"):
                    if lowered.startswith(prefix):
                        rest = text[len(prefix):].lstrip("：:，,、 ").strip()
                        evidence = rest
                        break
            if verdict == "pass" and not evidence:
                errors.append(f"self_check[{k}] 声明通过但未给 evidence 证据（裸'通过'会被渲染器按证据不足拦截）")
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

    # ③a 引用实例级校验：逐处原文片段、版本效力、地域用法
    errors.extend(check_citation_binding(trace, merged))
    # ③a-2 素材清单三字段：status／region／发布机关（含未被引用的 recalled）
    errors.extend(check_material_metadata(trace))
    warnings = collect_self_authored_warnings(trace)
    warnings.extend(collect_material_warnings(trace))

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
    result = {
        "ok": True,
        "file": str(Path(args.trace_json)),
        "materials": len(materials),
        "recalled_materials": len(recalled),
        "citations": len(trace.get("citations") or []),
        "body_chars": count_body_chars(trace.get("document_content") or ""),
        "self_check": "完整" if trace.get("self_check") else "缺失",
        "note": "校验通过，可生成溯源核验报告 HTML",
    }
    if warnings:
        result["warnings"] = warnings
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
