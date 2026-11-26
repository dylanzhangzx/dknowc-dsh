#!/usr/bin/env python3
"""深知税务助手 · 税务检索脚本。

两种模式：
1) 语义模式（--query，主路）：可信搜索接口 V2 条款级召回；可用 --policy-labels
   传完整路径标签圈定领域（税务族 / 社保族）。
2) 全文模式（--file <文件标题>，兜底）：政策条件筛选定位文件 → 政策正文 → 全文下载，
   用于核对文件全文/文号/条款上下文。税务不做"按第X条切分"——需要看条款时直接读全文。

输出为可信搜索同构 JSON（content.data.检索文章），可直接交给 merge_search_results.py
与 render_trace_html.py 生成溯源核验报告。

设计口径（2026-11-06 交接定稿）：
- 可信搜索 V2 是主路，任何税务检索第一步都是 V2；全文/版本接口只在 V2 没取全、
  需要核对全文或版本时兜底。
- 标签必须传完整路径；带标签返回 0 条不静默降级（记录 label_zero，需要无标签
  结果时另发一次独立检索，两次分别落盘）。
- 仅覆盖中国大陆税务；社保是相邻领域、另一个标签族。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tax_client as client
import run_dir
try:
    import tag_catalog
except Exception:  # 目录缺失时不影响检索
    tag_catalog = None  # type: ignore

# 全文兜底时按标题挑副本要剔除的噪音词（出现在"标题减去查询名"的剩余部分时剔除）
BAD_TITLE_WORDS = (
    "征求意见稿", "草案", "解读", "问答", "宣传", "学习", "培训", "讲话",
    "情况汇报", "征文", "审议", "说明",
)
# 全文返回的字符上限：防超长全文挤爆下游报告；截断时在产物里如实标注
MAX_FULL_TEXT_CHARS = 60000


# ---------- 工具 ----------

def normalize_width(text: str) -> str:
    out = []
    for ch in text or "":
        code = ord(ch)
        if 0xFF10 <= code <= 0xFF19:  # 全角数字
            out.append(chr(code - 0xFF10 + ord("0")))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = normalize_width(str(value)).strip()
    for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%Y/%m/%d", "%Y-%m", "%Y年%m月"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def format_date(value: Optional[date]) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def norm_title(text: str) -> str:
    return re.sub(r"[\s《》()（）\[\]【】·—\-]", "", text or "")


def title_score(title: str, target: str) -> int:
    """标题与查询名的匹配度：完全一致 10；前缀 8；包含 5；不含 0。"""
    t = norm_title(title)
    if not t:
        return 0
    bases = [target]
    if target.startswith("中华人民共和国"):
        bases.append(target[len("中华人民共和国"):])
    best = 0
    for base in bases:
        b = norm_title(base)
        if not b:
            continue
        if t == b:
            best = max(best, 10)
        elif t.startswith(b):
            best = max(best, 8)
        elif b in t:
            best = max(best, 5)
    return best


def host_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    return host


def snippet(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


# ---------- 全文兜底 ----------

def pick_copy(target: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按标题匹配度 + 状态 + 成文日期挑副本。

    税务文件多为公告/通知，正文不带修正日标记，不做法律场景的"修正日标记校验"；
    validityStatus 只作排序参考（库内效力状态有错标先例，不据此下结论）。
    """
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for c in candidates:
        ts = title_score(str(c.get("title") or ""), target)
        if ts == 0:
            continue
        extra = norm_title(str(c.get("title") or "")).replace(norm_title(target), "")
        if any(w in extra for w in BAD_TITLE_WORDS):
            continue
        status = str(c.get("validityStatus") or "")
        written = parse_date(c.get("writtenDate"))
        length = int(c.get("contentLength") or 0)
        score = ts * 10 + min(length / 10000.0, 5.0)
        if status == "EXPIRED_OR_REPEALED":
            score -= 8
        if written:
            score += min((written - date(2000, 1, 1)).days / 365.0, 5.0)  # 新文件微加分
        scored.append((score, c))
    if not scored:
        raise client.TaxApiError("resolve", f"「{target}」的候选均被标题规则排除")
    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def build_fulltext_article(target: str, cand: Dict[str, Any], text: str, versions: List[Dict[str, Any]]) -> Dict[str, Any]:
    truncated = len(text) > MAX_FULL_TEXT_CHARS
    body_text = text[:MAX_FULL_TEXT_CHARS] if truncated else text
    source_url = str(cand.get("sourceUrl") or "")
    written = parse_date(cand.get("writtenDate"))
    return {
        "文章Id": str(cand.get("encryptedFileId") or ""),
        "文章类型": "policy",
        "文章标题": str(cand.get("title") or target),
        "发布或实施机构": str(cand.get("issuingAuthority") or ""),
        "数据源": host_of(source_url) or "深知政策文件库",
        "源网址": source_url,
        "发布日期": format_date(written),
        "文号": str(cand.get("documentNumber") or ""),
        "生效日期": str(cand.get("effectiveDate") or ""),
        "文件标签": cand.get("policyTopicTags") or [],
        "版本状态": str(cand.get("validityStatus") or ""),
        "历次版本数": len(versions),
        "核验": ("原文取自全文下载" + ("；超长已截断，完整全文请再跑 --file" if truncated else "")),
        "检索通道": "深知税务检索·全文",
        "检索类型": "tax-fulltext",
        "段落": [{"id": 1, "标题": "全文", "内容": body_text, "匹配等级": "原文"}],
    }


