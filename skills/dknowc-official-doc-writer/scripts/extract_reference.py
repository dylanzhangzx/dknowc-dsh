#!/usr/bin/env python3
"""从 `dkag_search.py --full` 全文召回结果中提取「目标范文」单篇全文并落盘。

背景（3.7.5）：`--full` 会一次返回**全部命中篇**的全文（实测同一标题 20 篇、合计
52,886 字 / 263KB，是不带 `--full` 的 6.4 倍）。若把整个返回当作"参考范文"留存，
本地会堆入大量无关篇目，且模型需自行在对话里挑拣（易丢失、易挑错）。本脚本按
**标题精确匹配**只提取目标那一篇，写入单文件，确保本地只留目标的单篇全文。

匹配规则（与检索习惯一致）：
  按返回顺序逐篇比对文章标题与目标标题（去空格/全角空格归一），**命中第一篇即取**
  （即"先看第一篇是不是要找的，不是再看下一篇"）；精确匹配失败时依次尝试
  去公文缀词后的归一匹配，并在结果中如实标注匹配方式 match=exact|normalized。

用法：
  python3 scripts/extract_reference.py <full结果JSON> --title "<目标文章标题>" [--task "<任务名>"]
  python3 scripts/extract_reference.py <full结果JSON> --list          # 只列出返回的候选篇目标题

输出：
  参考范文 Markdown（默认 official-docs/input/参考范文_<任务名>.md）
  stdout 输出 JSON：{ok, matched, match, title, source_url, date, chars, output}

说明：本脚本只提取目标篇；`--full` 的全量返回仅作本次提取的输入，不作为参考范文留存。
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

# 文章列表可能出现的路径（不加 --clean 的原始结构 / 兼容其他同构结构）
ARTICLE_PATHS = (
    ("content", "data", "检索文章"),
    ("content", "data", "articles"),
    ("data", "common_articles"),
    ("data", "检索文章"),
    ("articles",),
    ("检索文章",),
)
# 全文字段候选
FULL_FIELDS = ("全文", "fullContent", "full_content", "全文内容")
TITLE_FIELDS = ("文章标题", "标题", "title")
URL_FIELDS = ("源网址", "原文链接", "sourceUrl", "source_url", "url")
DATE_FIELDS = ("发布日期", "createDate", "日期", "date")
SOURCE_FIELDS = ("数据源", "来源", "source")


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"错误：无法读取 {path}（{exc}）")


def first_value(d: dict, keys: tuple) -> str:
    for k in keys:
        v = d.get(k)
        if v:
            return str(v).strip()
    return ""


def pick_articles(data) -> list:
    """按兼容路径取文章列表，返回非空的第一组。"""
    for path in ARTICLE_PATHS:
        cur = data
        ok = True
        for seg in path:
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
            else:
                ok = False
                break
        if ok and isinstance(cur, list) and cur:
            return cur
    return []


def norm_exact(s: str) -> str:
    """精确匹配用的归一：仅去空白（含全角空格），不改动其他字符。"""
    return re.sub(r"[\s　]+", "", str(s or ""))


def norm_loose(s: str) -> str:
    """宽松匹配用的归一：去空白 + 去书名号/引号等引用标记 + 去发文机关前缀 + 去结尾公文缀词。

    例："深圳市交通运输局关于印发《X办法》的通知" 与 "《X办法》"
    归一后同为 "X办法"，可命中标题简称/全称、带不带书名号混用的情况。

    **书名号必须先去掉**（2026-09-29 修复）：否则
    "关于本市贯彻实施《上海市优化营商环境条例》情况的报告" 归一后仍保留连续子串
    "上海市优化营商环境条例"，与法规正文标题《上海市优化营商环境条例》构成包含关系，
    被误判为同一篇——实测把"报告"匹配成了"条例"本身，文种完全不同。
    """
    t = norm_exact(s)
    t = re.sub(r"[《》〈〉“”‘’\"'（）()\[\]【】]", "", t)
    t = re.sub(r"^.*?(关于印发|关于)", "", t)  # 去"发文机关 + 关于印发/关于"
    t = re.sub(r"(的通知|的公告|的意见|的方案|的办法|的规定|的细则|的批复|的规划|的纲要|的通报|的决定|的报告)$", "", t)
    return t


def safe_name(s: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "_", str(s or "")).strip("_")
    return s[:60] or "参考范文"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="从 --full 结果中提取目标范文单篇全文")
    parser.add_argument("full_json", help="dkag_search.py --full 的结果 JSON")
    parser.add_argument("--title", help="目标文章标题（与返回中某篇完全一致）")
    parser.add_argument("--task", default="", help="任务名（用于输出文件名）")
    parser.add_argument("--output", "-o", help="输出 Markdown 文件名（默认 official-docs/input/参考范文_<任务>.md）")
    parser.add_argument("--list", action="store_true", help="只列出返回的候选篇目标题，不提取")
    args = parser.parse_args()

    data = load_json(Path(args.full_json).expanduser())
    articles = pick_articles(data)
    if not articles:
        print(json.dumps({"ok": False, "error": "未在结果中找到文章列表（路径不匹配或结果为空）"},
                         ensure_ascii=False, indent=2))
        return 1

    if args.list:
        rows = []
        for i, a in enumerate(articles, 1):
            if not isinstance(a, dict):
                continue
            full = next((a.get(f) for f in FULL_FIELDS if isinstance(a.get(f), str) and a.get(f)), "")
            rows.append({"no": i, "title": first_value(a, TITLE_FIELDS),
                         "has_fulltext": bool(full), "chars": len(full)})
        print(json.dumps({"ok": True, "total": len(rows), "articles": rows}, ensure_ascii=False, indent=2))
        return 0

    if not args.title:
        raise SystemExit("错误：未提供 --title（目标文章标题）；可先用 --list 查看候选篇目标题")

    target_exact, target_loose = norm_exact(args.title), norm_loose(args.title)
    hit = None
    match_kind = ""
    for a in articles:  # 按返回顺序，逐篇比对，命中第一篇即取
        if not isinstance(a, dict):
            continue
        title = first_value(a, TITLE_FIELDS)
        if norm_exact(title) == target_exact:
            hit, match_kind = a, "exact"
            break
        if hit is None:
            loose = norm_loose(title)
            if target_loose and loose == target_loose:
                hit, match_kind = a, "normalized"  # 记录归一命中，继续找是否还有精确命中
            elif target_loose and len(target_loose) >= 8 and target_loose in loose:
                # 只保留「返回篇标题包含目标标题」这一方向：如目标是《X办法》、返回篇是
                # "XX局关于印发《X办法》的通知"，多出的部分应只是发文机关或公文缀词，故限制
                # 长度差；反方向（候选是目标的子串，如候选《X条例》被目标
                # "关于实施《X条例》情况的报告"包含）已证实会把不同文种判为同一篇，
                # 不再命中（2026-09-29 修复）。
                if len(loose) - len(target_loose) <= 24:
                    hit, match_kind = a, "contains"
    if hit is None:
        # 标题相近但被判定为不同篇目的候选单列出来：让调用方看清"为什么不匹配"，
        # 而不是把一篇文种不同的文章当成参考范文（2026-09-29 修复）。
        similar = []
        for a in articles:
            if not isinstance(a, dict):
                continue
            t = first_value(a, TITLE_FIELDS)
            lt = norm_loose(t)
            if target_loose and lt and (target_loose in lt or lt in target_loose):
                similar.append(t)
        print(json.dumps({
            "ok": False,
            "error": "未找到与目标标题匹配的文章（已按返回顺序逐篇比对；标题相近但判定为不同篇目的已排除）",
            "target": args.title,
            "similar_but_excluded": similar[:8],
            "available_titles": [first_value(a, TITLE_FIELDS) for a in articles if isinstance(a, dict)][:30],
            "note": "similar_but_excluded 是与目标标题相近、但篇目或文种不同的候选，不得直接当作参考范文；"
                    "如确认其中某篇就是目标，请用该篇完整标题重新传入 --title。",
        }, ensure_ascii=False, indent=2))
        return 1

    full_text = next((hit.get(f) for f in FULL_FIELDS if isinstance(hit.get(f), str) and hit.get(f)), "")
    if not full_text:
        print(json.dumps({
            "ok": False,
            "error": "目标文章已匹配但无全文内容（确认调用时带了 --full 且未加 --clean）",
            "title": first_value(hit, TITLE_FIELDS),
        }, ensure_ascii=False, indent=2))
        return 1

    title = first_value(hit, TITLE_FIELDS)
    url = first_value(hit, URL_FIELDS)
    date = first_value(hit, DATE_FIELDS)
    source = first_value(hit, SOURCE_FIELDS)

    out_path = args.output
    if not out_path:
        base = safe_name(args.task or title)
        out_path = f"参考范文_{base}.md"
    output = Path(out_path).expanduser()
    if not output.is_absolute():
        output = (INPUT_DIR / output.name).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    md = [f"# 参考范文：{title}", ""]
    meta = " ".join(v for v in [f"来源：{source}" if source else "", f"日期：{date}" if date else ""] if v)
    if meta:
        md += [f"> {meta}", ""]
    if url:
        md += [f"> 原文：{url}", ""]
    md += [f"> 全文约 {len(full_text)} 字（单篇提取，作为写作结构与表达参考，不进入溯源核验报告）", "", "---", "", full_text.strip(), ""]
    output.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "matched": True,
        "match": match_kind,
        "title": title,
        "source": source,
        "date": date,
        "source_url": url,
        "chars": len(full_text),
        "output": str(output.relative_to(SKILL_ROOT)) if output.is_relative_to(SKILL_ROOT) else str(output),
        "note": "已提取目标范文单篇全文；--full 的全量返回仅作输入，不作为参考范文留存。",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
