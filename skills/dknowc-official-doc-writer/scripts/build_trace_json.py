#!/usr/bin/env python3
"""从「素材清单 + 正文（带角标）+ 合并产物」装配溯源核验报告 JSON。

背景旧实现模型写完正文才反查"正文 [n] 对应哪篇素材"，再手写临时脚本拼
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
from typing import Optional

# 同一角标多次出现时的句子绑定与事后校验共用一套归一化，避免两处口径不一致
from check_materials import check_mark_occurrence_binding, cmp_norm, mark_occurrences

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
# 分组键兜底链不含"搜索地域"地域名（"中国"/"浙江省"）做分组键无意义，
# "搜索目的"为空的篇目会退化成地域胶囊（避免大量篇目退化）；全部落空时归"其他检索"。
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
        # V2 新增文章级字段（D5）：文号优先取文章级「发文字号」
        "发文字号": first_value(art, ("发文字号", "文号")),
        "生效日期": first_value(art, ("生效日期", "effectiveDate")),
        "失效日期": first_value(art, ("失效日期", "expiryDate")),
        "文章类型": first_value(art, ("文章类型", "type")),
        "发布或实施机构": first_value(art, ("发布或实施机构", "发布机关")),
        "文件标签": first_value(art, ("文件标签",)),
        # search_key：知识专库分组胶囊的依据，必须用"搜索目的"（真实搜索路数，如
        # "查找两地现行人才落户政策…"），不能用 deep_group/搜索地域（那是服务端子查询
        # 或地域组合，会把 7 路真实搜索展成几十个碎片胶囊）。
        "search_key": (first_value(art, ("搜索目的", "purpose"))
                       or first_value(art, SEL_SEARCH_KEY_FIELDS)
                       or "其他检索"),
        # 检索通道（深知深度搜索 / 深知可信搜索 / 联网检索）：由 deep_convert / dkag_search /
        # websearch_convert 打标，溯源报告据此区分接口来源与各自检索路数
        "检索通道": first_value(art, ("检索通道",)),
        # 外部联网材料标记：溯源报告据此打「非官方来源」徽标（联网检索/宿主 WebSearch 路）
        "非官方来源": True if art.get("非官方来源") else "",
        "数据权威性": first_value(art, ("数据权威性", "authority")),
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


def count_marks(content: str) -> dict[int, int]:
    """统计每个角标在正文中出现的次数（引用实例必须逐处对应）。"""
    counts: dict[int, int] = {}
    for m in re.finditer(r"[\[【]\s*(\d+)\s*[\]】]", content):
        n = int(m.group(1))
        counts[n] = counts.get(n, 0) + 1
    return counts


def flat(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


CIT_USAGE_VALUES = ("依据", "借鉴")
CIT_STATUS_VALUES = ("现行", "历史", "参考")
CIT_REGION_VALUES = ("本地", "上级", "外省", "全国")
# 引文片段下限（去空白后的字符数）：过短的片段容易在原文中偶然命中，撑不起该句
CIT_QUOTE_MIN = 10


def find_citation_file(args, materials_path: Path) -> Optional[Path]:
    """定位引用对照文件：显式 --citations 优先；否则按素材清单同名规则查找。"""
    if args.citations:
        p = Path(args.citations).expanduser()
        if not p.is_absolute():
            p = (INPUT_DIR / p.name).resolve()
        return p if p.is_file() else None
    stem = materials_path.stem
    task = stem[len("materials_"):] if stem.startswith("materials_") else stem
    for cand in (materials_path.parent / f"引用对照_{task}.json",
                 materials_path.parent / "引用对照.json",
                 INPUT_DIR / f"引用对照_{task}.json",
                 INPUT_DIR / "引用对照.json"):
        if cand.is_file():
            return cand
    return None


def load_citation_records(path: Optional[Path], body: str, material_count: int) -> list:
    """读取并初校验引用对照；返回按正文出现顺序排列的引用实例列表。

    硬约束：正文出现的每个角标，都要有等量的引用实例（同一角标用几处，就交几条 quote）。
    这是"引用从篇级降到片段级"的落点——没有 quote 就无法逐字核验，直接阻断。
    """
    counts = count_marks(body)
    if not counts:
        return []
    if path is None:
        raise SystemExit(
            "错误：正文含 [n] 角标，但未找到引用对照文件。\n"
            "请先按 reference/materials_pipeline.md 生成 official-docs/input/引用对照_<任务>.json：\n"
            '  {"task": "...", "citations": [{"mark": 1, "material": 1, '
            '"sentence": "正文中的原句", "quote": "该句依据的原文片段", "用法": "依据"}]}\n'
            "正文每出现一次 [n]，就要交一条对应实例（同一角标多处引用＝多条）。"
        )
    data = load_json(path)
    records = data.get("citations") if isinstance(data, dict) else None
    if not isinstance(records, list) or not records:
        raise SystemExit(f"错误：{path.name} 的 citations 为空或不是数组")

    errors: list[str] = []
    per_mark: dict[int, int] = {}
    cleaned: list = []
    flat_body = flat(body)
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            errors.append(f"引用[{i}] 不是对象")
            continue
        try:
            mark = int(rec.get("mark"))
        except (TypeError, ValueError):
            errors.append(f"引用[{i}] 缺 mark（正整数，对应正文角标）")
            continue
        material = rec.get("material", mark)
        try:
            material = int(material)
        except (TypeError, ValueError):
            errors.append(f"引用[{i}] 的 material 不是整数")
            continue
        if mark not in counts:
            errors.append(f"引用[{i}] 的 mark={mark} 在正文中不存在")
            continue
        if material < 1 or material > material_count:
            errors.append(f"引用[{i}] 的 material={material} 超出素材清单范围（1..{material_count}）")
            continue
        if material != mark:
            errors.append(
                f"引用[{i}] 的 material={material} 与 mark={mark} 不一致——"
                f"角标号即素材清单序号，两者必须相同，否则正文 [{mark}] 可以拿第 {material} 篇的原文通过校验")
            continue
        quote = str(rec.get("quote") or "").strip()
        sentence = str(rec.get("sentence") or "").strip()
        usage = str(rec.get("用法") or rec.get("usage") or "").strip()
        if len(flat(quote)) < CIT_QUOTE_MIN:
            errors.append(
                f"引用[{i}]（mark={mark}）quote 为空或过短（须≥{CIT_QUOTE_MIN}字原文片段，"
                f"当前 {len(flat(quote))} 字）")
        if not sentence:
            errors.append(f"引用[{i}]（mark={mark}）缺 sentence（正文中该角标所在的原句）")
        elif not re.search(rf"[\[【]\s*{mark}\s*[\]】]", sentence):
            errors.append(
                f"引用[{i}]（mark={mark}）的 sentence 必须包含角标 [{mark}] 本身"
                f"（照抄正文原句，含角标）：{sentence[:30]}")
        elif flat(sentence) not in flat_body:
            errors.append(f"引用[{i}]（mark={mark}）的 sentence 在正文中找不到：{sentence[:30]}")
        if usage not in CIT_USAGE_VALUES:
            errors.append(f"引用[{i}]（mark={mark}）的用法须为「依据」或「借鉴」，当前：{usage or '空'}")
        per_mark[mark] = per_mark.get(mark, 0) + 1
        cleaned.append({"mark": mark, "material": material, "quote": quote,
                        "sentence": sentence, "usage": usage})

    for mark, need in counts.items():
        got = per_mark.get(mark, 0)
        if got != need:
            errors.append(
                f"角标 [{mark}] 在正文出现 {need} 处，但引用对照只有 {got} 条——"
                f"每处引用都要交一条对应原文片段（不能一篇材料只交一段、多处复用）")
    # 同一角标多次出现时，每条 sentence 必须对上各自的第 k 处（不能多句套同一处）
    errors.extend(check_mark_occurrence_binding(body, cleaned))
    if errors:
        raise SystemExit("错误：引用对照校验未通过：\n- " + "\n- ".join(errors))

    # 按正文出现次序装配：按句子内容逐处认领，认领不到即报错（杜绝靠条数糊弄）
    pool = list(cleaned)
    ordered = []
    for mark, seg in mark_occurrences(body):
        hit = next((r for r in pool if r["mark"] == mark and cmp_norm(r["sentence"]) == seg), None)
        if hit is None:
            raise SystemExit(
                f"错误：引用对照与正文错位——角标 [{mark}] 的正文原句「{seg[:26]}」没有对应的引用记录，"
                "请按出现次序逐处补齐 sentence"
            )
        pool.remove(hit)
        ordered.append(hit)
    return ordered


def require_inside(path_value: str, label: str) -> Path:
    """输入路径必须落在本技能目录内（official-docs 之下），否则拒绝读取。

    关标统一由脚本自身定位，不接受目录外的绝对路径，避免把任意文件读进产物。
    """
    path = Path(path_value).expanduser().resolve()
    allowed = [(WS_ROOT / "official-docs").resolve()]
    if not any(path.is_relative_to(base) for base in allowed):
        raise SystemExit(
            f"错误：{label} 必须位于 {WS_ROOT / 'official-docs'} 之内，当前为 {path}。"
        )
    if path.suffix.lower() != ".json" and label != "问题文件":
        raise SystemExit(f"错误：{label} 必须是 JSON 文件：{path}")
    return path

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
            # 标题前缀匹配（政策文件名常带"关于印发…的通知"变体）：
            # 只接受“共同前缀 ≥12 字”的变体，避免短前缀命中无关文件
            tk = norm_key(t)
            if len(tk) >= 12:
                for k, a in by_title.items():
                    if len(k) >= 12 and (k.startswith(tk[:12]) or tk.startswith(k[:12])):
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
    parser.add_argument("--question", default="", help="用户原始问题全文（写入溯源 JSON 顶层 question；"
                                                      "溯源报告顶部展示完整原问题，供报告独立使用）")
    parser.add_argument("--question-file", help="用户原始问题全文文件（多行/长 prompt 优先用此参数，"
                                                "避免只传首行导致溯源报告原问题被截断）")
    parser.add_argument("--citations", help="引用对照 JSON（official-docs/input/引用对照_<任务>.json）；"
                                            "缺省按素材清单同名自动查找")
    parser.add_argument("--output", "-o", help="输出溯源 JSON 文件名（写入 official-docs/input/）")
    parser.add_argument("--sample", action="store_true", help="打印素材清单示例结构")
    args = parser.parse_args()

    if args.sample:
        print(json.dumps({
            "task": "任务名",
            "selected": [
                {"type": "政策依据型", "标题": "国务院关于印发新一代人工智能发展规划的通知", "源网址": "https://...",
                 "发布机关": "国务院", "status": "现行", "region": "全国"},
                {"type": "数据支撑型", "标题": "北京市人工智能产业发展报告", "源网址": "https://...",
                 "发布机关": "北京市经济和信息化局", "status": "现行", "region": "外省"},
            ],
            "引用对照示例": {
                "task": "任务名",
                "citations": [
                    {"mark": 1, "material": 1, "sentence": "正文中该角标所在的原句",
                     "quote": "该句依据的原文片段（须在材料中逐字存在）", "用法": "依据"},
                ],
            },
        }, ensure_ascii=False, indent=2))
        return 0

    if not (args.materials_list and args.body_file and args.merged_json):
        raise SystemExit("用法：python3 scripts/build_trace_json.py <素材清单> <正文文件> <合并产物JSON> --title <标题> --output <溯源JSON>")

    materials_list = load_json(require_inside(args.materials_list, "素材清单"))
    question_text = (args.question or "").strip()
    if args.question_file:
        question_path = require_inside(args.question_file, "问题文件")
        try:
            question_text = question_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SystemExit(f"错误：无法读取 --question-file {question_path}（{exc}）")
    body_path = Path(args.body_file).expanduser()
    try:
        body_path.resolve().relative_to(INPUT_DIR.resolve())
    except ValueError:
        raise SystemExit(
            f"错误：正文文件必须位于 {INPUT_DIR}/ 下，当前为 {body_path}。\n"
            "带角标的正文是本 Skill 的内部中间文件，不得写到宿主会话目录；"
            "请先保存到 official-docs/input/ 后再装配溯源 JSON。"
        )
    body = body_path.read_text(encoding="utf-8")
    merged = load_json(require_inside(args.merged_json, "合并产物"))

    selected = materials_list.get("selected") or []
    if not selected:
        raise SystemExit("错误：素材清单 selected 为空，请先完成素材四分类并落盘素材清单")

    by_title, by_url = build_article_index(merged)
    resolved = resolve_selected_index(selected, by_title, by_url)

    # ① materials：按正文角标序取清单对应篇
    citations = extract_citations(body)
    citation_file = find_citation_file(args, Path(args.materials_list).expanduser())
    citation_records = load_citation_records(citation_file, body, len(resolved))
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
        # 版本与地域元数据（素材清单必填）：供报告展示与 check_materials 拦截"引用历史版本/外省依据"
        mat["status"] = first_value(item, ("status", "效力状态", "版本状态"))
        mat["region"] = first_value(item, ("region", "地域属性", "地域"))
        mat["issue_org"] = first_value(item, ("发布机关", "发文机关", "发布或实施机构"))
        # 引用实例：本篇在正文中被引用的每一处，各带自己的原文片段
        mat["citations"] = [c for c in citation_records if c["material"] == n]
        materials.append(mat)

    if not materials:
        raise SystemExit("错误：正文没有任何 [n] 角标对应素材清单，请先基于清单写作并标注角标")

    # 按角标号（=素材清单序号）升序重排：渲染层按"位置"给材料编号，只有 materials 处于
    # 1..N 的 id 顺序时，位置才等于角标号。旧实现按正文"出现顺序"输出，只要正文首个引用
    # 不是 [1]（如先引 [23]），胶囊标题与角标号就会整体错位——溯源错配，务必升序。
    materials.sort(key=lambda m: m["id"])

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
        # 来自素材清单的条目：版本/地域/发布机关与 selected 一样必须齐备（check_materials 校验）
        rm["from_selected"] = True
        rm["status"] = first_value(item, ("status", "效力状态", "版本状态"))
        rm["region"] = first_value(item, ("region", "地域属性", "地域"))
        rm["issue_org"] = first_value(item, ("发布机关", "发文机关", "发布或实施机构"))
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
        # 合并产物里未被清单选中的召回材料：不受"三字段必填"约束
        rm["from_selected"] = False
        recalled.append(rm)

    # ③ self_check 骨架（五项待模型填写，两轨验收的 Agent 轨）
    # 每项填结构化对象：{"verdict": "pass|fail|pending", "basis": "结论依据", "evidence": ["可回查证据", …]}。
    # 硬约束：verdict=pass 时 evidence 必须含可回查要素（材料角标 [n]／条款号／文号／日期／
    # 文件名／GB 标准号任一），裸写「通过」或证据无要素会被渲染器按 evidence_missing 拦截；
    # fail 否决、pending 只表示待人工复核。骨架用空字符串占位（如实显示"未记录"）。
    self_check = {k: "" for k in SELF_CHECK_ITEMS}

    trace = {
        "title": args.title or (materials_list.get("task") or "溯源核验报告"),
        # 2026-10-08：完整原问题（溯源报告须能独立使用）。
        # 传用户原话全文，不传则留空（渲染层退回报告标题）。
        "question": question_text,
        "doc_type": materials_list.get("doc_type", ""),
        "issue_org": materials_list.get("issue_org", ""),
        "publish_date": materials_list.get("publish_date", ""),
        "document_content": body,
        "materials": materials,
        "recalled_materials": recalled,
        # 引用实例全量（逐处 quote）：check_materials 据此做"角标↔原句↔原文片段"三方校验
        "citations": citation_records,
        # 装配所用的合并产物：渲染前的引用门禁据此比对 quote 是否真在该材料原文中
        "merged_json": (str(Path(args.merged_json).expanduser().resolve().relative_to(WS_ROOT))
                        if Path(args.merged_json).expanduser().resolve().is_relative_to(WS_ROOT)
                        else str(Path(args.merged_json).expanduser().resolve())),
        "self_check": self_check,
        # 用户明确字数要求时由素材清单传入（如 {"min": 4000, "max": 5000}）；
        # 未提字数时为空，check_materials 不做篇幅校验。
        "length_target": materials_list.get("length_target"),
        # 逐次调用记录（来自合并产物 search_summary）：过程条按真实调用次数
        # 统计"深度搜索 N 路 / 可信补搜 M 次"，不受同 purpose 分组影响。
        "检索记录": (merged.get("search_summary") or {}).get("searches") or [],
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
        "note": "溯源 JSON 已装配。请把 self_check 五项填成结构化结果（verdict/basis/evidence，pass 必须带可回查证据），再运行 check_materials.py 校验、source_note_html.py 渲染。",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