def run_fulltext(target: str, max_chars: Optional[int] = None) -> Dict[str, Any]:
    """政策条件筛选 → 选副本 → 历次版本（尽力） → 政策正文 → 全文下载。"""
    global MAX_FULL_TEXT_CHARS
    if max_chars:
        MAX_FULL_TEXT_CHARS = max_chars
    # 条件筛选的标题匹配对长标题偏严：全名 → 去"关于"前缀 → 去"中华人民共和国"前缀逐步放宽
    variants: List[str] = [target]
    if "关于" in target:
        variants.append(target.split("关于", 1)[1])
    if target.startswith("中华人民共和国"):
        variants.append(target[len("中华人民共和国"):])
    candidates: Dict[str, Dict[str, Any]] = {}
    for variant in variants:
        if not variant.strip():
            continue
        try:
            items = client.filter_policies(variant.strip(), limit=30)
        except client.TaxApiError:
            continue
        for item in items:
            fid = str(item.get("encryptedFileId") or "")
            if fid and fid not in candidates:
                candidates[fid] = item
    if not candidates:
        raise client.TaxApiError("resolve", f"政策条件筛选未找到标题包含「{target}」的文件")
    cand = pick_copy(target, list(candidates.values()))
    versions: List[Dict[str, Any]] = []
    try:
        versions = client.query_versions(str(cand.get("encryptedFileId") or "")).get("versions") or []
    except client.TaxApiError:
        versions = []
    content, text = client.get_full_text(str(cand.get("encryptedFileId") or ""))
    if not text.strip():
        raise client.TaxApiError("download", f"「{target}」未取到可下载正文")
    article = build_fulltext_article(target, cand, text, versions)
    meta = {
        "mode": "fulltext",
        "file": target,
        "selected_file_id": str(cand.get("encryptedFileId") or ""),
        "selected_title": str(cand.get("title") or ""),
        "selected_status": str(cand.get("validityStatus") or ""),
        "versions_count": len(versions),
        "truncated": len(text) > MAX_FULL_TEXT_CHARS,
    }
    return output_body(target, date.today().isoformat(), [article], meta)


# ---------- V2 语义主路 ----------

