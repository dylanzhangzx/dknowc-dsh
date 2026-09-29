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
# 工作区根：dsh 场景通过环境变量 DKNWOC_WS_ROOT 指向会话工作区，未设置时回退到 skill 目录（SkillHub 兼容）
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
        # 搜索目的兜底（3.7.6 修复）：该路 --purpose 为空时用该路 query 兜底——
        # 若留空，文章"搜索目的"缺失，溯源报告分组键（search_key）会退化成
        # "中国"/"浙江省"等地域碎片，材料面板筛选胶囊失去意义（杭州实测 75/295 篇退化）。
        purpose_val = search_meta.get("purpose") or search_meta.get("query") or ""
        searches.append({
            "file": str(safe_file_path),
            "query": search_meta.get("query", ""),
            "purpose": purpose_val,
            "area": region,
            "time": search_meta.get("time", ""),
            "policy": search_meta.get("policy", False),
            "full": search_meta.get("full", False),
            "segmentCount": search_meta.get("segmentCount"),
            "knowledgeBase": data.get("knowledgeBase", ""),
        })
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
