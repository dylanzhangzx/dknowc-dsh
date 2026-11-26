#!/usr/bin/env python3
"""多路检索结果合并（法律检索/可信搜索混合输入 → 渲染器统一形态）。

背景：复杂法律问题可能产生多路产物——legal_search.py 的法条模式/语义模式产物
（content.data.检索文章形态）多路，或历史可信搜索产物。渲染脚本 render_trace_html.py
只接受单个 input_json，本脚本把任意多路产物程序化合并为渲染器可直接消费的单 JSON：

- **合并式去重**：按"规范化标题 + 源网址"双键判同一材料——
  标题去空白/全角/开头"关于印发/关于"/结尾公文后缀词；同一材料**合并段落**（段落级
  去重，保留各检索召回的不同段落）与**字段取并集**（保留非空字段、合并搜索条件标记）；
  不再按标题整体丢弃后篇。
- **旧深度产物兼容**：历史 deep_query 的 data.searches[].result + data.common_articles
  仍可摊平为检索文章形态（子查询 query 作为默认搜索条件分组）。
- **policyFiles 收集**：各可信产物携带的 policyFiles 合并去重（writtenText+title 双键），
  写入合并产物 content.data.policyFiles（文号匹配数据源）。
- **分组标签**：每路通过 --search-key 指定该路的搜索条件（核验报告"检索分组 tabs"
  与过程回顾按此分组）；未指定时可信产物默认"本次检索"、深度产物用子查询。
- **显式材料编号**（1.4.0 追加）：合并产物的每篇材料带 `编号` = 它在合并结果中的
  1-based 序号；答案角标 `[n]` 的 n 就用这个编号（渲染器优先读显式编号，不再依赖
  数组位置）。**写答案时读 `编号` 字段，不要按"某一路材料清单里的第几条"编号。**

用法（输出统一写会话 run 目录，不写 Skill 安装目录）：
  python3 scripts/merge_search_results.py \
      --run ./runs/20261120-legal-01 \
      --input route1.json --search-key "政策依据路" \
      --input route2.json --search-key "数据口径路" \
      --output merged_all.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import path_guard

SKILL_ROOT = Path(__file__).resolve().parent.parent
SEARCH_RESULTS_DIR = SKILL_ROOT / "official-docs" / "search-results"  # 历史常量，仅兼容旧引用

# 公文标题前后缀归一（合并去重用）
TITLE_PREFIX = ("关于印发", "关于", "印发", "发布", "印发《")
TITLE_SUFFIX = ("办法的通知", "办法", "实施细则的通知", "实施细则", "意见的通知",
                "意见", "规定的通知", "规定", "公告", "的通知")


def _norm_title(value: Any) -> str:
    """标题归一：全半角/大小写、去空白与书名号，去公文前后缀（变体判同一主体）。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）\"'“”‘’]", "", text)
    text = re.sub(r"\s+", "", text)
    for prefix in TITLE_PREFIX:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for suffix in TITLE_SUFFIX:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _first_value(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _norm_url(raw: Any) -> str:
    """URL 归一（只用于去重键）：去 fragment、常见 tracking 参数、尾斜杠。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return text
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "gclid", "fbclid", "spm", "scm", "from", "share_token", "share_source",
            "ref", "ref_src", "source", "campaign"}
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k.lower() not in drop]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "",
                       urlencode(sorted(query)), ""))


def _is_unofficial(article: Dict[str, Any]) -> bool:
    """非官方判定：外部联网标记或接口数据权威性=非权威。"""
    return bool(article.get("非官方来源") or article.get("待核验") or article.get("pending")) or str(
        article.get("数据权威性") or article.get("authority") or "").strip() in ("非权威", "non-authoritative")


def _dedupe_paragraphs(paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """段落级去重：**按归一化内容判重**，id 仅无语料时兜底，保留顺序。

    1.4.3 修复（WB 实测暴露）：原实现优先按 `id` 判重，而段落实为**篇内局部编号**
    （同一篇材料被多路召回时，各路 id 都从 1 起编）——两路带回的段落只要 id 相同，
    后一路的**不同内容**会被当作重复整段丢弃（静默丢条款，且结果依赖 --input 顺序）。
    实测：杭州门诊待遇条款一度在合并环节丢失，Agent 靠调整 --input 顺序才找回。
    改为内容主键后：多路召回的不同段落全部并集保留，与输入顺序无关、结果可复现。
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for p in paragraphs:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        content = re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or ""))
        key = f"c:{content}" if content else (f"id:{pid}" if pid else "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(p)
    return out


def _merge_article(target: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    """同材料合并：段落并集 + 字段取并集（非空优先）+ 搜索条件合并。"""
    para_key = "段落" if "段落" in target or "段落" in incoming else "paragraphs"
    merged_paras = list(target.get(para_key) or []) + list(incoming.get(para_key) or [])
    target[para_key] = _dedupe_paragraphs(merged_paras)
    for key, value in incoming.items():
        if key in (para_key, "_route_idx", "_para_contrib"):
            continue
        if value not in (None, "", [], {}):
            if key not in target or target[key] in (None, "", [], {}):
                target[key] = value
    for _owner, _cnt in (incoming.get("_para_contrib") or {}).items():
        if isinstance(_owner, int) and isinstance(_cnt, int) and _cnt > 0:
            _tpc = target.setdefault("_para_contrib", {})
            _tpc[_owner] = _tpc.get(_owner, 0) + _cnt
    # 检索通道：不同则顿号拼接保留双通道（2026-10-14 修复——字段并集"非空优先"会让
    # 先入的深搜标签吃掉补搜标签，单条材料的通道归属失真；与句子指纹去重处同款）
    for ch_key in ("检索通道", "channel"):
        cur_ch = str(target.get(ch_key) or "").strip()
        inc_ch = str(incoming.get(ch_key) or "").strip()
        # 按 token（顿号分隔）去重后拼接（2026-10-16 修复）：原用子串判断，
        # "深知可信搜索" 遇 "深知深度搜索、深知可信搜索" 时整串不是子串，会把已含的
        # token 再拼一次，产生 "深知深度搜索、深知深度搜索、深知可信搜索" 这类重复值。
        if inc_ch:
            toks = [t.strip() for t in cur_ch.split("、") if t.strip()]
            for t in inc_ch.split("、"):
                t = t.strip()
                if t and t not in toks:
                    toks.append(t)
            merged_ch = "、".join(toks)
            if merged_ch != cur_ch:
                target[ch_key] = merged_ch
    # 搜索条件（分组标签）：**不拼接**，保留首路标签作为分组归属。
    # 旧实现把两路标签拼成 "上海市落户政策、上海：人才引进申办条件" 这类组合标签，
    # 会把 7 路撑成 10 个分组，过程回顾条的"检索 N 次"随之虚高，材料专库也出现怪分组
    # （2026-09-28 WB 实测：实际 7 路、报告显示 10 次）。并集信息不丢，另存 搜索条件全部。
    for key in ("搜索条件", "search_key"):
        cur = str(target.get(key) or "").strip()
        inc = str(incoming.get(key) or "").strip()
        if not cur:
            if inc:
                target[key] = inc
            continue
        if inc and inc != cur:
            all_key = f"{key}全部"
            vals = list(target.get(all_key) or [cur])
            if inc not in vals:
                vals.append(inc)
            target[all_key] = vals


def _to_article(item: Dict[str, Any], default_key: str = "") -> Dict[str, Any]:
    """把深度产物条目/可信产物条目归一为检索文章字段（渲染器 source_from_article 契约）。"""
    article = {
        "文章标题": _first_value(item, "文章标题", "title", "标题"),
        "数据源": _first_value(item, "数据源", "source"),
        "来源通道": _first_value(item, "来源通道", "source_channel"),
        "来源性质": _first_value(item, "来源性质", "source_nature"),
        "发布日期": _first_value(item, "发布日期", "date"),
        "发布日期可信度": _first_value(item, "发布日期可信度", "date_confidence"),
        "源网址": _first_value(item, "源网址", "url", "原文链接"),
        "段落": item.get("段落") if isinstance(item.get("段落"), list) else
               [{"内容": str(item.get("内容") or item.get("paragraph") or "").strip()}] if (item.get("内容") or item.get("paragraph")) else [],
    }
    for snap_key in ("screenShotPath", "快照链接", "snapshot"):
        snap = _first_value(item, snap_key)
        if snap:
            article["screenShotPath"] = snap
            break
    # 文号键链（2026-10-23）：「发文字号」是 V2 可信路文章级实际键名（policy 路实测返回，
    # 如 商办消费函〔2021〕58号）——缺它则 V2 文号全靠 policyFiles 本地匹配兜底（writtenText
    # 偶发为空，兜底不稳）；`writtenText` 为深搜接口 10-23 新增文章级键（标题命中 policyFiles
    # 才有，部分覆盖）。中文键优先、英文键垫底，全部缺键时行为不变
    if _first_value(item, "文号", "发文字号", "doc_number", "writtenText"):
        article["文号"] = _first_value(item, "文号", "发文字号", "doc_number", "writtenText")
    # 检索通道透传（1.5.0）：检索脚本在产物文章级打的 检索通道 标注，渲染按接口通道拆分计数
    if _first_value(item, "检索通道", "channel"):
        article["检索通道"] = _first_value(item, "检索通道", "channel")
    # 非官方来源透传（1.6.0）：联网路（searchChannel=webSearch）脚本打标 非官方来源=True，
    # 及接口 dataAuthority 返回的 数据权威性（实测联网结果为"非权威"）——渲染层按双口径打徽标
    if item.get("非官方来源"):
        article["非官方来源"] = True
    if _first_value(item, "数据权威性", "authority"):
        article["数据权威性"] = _first_value(item, "数据权威性", "authority")
    if item.get("待核验"):
        article["待核验"] = True
    if item.get("pending"):
        article["pending"] = True
    # 法律场景审计字段透传（2026-11-04）：合并必须保留文章 ID 与选本/版本信息。
    # 否则多路合并后下游按 文章Id 回填版本元数据会 KeyError（WorkBuddy 首测实测），
    # 版本状态/标记/选本依据也会在合并时丢失，报告只能显示“未记录”。
    for _field in (
        "文章Id", "文章类型", "发布或实施机构", "原始标题", "文件标签",
        "生效日期", "版本状态", "版本标记", "版本标记命中", "版本状态存疑",
        "历次版本数", "选本依据", "核验",
    ):
        _value = item.get(_field)
        if _value not in (None, "", [], {}):
            article[_field] = _value
    key = _first_value(item, "搜索条件", "search_key", "deep_group") or default_key
    if key:
        article["搜索条件"] = key
    return article


def _collect_route(input_path: Path, search_key: str,
                   articles: List[Dict[str, Any]], policy_files: List[Dict[str, Any]],
                   route_idx: int = -1) -> None:
    """处理一路输入：可信形态（content.data.检索文章）或深度形态（data.searches）。"""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    policy_holder = data.get("content") if isinstance(data.get("content"), dict) else data
    pf = (policy_holder.get("data") or {}).get("policyFiles") if isinstance(policy_holder.get("data"), dict) else []
    for p in pf or []:
        if isinstance(p, dict):
            policy_files.append(dict(p))

    # 1.5.1 起只处理通用形态（content.data.检索文章）——深度搜索原始产物先经
    # deep_convert.py 转换（接口适配收敛在转换层）；历史深搜形态由转换层前置解决
    search_articles = (policy_holder.get("data") or {}).get("检索文章")
    if isinstance(search_articles, list):
        for item in search_articles:
            if isinstance(item, dict):
                _a = _to_article(item, search_key or "本次检索")
                if route_idx >= 0:
                    _a["_route_idx"] = route_idx  # 每路调用增量统计用（1.6.0），输出前剥离
                articles.append(_a)
        return

    d = data.get("data") if isinstance(data.get("data"), dict) else {}
    if isinstance(d.get("searches"), list):
        raise SystemExit(
            "错误：检测到深度搜索 v3 原始形态（data.searches）——merge 自 1.5.1 起只处理通用形态。"
            "\n请先运行转换层：python3 scripts/deep_convert.py <深搜原始.json>，再把转换产物传给 --input。"
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="多路检索结果合并（可信/深度混合 → 渲染器统一形态）")
    parser.add_argument("--input", action="append", required=True, help="输入 JSON（可多次传入，每路一个）")
    parser.add_argument("--search-key", action="append", help="对应 --input 路次的搜索条件分组标签（可多次；只传 1 个时应用到全部输入；缺省自动）")
    parser.add_argument("--output", "-o", help="输出文件名（落到 --run 目录，默认 merged_all.json）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）")
    args = parser.parse_args()

    if args.search_key and len(args.search_key) not in (1, len(args.input)):
        raise SystemExit("错误：--search-key 数量必须与 --input 一致（或缺省；只传 1 个时应用到全部输入）。")
    if args.search_key and len(args.search_key) == 1 and len(args.input) > 1:
        keys = args.search_key * len(args.input)
    else:
        keys = args.search_key or [""] * len(args.input)

    articles: List[Dict[str, Any]] = []
    policy_files: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    total_in = 0

    for _ri, (input_path_str, key) in enumerate(zip(args.input, keys)):
        # 相对路径按会话 run 目录解析（不再回退 Skill 内 official-docs/）
        try:
            raw_path = path_guard.safe_read_path(input_path_str, args.run)
        except ValueError as exc:
            raise SystemExit(f"错误：{exc}") from None
        before = len(articles)
        _collect_route(raw_path, key, articles, policy_files, route_idx=_ri)
        total_in += len(articles) - before

    # 每路调用增量统计（1.6.0，过程可信度）：该路带来多少篇新材料（new_articles）、
    # 给已有材料补充了多少段（added_paragraphs）——过程条按真实调用次数展示每条补搜的
    # 实际贡献，避免按分组主通道统计时把补搜吞掉（对齐公文写作 3.9.0）。
    call_stats: List[Dict[str, Any]] = [
        {"label": (keys[i] or Path(args.input[i]).name), "file": Path(args.input[i]).name,
         "articles_in": 0, "new_articles": 0, "added_paragraphs": 0}
        for i in range(len(args.input))
    ]

    # 合并式去重
    for art in articles:
        _ri = art.get("_route_idx")
        if isinstance(_ri, int) and 0 <= _ri < len(call_stats):
            call_stats[_ri]["articles_in"] += 1
        title = str(art.get("文章标题") or "").strip()
        url = str(art.get("源网址") or "").strip()
        norm = _norm_title(title)
        url_key = _norm_url(url) if url else ""
        key = f"{norm}|{url_key}" if url_key else norm
        if not key:
            continue
        if key in by_key:
            target = by_key[key]
            target_unofficial = _is_unofficial(target)
            incoming_unofficial = _is_unofficial(art)
            if target_unofficial != incoming_unofficial:
                # 官方 vs 外部：官方记录整体胜出，且与 --input 顺序无关；
                # 不吸收外部段落/数据源/日期/文号/快照/检索通道/分组。
                if not incoming_unofficial:
                    _prev_owner = target.get("_route_idx")
                    if isinstance(_ri, int) and 0 <= _ri < len(call_stats):
                        if (isinstance(_prev_owner, int) and _prev_owner != _ri
                                and 0 <= _prev_owner < len(call_stats)):
                            call_stats[_prev_owner]["new_articles"] = max(
                                0, call_stats[_prev_owner]["new_articles"] - 1)
                        call_stats[_ri]["new_articles"] += 1
                    for _owner, _cnt in (target.get("_para_contrib") or {}).items():
                        if (isinstance(_owner, int) and 0 <= _owner < len(call_stats)
                                and isinstance(_cnt, int) and _cnt > 0):
                            call_stats[_owner]["added_paragraphs"] = max(
                                0, call_stats[_owner]["added_paragraphs"] - _cnt)
                    art["_para_contrib"] = {}
                    by_key[key] = art
                continue
            _before = len(target.get("段落") or [])
            _merge_article(target, art)
            _delta = max(0, len(target.get("段落") or []) - _before)
            if isinstance(_ri, int) and 0 <= _ri < len(call_stats):
                call_stats[_ri]["new_articles"] += 0
                call_stats[_ri]["added_paragraphs"] += _delta
                if _delta > 0:
                    _pc = target.setdefault("_para_contrib", {})
                    _pc[_ri] = _pc.get(_ri, 0) + _delta
        else:
            by_key[key] = art
            if isinstance(_ri, int) and 0 <= _ri < len(call_stats):
                call_stats[_ri]["new_articles"] += 1
    merged = list(by_key.values())

    # —— 近似重复去重（句子指纹，1.5.0）——
    # 搜索接口对同一篇文章常返回多个标题变体条目，上面的"标题+URL"双键去重会漏掉，
    # 表现为知识专库中同一内容出现多张卡：段落完全一致、或分段切法不同顺序略异。
    # 按"句子集合"二次判定：一篇的句子被另一篇覆盖过半（交集≥4句且 inter/min≥0.55）
    # 即判同一材料，保留更完整的一篇（相当时优先发文版标题），段落取并集。
    def _norm_sent(s) -> str:
        return re.sub(r"[\s，,、。；;：:！!？?「」『』“”\"'（）()【】·—\[\]-]", "", str(s or ""))

    def _sentence_fp(article: dict) -> set:
        sents = set()
        for p in (article.get("段落") or []):
            if not isinstance(p, dict):
                continue
            for s in re.split(r"[。；;!？?]", str(p.get("内容") or p.get("content") or "")):
                ns = _norm_sent(s)
                if len(ns) >= 12:
                    sents.add(ns)
        return sents

    def _is_official_title(t: str) -> bool:
        t = t or ""
        return ("关于印发" in t) or t.endswith("的通知") or t.endswith("的公告") or t.endswith("的意见")

    _fps = [_sentence_fp(a) for a in merged]
    _i = 0
    _near_dup = 0
    while _i < len(merged):
        _j = _i + 1
        while _j < len(merged):
            si, sj = _fps[_i], _fps[_j]
            inter = len(si & sj) if (si and sj) else 0
            if inter >= 4 and inter / min(len(si), len(sj)) >= 0.55:
                _i_unofficial = _is_unofficial(merged[_i])
                _j_unofficial = _is_unofficial(merged[_j])
                if _i_unofficial != _j_unofficial:
                    # 官方优先：外部近似重复不得吞掉官方卡，也不把外部段落并进官方卡
                    keep_idx = _j if _i_unofficial else _i
                elif len(si) != len(sj):
                    keep_idx = _i if len(si) > len(sj) else _j
                else:
                    ti = merged[_i].get("文章标题") or ""
                    tj = merged[_j].get("文章标题") or ""
                    keep_idx = _i if (_is_official_title(ti) or not _is_official_title(tj)) else _j
                drop_idx = _j if keep_idx == _i else _i
                keep, drop = merged[keep_idx], merged[drop_idx]
                if _is_unofficial(keep) != _is_unofficial(drop):
                    _drop_owner = drop.get("_route_idx")
                    if (isinstance(_drop_owner, int) and 0 <= _drop_owner < len(call_stats)):
                        call_stats[_drop_owner]["new_articles"] = max(
                            0, call_stats[_drop_owner]["new_articles"] - 1)
                    for _owner, _cnt in (drop.get("_para_contrib") or {}).items():
                        if (isinstance(_owner, int) and 0 <= _owner < len(call_stats)
                                and isinstance(_cnt, int) and _cnt > 0):
                            call_stats[_owner]["added_paragraphs"] = max(
                                0, call_stats[_owner]["added_paragraphs"] - _cnt)
                    merged.pop(drop_idx)
                    _fps.pop(drop_idx)
                    _near_dup += 1
                    if drop_idx == _i:
                        _j = _i + 1
                    continue
                # 同权威近似重复：被并卡不再是独立材料，所属路次 new_articles 回滚 -1；
                # 被并卡的段落贡献并入保留卡，便于后续若保留卡被丢弃时完整回滚。
                _drop_owner = drop.get("_route_idx")
                if isinstance(_drop_owner, int) and 0 <= _drop_owner < len(call_stats):
                    call_stats[_drop_owner]["new_articles"] = max(
                        0, call_stats[_drop_owner]["new_articles"] - 1)
                for _owner, _cnt in (drop.get("_para_contrib") or {}).items():
                    if isinstance(_owner, int) and isinstance(_cnt, int) and _cnt > 0:
                        _kpc = keep.setdefault("_para_contrib", {})
                        _kpc[_owner] = _kpc.get(_owner, 0) + _cnt
                # 段落取并集（内容级去重；后续统一编号）
                _seen_para = {re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or ""))
                              for p in (keep.get("段落") or [])}
                for p in (drop.get("段落") or []):
                    pc = re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or ""))
                    if pc and pc not in _seen_para:
                        _seen_para.add(pc)
                        keep.setdefault("段落", []).append(p)
                # 字段取并集：保留篇空字段用被并篇补；检索通道不同则拼接保留双通道
                for f, v in drop.items():
                    if f in ("段落", "_route_idx", "_para_contrib"):
                        continue
                    if not keep.get(f) and v:
                        keep[f] = v
                # 通道拼接同款 token 去重（2026-10-16，与字段并集处同口径）
                _inc = (drop.get("检索通道") or "").strip()
                if _inc:
                    _toks = [t.strip() for t in (keep.get("检索通道") or "").split("、") if t.strip()]
                    for _t in _inc.split("、"):
                        _t = _t.strip()
                        if _t and _t not in _toks:
                            _toks.append(_t)
                    _merged = "、".join(_toks)
                    if _merged != (keep.get("检索通道") or ""):
                        keep["检索通道"] = _merged
                merged.pop(drop_idx)
                _fps.pop(drop_idx)
                _near_dup += 1
                if drop_idx == _i:
                    _j = _i + 1  # _i 处已换成保留篇，重新向后比较
                continue
            _j += 1
        _i += 1

    # —— 段内污染段去重（1.5.0，修"一张卡里两段内容一样"）——
    # ① 内容完全一致 → 保留先出现的；
    # ② "标题链拼进正文"的污染段——接口偶发把段落标题/上级标题文字拼进内容开头，
    #    形成 内容=标题前缀+另一段内容 的超集段（渲染剥前缀后两段看起来完全一样）。
    #    判定：归一化后一段是另一段的前缀或后缀超集（短段≥30字）→ 丢弃污染长段、保留干净段。
    for article in merged:
        paras = article.get("段落") or []
        # 归一化加强（2026-11-05，T5 实测）：旧版只去空白，法条模式与语义模式两份副本
        # 全半角标点不一（"(一);"vs"（一）；"）时同一条文比不相等、双份并存。改为去全部
        # 空白与标点（只留字词与数字）再比对。
        def _hard(t) -> str:
            return re.sub(r"[\W_]+", "", str(t or ""))

        texts = [_hard(p.get("内容") or p.get("content")) for p in paras]
        # 同条号旧版混入（2026-11-05）：语义召回的旧版条文段（如 2004 版条例第十四条）与
        # 选本器选定的现行版并存一卡。标题尾级同为"第X条"的段落只保留最长的一段。
        art_of = []
        for p in paras:
            m = re.search(r"第[零一二三四五六七八九十百千〇]+条", str(p.get("标题") or "").split(">")[-1])
            art_of.append(m.group(0) if m else "")
        drop_set = set()
        for a in range(len(paras)):
            ta = texts[a]
            if len(ta) < 30 or a in drop_set:
                continue
            for b in range(len(paras)):
                tb = texts[b]
                if a == b or b in drop_set or len(tb) < 30:
                    continue
                if ta == tb:
                    if a < b:
                        drop_set.add(b)      # 完全一致：保留先出现的
                    continue
                if art_of[a] and art_of[a] == art_of[b]:
                    # 同条号两份（跨版本/截断）：留内容更长的
                    drop_set.add(a if len(ta) < len(tb) else b)
                    continue
                if tb.startswith(ta) or tb.endswith(ta):
                    drop_set.add(b)          # b 是带标题前缀的污染超集段
                elif ta.startswith(tb) or ta.endswith(tb):
                    drop_set.add(a)          # a 才是污染段
        if drop_set:
            article["段落"] = [p for i, p in enumerate(paras) if i not in drop_set]

    # 清理内部字段：_route_idx 只用于合并期统计，不进入交付 JSON
    for _art in merged:
        _art.pop("_route_idx", None)
        _art.pop("_para_contrib", None)

    # 显式材料编号（1.4.0）：给每篇材料盖上 `编号` = 它在合并产物中的 1-based 序号。
    # 渲染器优先读材料上的显式编号（render_trace_html.source_from_article 的 explicit_id），
    # 答案角标 [n] 因此锚定在一个"读得到"的编号上，不必让模型去数数组位置——
    # 多路合并后总序号与各路内部的相对编号不同（实测：WorkBuddy 需反复确认才敢写），
    # 数错会静默绑到另一份材料且核验单不会报警，故改为显式锚点。
    for _idx, _art in enumerate(merged, start=1):
        _art["编号"] = _idx
        # 旧版标注（1.0.4 随上游内核迁移，从渲染器移到合并层）：接口给了失效日期且已过期的
        # 材料，在"核验"说明前置"旧版 · 失效于…"——上游材料卡不再有独立失效字段，
        # 该说明经 build_report_input 映射为材料"核验"说明，卡片如实展示。
        _expired = str(_art.get("失效日期") or _art.get("expired_at") or "").strip()
        # 生效时间显式化（律所反馈场景六 P0：引用要能核验"生效时间"）：接口给了生效日期
        # 而核验说明未提及的，把"生效于 X"并入材料核验说明，卡片如实展示。
        _eff = str(_art.get("生效日期") or _art.get("effectiveDate") or "").strip()
        if _eff and _eff not in str(_art.get("核验") or ""):
            _prev = str(_art.get("核验") or "").strip()
            _art["核验"] = ("生效于 " + _eff + ("；" + _prev if _prev else ""))
        if _expired:
            import re as _re
            _m = _re.search(r"(\d{4})[年./-]?(\d{1,2})?[月./-]?(\d{1,2})?", _expired)
            if _m:
                _note = f"旧版 · 失效于 {_expired}"
                _prev = str(_art.get("核验") or "").strip()
                _art["核验"] = (_note + ("；" + _prev if _prev else ""))

    # policyFiles 收集去重（writtenText+title 双键）
    pf_seen: set = set()
    pf_out: List[Dict[str, Any]] = []
    for p in policy_files:
        w = str(p.get("writtenText") or p.get("发文字号") or "").strip()
        t = str(p.get("title") or p.get("标题") or "").strip()
        if not w and not t:
            continue
        pf_key = f"{w}|{t}"
        if pf_key in pf_seen:
            continue
        pf_seen.add(pf_key)
        pf_out.append(p)

    out_name = args.output or "merged_all.json"
    try:
        out = path_guard.safe_write_path(out_name, args.run)
        path_guard.refuse_existing(out, kind="输出")
    except ValueError as exc:
        raise SystemExit(f"错误：{exc}") from None

    result = {
        "search_meta": {"merged": True, "input_routes": len(args.input), "merged_from": [str(Path(x).name) for x in args.input]},
        "content": {"data": {"检索文章": merged, "policyFiles": pf_out}},
    }

    # 材料池清单（1.4.3 证据侧覆盖）：写答案大纲前先扫描——识别与用户情形相关、
    # 但问题字面未覆盖的主题。清单 = 机构分布 + 文号 + 涉及金额 + 全量标题，
    # 同时写入 search_meta.pool_summary（供程序复用）并打印到 stdout（供 Agent 扫描）。
    def _art_org(a: Dict[str, Any]) -> str:
        # 机构分布按发文机关统计（2026-11-13 统一口径）；数据源只是抓取站点，不作机构。
        return str(a.get("发布或实施机构") or a.get("发布机关") or "").strip() or "（未标注机构）"

    org_counts: Dict[str, int] = {}
    for a in merged:
        key = _art_org(a)[:24]
        org_counts[key] = org_counts.get(key, 0) + 1
    doc_numbers: List[str] = []
    for p in pf_out:
        w = str(p.get("writtenText") or "").strip()
        if w and w not in doc_numbers:
            doc_numbers.append(w)
    amounts: List[str] = []
    for a in merged:
        for seg in (a.get("段落") or []):
            if not isinstance(seg, dict):
                continue
            for m2 in re.finditer(r"\d+(?:\.\d+)?(?:\s*[万亿])?元", str(seg.get("内容") or "")):
                v = m2.group(0)
                if v not in amounts:
                    amounts.append(v)
        if len(amounts) >= 30:
            break
    pool_summary = {
        "articles": len(merged),
        "orgs": dict(sorted(org_counts.items(), key=lambda kv: -kv[1])[:20]),
        "doc_numbers": doc_numbers[:40],
        "amounts": amounts[:30],
        "titles": [
            {"编号": a.get("编号", i + 1), "标题": str(a.get("文章标题") or "")[:60],
             "机构": _art_org(a)[:24], "日期": str(a.get("发布日期") or "")[:10],
             # 摘要 = 首个非空段落前 60 字：主题藏在正文里（标题看不出）的材料同样能被扫到
             "摘要": next((re.sub(r"\s+", " ", str(seg.get("内容") or "")).strip()[:60]
                           for seg in (a.get("段落") or [])
                           if isinstance(seg, dict) and str(seg.get("内容") or "").strip()), "")}
            for i, a in enumerate(merged)
        ],
    }
    result["search_meta"]["pool_summary"] = pool_summary
    # 每路调用增量（1.6.0）：渲染过程条按真实调用次数展示每条补搜的实际贡献
    result["search_meta"]["calls"] = call_stats

    # official-docs/ 不随发布包携带（平台不接受 .gitkeep，目录由脚本运行期自动创建）
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 合并完成：{len(args.input)} 路 / 输入 {total_in} 篇 → 合并去重后 {len(merged)} 篇"
          f"（policyFiles {len(pf_out)} 条）→ {out}")
    print("  合并产物与 legal_search.py 单路输出同构，可直接作为 render_trace_html.py 的 input_json。")
    print("── 每路调用增量（过程可信度：该路新增 N 篇 · 为已有材料补充 K 段）──")
    for _c in call_stats:
        print(f"    · {_c['label']}：输入 {_c['articles_in']} 篇 → 新增 {_c['new_articles']} 篇 · 补充 {_c['added_paragraphs']} 段")
    print("── 材料池清单（证据侧覆盖：写答案大纲前先扫描，识别与用户情形相关、但问题字面未覆盖的主题）──")
    print("  机构分布：" + "；".join(f"{k}×{v}" for k, v in list(pool_summary["orgs"].items())[:12]))
    if doc_numbers:
        print(f"  文号 {len(doc_numbers)} 个：{'、'.join(doc_numbers[:12])}{'…' if len(doc_numbers) > 12 else ''}")
    if amounts:
        print("  涉及金额样例：" + "、".join(amounts[:15]))
    print(f"  标题清单（{len(merged)} 篇；含首段摘要，便于识别标题看不出的主题）：")
    for t in pool_summary["titles"]:
        line = f"    {t['编号']:>3}. {t['标题']}｜{t['机构']}｜{t['日期']}"
        if t.get("摘要"):
            line += f"｜{t['摘要']}"
        print(line)


if __name__ == "__main__":
    main()