def build_semantic_articles(body: Dict[str, Any], search_channel: str = "") -> List[Dict[str, Any]]:
    data = (body.get("content") or {}).get("data") or {}
    articles = [x for x in (data.get("检索文章") or []) if isinstance(x, dict)]
    for article in articles:
        # 与深知可信搜索 1.7.2 完全一致：只有 webSearch 通道标"·联网"并补非官方来源；
        # govSearch/wxSearch 不打该标（渲染层仍按 数据权威性=非权威 双口径兜底）。
        article.setdefault("检索通道", "深知税务检索·联网" if search_channel == "webSearch" else "深知税务检索·可信")
        article.setdefault("检索类型", "tax-semantic")
        if search_channel == "webSearch":
            article["非官方来源"] = True
            # 外部联网材料统一降权：不依赖接口 dataAuthority 的返回值（可能仍为“权威”）。
            # 来源性质由 source_cards 按发布机构/域名推断，原始材料不伪造。
            article["数据权威性"] = "非权威"
        # V2 文号键名是「发文字号」，统一补一份「文号」供下游渲染/核对使用
        if article.get("发文字号") and not article.get("文号"):
            article["文号"] = article["发文字号"]
        # V2 的段落字段已是原文原段；统一匹配等级文案，避免渲染层把它当低置信段落
        for para in article.get("段落") or []:
            if isinstance(para, dict) and not para.get("匹配等级"):
                para["匹配等级"] = "原文"
    return articles


def output_body(query: str, ref: str, articles: List[Dict[str, Any]], tax_meta: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tid": tax_meta.get("tid") or "",
        "ret": 0,
        "content": {
            "code": 200,
            "msg": "success",
            "data": {
                "用户问题": query,
                "咨询日期": ref,
                "办理地域": "中国",
                "文章数量": len(articles),
                "检索文章": articles,
            },
        },
        "_tax": tax_meta,
    }


def resolve_output_path(args: argparse.Namespace) -> Path:
    """产物落盘位置（2026-11-20 运行目录口径）：
    --out 新建运行目录 / --run 使用已有运行目录 / 都不传则在当前工作目录 runs/ 下新建；
    拒绝写入 Skill 安装目录（含 official-docs/），不覆盖已有运行结果。
    """
    try:
        if getattr(args, "out", "") and getattr(args, "run", ""):
            raise ValueError("--out 与 --run 只能二选一（新建运行目录 / 使用已有运行目录）")
        if getattr(args, "out", ""):
            run = run_dir.new_run_dir(args.out, "--out")
        elif getattr(args, "run", ""):
            run = run_dir.open_run_dir(args.run, "--run")
        else:
            run = run_dir.auto_run_dir()
    except ValueError as exc:
        raise client.TaxApiError("output", str(exc)) from None
    name = args.output or ("tax_fulltext.json" if args.file else "tax_search.json")
    try:
        target = run_dir.out_file(run, name)
    except ValueError as exc:
        raise client.TaxApiError("output", str(exc)) from None
    return target


def run(args: argparse.Namespace) -> Dict[str, Any]:
    ref_date = date.today().isoformat()

    if args.file:
        return run_fulltext(args.file.strip(), max_chars=args.max_chars)

    query = (args.query or "").strip()
    if not query:
        raise client.TaxApiError("input", "必须提供 --query（V2 主路），或 --file 走全文兜底")

    labels = [x.strip() for x in re.split(r"[,，]", args.policy_labels or "") if x.strip()]
    # 标签目录：允许传短名/叶子名，自动解析成接口要求的完整路径
    if labels and tag_catalog:
        try:
            labels = tag_catalog.resolve_many(labels)
        except Exception:
            pass
    # 阶段二（可信联网）不传标签：联网网页不带库内标签，传了会把结果全部过滤掉
    if args.search_channel and labels:
        print("阶段二（联网检索）不使用 policyLabels：联网网页不携带库内标签，已忽略标签参数",
              file=sys.stderr)
        labels = []
    body = client.semantic_search(
        query,
        limit_articles=args.limit_articles,
        segment_count=args.segment_count,
        service_area=(args.service_area or None),
        policy_labels=labels or None,
        search_channel=(args.search_channel or None),
    )
    if body.get("_tax_label_zero"):
        print(f"检索结果：带标签 {labels} 返回 0 条（按契约不作静默降级；如需无标签结果请另发一次检索）",
              file=sys.stderr)
    articles = build_semantic_articles(body, args.search_channel or "")
    # 校验返回的文件标签是否都在目录里（目录外标签说明数据侧有一致性问题）
    tag_unknown = []
    if tag_catalog:
        try:
            tag_unknown = tag_catalog.Catalog.load().unknown_in_articles(articles)
            if tag_unknown:
                print(f"标签校验：{len(tag_unknown)} 个返回标签不在目录中，例如 "
                      f"{tag_unknown[0]['文件标签']}", file=sys.stderr)
        except Exception:
            pass
    meta = {
        "mode": "semantic",
        "query": query,
        "policy_labels": labels,
        "service_area": args.service_area or "",
        "search_channel": args.search_channel or "",
        "tid": body.get("tid") or "",
        "article_count": len(articles),
        "note": ("阶段二：可信联网检索（外部网页，非官方来源）" if args.search_channel
                 else "V2 条款级召回是主路；需要核对全文/文号/版本时再用 --file 兜底"),
        "semantic_params": ((body.get("content") or {}).get("data") or {}).get("用户问题"),
        "tag_unknown": tag_unknown,
        "label_zero": bool(body.get("_tax_label_zero")),
    }
    return output_body(query, ref_date, articles, meta)


