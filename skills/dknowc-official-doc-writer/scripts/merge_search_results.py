#!/usr/bin/env python3
"""
合并多次搜索结果
功能：去重、重新编号、生成统计信息
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict

SKILL_ROOT = Path(__file__).resolve().parent.parent
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 cwd（SkillHub 兼容）
import os as _os
_ws = _os.environ.get("DKNWOC_WS_ROOT")
if not _ws:
    # dsh 会话隔离：每会话独立产物目录 <工作区>/dknowc-output/<DSH_SESSION_ID前8位>/，
    # 多会话共用同一工作区时互不混杂；非 dsh 环境回退为工作区本身。
    _sid = _os.environ.get("DSH_SESSION_ID", "")
    _ws = str(Path(_os.getcwd()) / "dknowc-output" / (_sid[:8] if _sid else "_default"))
WS_ROOT = Path(_ws).resolve()
OFFICIAL_DOCS_DIR = WS_ROOT / "official-docs"
SEARCH_RESULTS_DIR = OFFICIAL_DOCS_DIR / "search-results"
ALLOWED_INPUT_DIRS = (
    OFFICIAL_DOCS_DIR / "input",
    OFFICIAL_DOCS_DIR / "output",
    SEARCH_RESULTS_DIR,
)


def is_relative_to(path: Path, parent: Path) -> bool:
    """兼容旧 Python 版本的 Path.is_relative_to。"""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_input_json(file_path: str) -> Path:
    """只允许读取 skill 工作目录内的 JSON 搜索结果。"""
    raw_path = Path(file_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = (SKILL_ROOT / raw_path).resolve()

    if resolved.suffix.lower() != ".json":
        raise ValueError(f"只允许读取 JSON 文件: {file_path}")
    if not any(is_relative_to(resolved, allowed.resolve()) for allowed in ALLOWED_INPUT_DIRS):
        raise ValueError(f"输入文件必须位于 skill 工作目录内: {file_path}")
    return resolved


def resolve_output_json(output_path: str) -> Path:
    """只允许将合并结果写入搜索结果目录。"""
    raw_path = Path(output_path).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    elif raw_path.parent == Path("."):
        resolved = (SEARCH_RESULTS_DIR / raw_path.name).resolve()
    else:
        resolved = (SKILL_ROOT / raw_path).resolve()

    if resolved.suffix.lower() != ".json":
        resolved = resolved.with_suffix(".json")
    if not is_relative_to(resolved, SEARCH_RESULTS_DIR.resolve()):
        raise ValueError(f"输出文件必须位于搜索结果目录内: {SEARCH_RESULTS_DIR}")
    return resolved


def merge_results(result_files: List[str]) -> Dict:
    """
    合并多个搜索结果文件
    
    Args:
        result_files: 搜索结果文件路径列表
        
    Returns:
        合并后的结果字典
    """
    all_articles = []
    seen_titles = set()
    by_key = {}
    duplicates_count = 0
    regions_searched = []
    searches = []
    knowledge_bases = []
    all_policy_files = []
    seen_policies = set()
    
    for file_path in result_files:
        try:
            safe_file_path = resolve_input_json(file_path)
            with safe_file_path.open('r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"警告: 无法读取文件 {file_path}: {e}", file=sys.stderr)
            continue
        
        # 检查是否是清洗后的格式
        if data.get("cleaned") and "articles" in data:
            articles = data["articles"]
        elif "content" in data and "data" in data.get("content", {}):
            articles = data["content"]["data"].get("检索文章", [])
        else:
            print(f"警告: 文件 {file_path} 格式不识别", file=sys.stderr)
            continue
        
        search_meta = data.get("search_meta", {})
        region = search_meta.get("area") or infer_region_from_filename(str(safe_file_path))
        regions_searched.append(region)
        # 本文件处理前的文章/段落基线：用于计算每次调用真实新增量
        before_article_count = len(all_articles)
        before_para_total = sum(len(a.get("段落") or []) for a in all_articles)
        # 搜索目的兜底（3.7.6 修复）：该路 --purpose 为空时用该路 query 兜底——
        # 若留空，文章"搜索目的"缺失，溯源报告分组键（search_key）会退化成
        # "中国"/"浙江省"等地域碎片，材料面板筛选胶囊失去意义（避免大量篇目退化）。
        purpose_val = search_meta.get("purpose") or search_meta.get("query") or ""
        record = {
            "file": str(safe_file_path),
            "query": search_meta.get("query", ""),
            "purpose": purpose_val,
            "area": region,
            "time": search_meta.get("time", ""),
            "policy": search_meta.get("policy", False),
            "full": search_meta.get("full", False),
            "segmentCount": search_meta.get("segmentCount"),
            "knowledgeBase": data.get("knowledgeBase", ""),
            # 调用通道：深搜转换产物自带 channel=deep；补搜文件按文件名区分（deep_* vs 其他）
            "channel": ("深知深度搜索"
                        if (data.get("channel") == "deep"
                            or Path(str(safe_file_path)).name.startswith("deep_"))
                        else "深知可信搜索"),
        }
        searches.append(record)
        if data.get("knowledgeBase"):
            knowledge_bases.append({
                "file": str(safe_file_path),
                "query": search_meta.get("query", ""),
                "purpose": purpose_val,
                "area": region,
                "knowledgeBase": data.get("knowledgeBase", ""),
            })
        
        # 规范性文件清单（policyFiles，含发文字号）：可信搜索补搜产物携带，
        # 是溯源核验报告匹配"文号"的唯一来源，合并时必须带下去（此前被整体丢弃，
        # 导致合并产物 policyFiles 恒为空、政策文件无法显示发文字号）。
        for pf in (data.get("policyFiles") or []):
            if not isinstance(pf, dict):
                continue
            key = (pf.get("writtenText") or "", pf.get("title") or "")
            if key in seen_policies:
                continue
            seen_policies.add(key)
            all_policy_files.append(pf)
        
        # 去重合并（3.7.5 修复：合并式去重，禁止按标题整体丢弃后篇）
        # 同一材料多次搜索返回时，标题相同但召回段落可能不同（各次搜索命中不同相关段落）——
        # 按标题丢弃会丢掉其他搜索带来的段落；标题微小差异（空格/全半角/赘词）又可能漏去重。
        # 正确做法：按"规范化标题 + 源网址"双键判同一材料，同一材料合并段落、字段取并集。
        for article in articles:
            title = article.get("文章标题", "")
            url = article.get("源网址") or article.get("sourceUrl") or article.get("原文链接") or ""
            # 规范化标题：去空白、全角转半角、去公文开头（关于印发/关于）与结尾赘词后缀，
            # 使"…管理办法" / "…管理办法的通知" / "关于印发…管理办法的通知" 判为同一材料（去重键，不改原文）
            title_key = re.sub(r"\s+", "", title or "").replace("　", "")
            title_key = re.sub(r"^(关于印发|关于)", "", title_key)
            title_key = re.sub(r"(的通知|的公告|的意见|的方案|的办法|的规定|的细则|的批复|的规划|的纲要)$", "", title_key)
            url_key = re.sub(r"\s+", "", url or "").rstrip("/")
            key = title_key if title_key else url_key
            if not key:
                all_articles.append(article)
                continue

            if key in seen_titles:
                # 同一材料：合并段落（保留两篇的段落合集，段落级去重），字段取并集（保留非空者）
                duplicates_count += 1
                existing = by_key[key]
                # 合并段落：按内容去重合并，保留各自 id（后续统一重编号）
                seen_para = set()
                merged_paras = list(existing.get("段落") or [])
                for p in merged_paras:
                    pc = p.get("内容") or p.get("content") or ""
                    if pc:
                        seen_para.add(re.sub(r"\s+", "", str(pc)))
                for p in (article.get("段落") or []):
                    pc = p.get("内容") or p.get("content") or ""
                    if pc and re.sub(r"\s+", "", str(pc)) not in seen_para:
                        merged_paras.append(p)
                existing["段落"] = merged_paras
                # 字段取并集：已有字段非空则保留，空字段用后篇补
                for f, v in article.items():
                    if f == "段落":
                        continue
                    if not existing.get(f) and v:
                        existing[f] = v
                # 追加本次搜索的来源标记（搜索地域/搜索词/搜索目的）
                if region and region not in (existing.get("搜索地域") or ""):
                    existing["搜索地域"] = (existing.get("搜索地域") or "") + (("、" + region) if existing.get("搜索地域") else region)
                # 检索通道：两接口召回同一材料时拼接保留双通道（去重逻辑——
                # 原按"字段非空保留先入"会让深搜标签覆盖补搜标签，补搜召回的标准在
                # 报告材料级被误标为仅"深知深度搜索"）
                if (article.get("检索通道") or "") and article["检索通道"] not in (existing.get("检索通道") or ""):
                    existing["检索通道"] = (existing.get("检索通道") or "") + (("、" + article["检索通道"]) if existing.get("检索通道") else article["检索通道"])
                if search_meta.get("query") and not existing.get("搜索词"):
                    existing["搜索词"] = search_meta.get("query")
                if purpose_val and not existing.get("搜索目的"):
                    existing["搜索目的"] = purpose_val
                continue

            seen_titles.add(key)
            by_key[key] = article
            article.setdefault("搜索地域", region)
            if search_meta.get("query"):
                article.setdefault("搜索词", search_meta.get("query"))
            if purpose_val:
                article.setdefault("搜索目的", purpose_val)
            if article.get("源网址") and not article.get("原文链接"):
                article["原文链接"] = article["源网址"]
            if article.get("sourceUrl") and not article.get("原文链接"):
                article["原文链接"] = article["sourceUrl"]
            if article.get("policyUrl") and not article.get("知识专库原文"):
                article["知识专库原文"] = article["policyUrl"]
            all_articles.append(article)

        # 每次调用的真实增量：新增文章数 / 新增段落数（含新文章自带段落）。
        # 补搜的价值主要看这两个数：新增 0 篇但补充 N 段，说明补的是已有文章的条款段落。
        record["new_articles"] = len(all_articles) - before_article_count
        record["added_paragraphs"] = (
            sum(len(a.get("段落") or []) for a in all_articles) - before_para_total
        )

    # —— 近似重复去重（句子指纹，用于处理段落重复问题）——
    # 搜索接口对同一篇文章常返回多个标题变体条目（如"北京出台智能体专项政策"与
    # "…专项政策 最高支持1亿元"），上面的标题去重会漏掉，表现为知识专库中同一内容
    # 出现多张卡：段落完全一致、或分段切法不同导致顺序略不同。此处按"句子集合"二次
    # 判定：一篇的句子被另一篇覆盖过半即判同一材料，保留更完整的一篇，段落取并集。
    def _norm_sent(s) -> str:
        return re.sub(r"[\s，,、。；;：:！!？?「」『』“”\"'（）()\[\]【】·—\-]", "", str(s or ""))

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

    fps = [_sentence_fp(a) for a in all_articles]
    _i = 0
    while _i < len(all_articles):
        _j = _i + 1
        while _j < len(all_articles):
            si, sj = fps[_i], fps[_j]
            inter = len(si & sj) if (si and sj) else 0
            if inter >= 4 and inter / min(len(si), len(sj)) >= 0.55:
                # 保留更完整（句子更多）的一篇；相当时优先"发文版"标题，再相当保留先入篇
                if len(si) != len(sj):
                    keep_idx = _i if len(si) > len(sj) else _j
                else:
                    ti = all_articles[_i].get("文章标题") or ""
                    tj = all_articles[_j].get("文章标题") or ""
                    keep_idx = _i if (_is_official_title(ti) or not _is_official_title(tj)) else _j
                drop_idx = _j if keep_idx == _i else _i
                keep, drop = all_articles[keep_idx], all_articles[drop_idx]
                # 段落取并集（内容级去重，保留各自 id；后续统一重编号）
                _seen_para = {re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or ""))
                              for p in (keep.get("段落") or [])}
                for p in (drop.get("段落") or []):
                    pc = re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or ""))
                    if pc and pc not in _seen_para:
                        _seen_para.add(pc)
                        keep.setdefault("段落", []).append(p)
                # 字段取并集：保留篇空字段用被并篇补
                for f, v in drop.items():
                    if f == "段落":
                        continue
                    if not keep.get(f) and v:
                        keep[f] = v
                # 检索通道：不同则拼接保留双通道（同上方同名键去重逻辑）
                if (drop.get("检索通道") or "") and drop["检索通道"] not in (keep.get("检索通道") or ""):
                    keep["检索通道"] = (keep.get("检索通道") or "") + (("、" + drop["检索通道"]) if keep.get("检索通道") else drop["检索通道"])
                if (drop.get("搜索地域") or "") and drop["搜索地域"] not in (keep.get("搜索地域") or ""):
                    keep["搜索地域"] = (keep.get("搜索地域") or "") + (("、" + drop["搜索地域"]) if keep.get("搜索地域") else drop["搜索地域"])
                all_articles.pop(drop_idx)
                fps.pop(drop_idx)
                duplicates_count += 1
                if drop_idx == _i:
                    _j = _i + 1  # _i 处已换成保留篇，重新向后比较
                continue
            _j += 1
        _i += 1

    # 段内重复段去重（用于处理一张卡里两段内容一样的问题）：
    # ① 内容完全一致 → 保留先出现的；
    # ② "标题链拼进正文"的污染段——接口偶发把段落标题/上级标题文字拼进内容开头，
    #    形成 内容=标题前缀+另一段内容 的超集段（渲染剥前缀后两段看起来完全一样）。
    #    判定：归一化后一段是另一段的前缀或后缀超集（短段≥30字）→ 丢弃污染的长段、保留干净段。
    for article in all_articles:
        paras = article.get("段落") or []
        texts = [re.sub(r"\s+", "", str(p.get("内容") or p.get("content") or "")) for p in paras]
        drop = set()
        for a in range(len(paras)):
            ta = texts[a]
            if len(ta) < 30 or a in drop:
                continue
            for b in range(len(paras)):
                tb = texts[b]
                if a == b or b in drop or len(tb) < 30:
                    continue
                if ta == tb:
                    if a < b:
                        drop.add(b)      # 完全一致：保留先出现的
                elif tb.startswith(ta) or tb.endswith(ta):
                    drop.add(b)          # b 是带标题前缀的污染超集段
                elif ta.startswith(tb) or ta.endswith(tb):
                    drop.add(a)          # a 才是污染段
        if drop:
            article["段落"] = [p for i, p in enumerate(paras) if i not in drop]

    # 重新编号段落
    global_id = 1
    total_paragraphs = 0
    for article in all_articles:
        paragraphs = article.get("段落", [])
        for p in paragraphs:
            p["id"] = global_id
            global_id += 1
            total_paragraphs += 1
    
    # 返回合并结果
    return {
        "cleaned": True,
        "articles": all_articles,
        "policyFiles": all_policy_files,
        "search_summary": {
            "total_searches": len(result_files),
            "regions": list(set(regions_searched)),
            "total_articles": len(all_articles),
            "total_paragraphs": total_paragraphs,
            "duplicates_removed": duplicates_count,
            "searches": searches,
            "knowledge_bases": knowledge_bases
        }
    }


def infer_region_from_filename(file_path: str) -> str:
    """兼容旧结果文件：从文件名推断地域。新结果优先使用 search_meta.area。"""
    lower_path = file_path.lower()
    if "gd" in lower_path or "guangdong" in lower_path:
        return "广东省"
    if "bj" in lower_path or "beijing" in lower_path:
        return "北京市"
    if "sh" in lower_path or "shanghai" in lower_path:
        return "上海市"
    return "未知地区"


def main():
    parser = argparse.ArgumentParser(
        description="合并多次搜索结果（去重+重新编号）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s result_gd.json result_bj.json result_sh.json
  %(prog)s result_gd.json result_bj.json --output merged.json
        """
    )
    parser.add_argument("files", nargs="+", help="搜索结果文件路径")
    parser.add_argument("--output", "-o", help="输出文件路径（可选，默认输出到标准输出）")
    
    args = parser.parse_args()
    
    # 合并结果
    merged = merge_results(args.files)
    
    # 输出
    output_json = json.dumps(merged, ensure_ascii=False, indent=2)
    
    if args.output:
        output_path = resolve_output_json(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open('w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"✅ 已合并 {merged['search_summary']['total_searches']} 次搜索结果")
        print(f"   - 文章数: {merged['search_summary']['total_articles']}")
        print(f"   - 段落数: {merged['search_summary']['total_paragraphs']}")
        print(f"   - 去重: {merged['search_summary']['duplicates_removed']} 篇")
        print(f"   - 输出: {output_path}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