def main() -> None:
    parser = argparse.ArgumentParser(description="深知税务助手 · 税务检索（可信搜索 V2 主路 + 全文兜底）")
    parser.add_argument("--query", help="检索词：一税种/一事项一条聚焦短查询（主路）")
    parser.add_argument("--file", help="文件标题：全文兜底（政策条件筛选→正文→全文下载），不切条")
    parser.add_argument("--policy-labels", default="", help="标签过滤（完整路径，逗号分隔）。税务族=政策/主题标签/财政、金融、审计/税务；社保族=政策/主题标签/劳动、人事、监察/社会保障；可传短名自动解析")
    parser.add_argument("--service-area", default="", help="地域（如 北京市）；注意核对结果是否真的限定在该地")
    parser.add_argument("--search-channel", default="", choices=["", "webSearch", "govSearch", "wxSearch"],
                        help="阶段二联网检索：webSearch=互联网网页（非官方来源，自动打标）；govSearch=政府站定向；wxSearch=微信生态。不传=只查库内")
    parser.add_argument("--limit-articles", type=int, default=10, help="最多返回材料数（默认 10）")
    parser.add_argument("--segment-count", type=int, default=8, help="返回段落数（默认 8）")
    parser.add_argument("--max-chars", type=int, default=60000, help="全文模式的字符上限（默认 60000，截断会如实标注）")
    parser.add_argument("--out", help="新建运行目录（会话工作区，如 ./runs/20261120-B01-<时间>）；已有结果的目录会被拒绝")
    parser.add_argument("--run", help="使用已存在的运行目录（补查/续跑时用）；目录内已有同名产物不会被覆盖")
    parser.add_argument("--output", "-o", help="结果 JSON 文件名（配合 --out/--run 放进运行目录）或显式输出路径（不得指向 Skill 安装目录）")
    parser.add_argument("--json-only", action="store_true", help="仅输出 JSON")
    parser.add_argument("--timeout", type=int, default=90, help="单次请求超时秒数（默认 90）")
    args = parser.parse_args()

    try:
        body = run(args)
    except client.TaxApiError as exc:
        print(json.dumps({
            "status": "error",
            "stage": exc.stage,
            "message": str(exc),
            "status_code": exc.status_code,
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    path = resolve_output_path(args)
    body.setdefault("_tax", {})["run_dir"] = str(path.parent)
    raw = json.dumps(body, ensure_ascii=False, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    print(f"已保存税务检索 JSON：{path}")
    print(f"运行目录：{path.parent}")
    if not args.json_only:
        data = (body.get("content") or {}).get("data") or {}
        print(f"模式：{(body.get('_tax') or {}).get('mode')}｜材料：{data.get('文章数量')} 条")
        for idx, article in enumerate(data.get("检索文章") or [], start=1):
            print(f"{idx}. {article.get('文章标题')}｜{article.get('文号') or article.get('数据源')}｜{article.get('发布日期')}")
            for para in (article.get("段落") or [])[:1]:
                print("   " + snippet(str(para.get("内容") or ""), 160))


if __name__ == "__main__":
    main()
