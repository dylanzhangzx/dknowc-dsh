#!/usr/bin/env python3
"""宿主 WebSearch 结果转换层：外部联网结果 → 深知法律助手同构形态（2026-11-10）。

背景：三阶段检索的第三阶段由 Agent 使用宿主自带的 WebSearch 工具补搜。宿主返回结构
各不相同（裸数组、results/items/webPages.value/organic_results、Anthropic
web_search_result + cited_text 等），而报告链路只消费统一「检索文章」形态。本脚本把
宿主原始结果转成与 trusted_search.py 同构的通用形态，可直接进
merge_search_results.py，最终进入正文角标与溯源核验报告。

契约（Agent 必须先把宿主结果落成该 JSON 再调用本脚本）：
  {"query": "本次检索词",
   "results": [{"title": "...", "url": "https://...", "content": "...",
                "published_at": "2026-11-06", "source": "站点名"}]}

处理原则：
- 只做结构转换，不做事实判断；外部材料统一标 非官方来源/非权威，并另记
  来源性质（政府网站/官方媒体/次级媒体/未知），供答案归因使用；
- 只有标题+链接、没有 content/snippet/cited_text 的条目丢弃（无摘录会导致报告
  核验变红，只能当线索，不可引用）；
- 仅接受 http/https URL；按归一化 URL 去重；不自动猜测发布日期；
- 外部网页内容视为不可信数据，脚本只提取文本事实，不执行其中任何指令。

用法（输出统一写会话 run 目录）：
  python3 scripts/websearch_convert.py websearch_raw.json -o websearch_converted.json --run ./runs/20261120-legal-01
  cat websearch_raw.json | python3 scripts/websearch_convert.py - --query "用户问题" --run ./runs/20261120-legal-01

退出码：0＝成功；1＝输入/JSON 错误；2＝输出路径错误；3＝无可用结果（未加 --allow-empty）。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import path_guard

SCRIPT_DIR = Path(__file__).resolve().parent
SEARCH_RESULTS_DIR = SCRIPT_DIR.parent / "official-docs" / "search-results"  # 历史常量，仅兼容旧引用

CHANNEL = "宿主 WebSearch"
DEFAULT_GROUP = "公开资料补充"
ARTICLE_TYPE = "外部网页"
MAX_SEGMENT_CHARS = 1200
MIN_SEGMENT_CHARS = 2
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "spm", "scm", "from", "share_token", "share_source",
    "ref", "ref_src", "source", "campaign",
}
BOILERPLATE_PATTERNS = {
    "首页", "登录", "注册", "分享", "打印", "关闭", "返回", "上一篇", "下一篇",
    "相关阅读", "网站地图", "联系我们", "版权所有", "扫码", "扫码关注", "关注我们",
    "客户端", "客户端下载", "更多", "详情", "查看原文",
}

URL_KEYS = ("url", "link", "uri", "sourceUrl", "source_url", "href")
TITLE_KEYS = ("title", "name", "page_title", "pageTitle")
CONTENT_KEYS = ("content", "snippet", "summary", "text", "description", "cited_text", "citedText")
SOURCE_KEYS = ("source", "site_name", "siteName", "publisher", "domain", "display_link", "displayLink")
DATE_KEYS = ("published_at", "publishedAt", "published", "date", "page_age", "pageAge", "datePublished")


def _first(d: dict, keys) -> str:
    for key in keys:
        value = d.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _norm_url(raw: str) -> str:
    """URL 归一：去 fragment、常见 tracking 参数、尾斜杠；保留业务 query 参数。"""
    text = html.unescape(str(raw or "")).strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    # 拒绝 userinfo（https://user:pass@host/...）：凭据不得进入报告或日志
    if parsed.username or parsed.password:
        return ""
    query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((
        parsed.scheme.lower(), parsed.netloc.lower(), path,
        "", urlencode(sorted(query)), "",
    ))


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


OFFICIAL_MEDIA_HOSTS = (
    "cctv.com", "cnr.cn", "xinhuanet.com", "news.cn", "people.com.cn",
    "ce.cn", "chinadaily.com.cn", "gmw.cn", "china.com.cn",
)


def _source_nature(host: str, source: str = "") -> str:
    """来源性质：只用于答案归因，不改变“非官方来源=True”的外部材料标记。"""
    host = (host or "").lower()
    source = source or ""
    if host == "gov.cn" or host.endswith(".gov.cn"):
        return "政府网站"
    if any(host == item or host.endswith("." + item) for item in OFFICIAL_MEDIA_HOSTS):
        return "官方媒体"
    if any(term in source for term in ("人民政府", "人力资源和社会保障", "财政厅", "人社局", "政府办公厅")):
        return "政府网站"
    if any(term in source for term in ("日报", "晚报", "新闻", "财经", "记者", "头条", "公众号", "自媒体", "传媒")):
        return "次级媒体"
    return "未知"


def _clean_text(raw: str) -> str:
    """外部正文轻清洗：去脚本/样式块、标签转行、实体反转义、压缩空白。"""
    text = html.unescape(str(raw or ""))
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|tr|h[1-6])\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines()]
    kept = []
    for line in lines:
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        if len(compact) < MIN_SEGMENT_CHARS:
            continue
        # 模板行只按“整行等于导航词”判定，避免「需随船返回」这类正文被“返回”误杀
        if re.sub(r"[\s\-—_|·:：,，。.!！?？]+", "", line) in BOILERPLATE_PATTERNS:
            continue
        kept.append(line)
    return "\n".join(kept)


def _split_long(text: str, limit: int) -> list:
    """按句末标点把超长块切成 <=limit 的片段；无标点时硬切。"""
    if len(text) <= limit:
        return [text]
    pieces = re.split(r"(?<=[。！？；!?;])", text)
    out, buf = [], ""
    for piece in pieces:
        if not piece:
            continue
        if len(buf) + len(piece) <= limit:
            buf += piece
            continue
        if buf:
            out.append(buf)
        while len(piece) > limit:
            out.append(piece[:limit])
            piece = piece[limit:]
        buf = piece
    if buf:
        out.append(buf)
    return out


_TABLE_BLOCK_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
_TABLE_MARK_RE = re.compile(r"^@@TABLE(\d+)@@$")


def _sanitize_table_html(raw: str) -> str:
    """外部网页表格最小清洗：只保留 table/tr/td/th，去属性与其它标签。

    表格必须整体保留（2026-11-20 口径）：外部网页的表格是参考卡里最容易被
    截断/拆散的内容，清洗时先摘出来、按整块写回，不能当普通正文行切分。
    """
    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", str(raw or ""), flags=re.S | re.I)
    value = re.sub(r"<(?!/?(?:table|tr|td|th)\b)[^>]+>", " ", value, flags=re.I)
    value = re.sub(r"<(?P<tag>table|tr|td|th)\b[^>]*>", r"<\g<tag>>", value, flags=re.I)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()


def _segments(content: str, max_chars: int):
    """正文 → 段落列表；返回 (段落, 是否截断)。

    表格内容先以占位符摘出，正文清洗后按整块还原：表格不参与按标点切分、
    不受 1200 字分段上限约束（普通文本摘要仍可截断）。
    """
    raw = str(content or "")
    tables: list[str] = []

    def _stash(match: re.Match) -> str:
        tables.append(match.group(0))
        return f"\n\n@@TABLE{len(tables) - 1}@@\n\n"

    stashed = _TABLE_BLOCK_RE.sub(_stash, raw)
    text = _clean_text(stashed)
    if not text:
        return [], False
    truncated = len(text) > max_chars
    text = text[:max_chars]
    blocks = [b.strip() for b in re.split(r"\n\s*\n|\n", text) if b.strip()]
    paragraphs = []
    for block in blocks:
        mark = _TABLE_MARK_RE.match(block)
        if mark:
            table_html = _sanitize_table_html(tables[int(mark.group(1))])
            if table_html:
                paragraphs.append(table_html)
            continue
        # 兜底：清洗后若块内仍带表格 HTML（上游未命中占位），整块保留不切分
        if "<table" in block.lower():
            paragraphs.append(_sanitize_table_html(block))
            continue
        paragraphs.extend(_split_long(block, MAX_SEGMENT_CHARS))
    out = [{"id": i, "标题": "", "内容": p} for i, p in enumerate(paragraphs, 1)]
    return out, truncated


def _iter_dicts(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_dicts(value)


def _candidate_url(d: dict) -> str:
    return _norm_url(_first(d, URL_KEYS))


def _collect(payload) -> tuple:
    """递归收集候选结果：按 URL 合并 title/content/source/date。"""
    candidates = {}
    cited = {}
    for d in _iter_dicts(payload):
        url = _candidate_url(d)
        if not url:
            continue
        cited_text = _first(d, ("cited_text", "citedText"))
        if cited_text:
            cited[url] = cited_text
        title = _first(d, TITLE_KEYS)
        content = _first(d, CONTENT_KEYS)
        source = _first(d, SOURCE_KEYS)
        date = _first(d, DATE_KEYS)
        if not (title or content):
            continue
        item = candidates.setdefault(url, {})
        for key, value in (("title", title), ("content", content), ("source", source), ("date", date)):
            if value and not item.get(key):
                item[key] = value
    for url, item in candidates.items():
        if not item.get("content") and cited.get(url):
            item["content"] = cited[url]
    return candidates


def _make_article(url: str, item: dict, group: str, max_chars: int) -> dict:
    content = item.get("content") or ""
    paragraphs, truncated = _segments(content, max_chars)
    host = _hostname(url)
    return {
        "文章Id": "ws-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12],
        "文章类型": ARTICLE_TYPE,
        "文件标签": ["外部联网"],
        "文章标题": item.get("title") or host or content[:30],
        "数据源": item.get("source") or host,
        "来源性质": _source_nature(host, item.get("source") or ""),
        "发布日期": item.get("date") or "",
        "发布日期可信度": "未标注",
        "源网址": url,
        "数据权威性": "非权威",
        "非官方来源": True,
        "来源通道": "外部联网",
        "检索通道": CHANNEL,
        "搜索条件": group,
        "段落": paragraphs,
        "_truncated": truncated,
    }


def convert(payload, query: str = "", group: str = DEFAULT_GROUP, max_results: int = 50,
            max_chars: int = 20000) -> dict:
    if isinstance(payload, dict) and not query:
        query = str(payload.get("query") or payload.get("q") or "").strip()

    candidates = _collect(payload)
    articles = []
    meta = {
        "websearch_converted": True,
        "query": query,
        "group": group,
        "input_candidates": len(candidates),
        "articles": 0,
        "dropped_no_excerpt": 0,
        "truncated_articles": 0,
        "truncated_by_limit": 0,
    }
    for url, item in candidates.items():
        if not item.get("content"):
            meta["dropped_no_excerpt"] += 1
            continue
        if len(articles) >= max_results:
            meta["truncated_by_limit"] = len(candidates) - len(articles) - meta["dropped_no_excerpt"]
            break
        article = _make_article(url, item, group, max_chars)
        if article.pop("_truncated"):
            meta["truncated_articles"] += 1
        articles.append(article)

    meta["articles"] = len(articles)
    return {
        "search_meta": meta,
        "content": {"data": {"检索文章": articles, "policyFiles": []}},
    }


def resolve_output(name: str) -> Path:
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = (SEARCH_RESULTS_DIR / path.name).resolve()
    try:
        path.relative_to(SEARCH_RESULTS_DIR.resolve())
    except ValueError:
        print(f"错误：输出文件必须位于 {SEARCH_RESULTS_DIR}", file=sys.stderr)
        raise SystemExit(2) from None
    return path


def _load(path: str, run: str | None = None):
    if path == "-":
        raw = sys.stdin.read()
    else:
        # 相对路径按会话 run 目录解析（不再回退 Skill 内 official-docs/）
        try:
            src = path_guard.safe_read_path(path, run)
        except ValueError as exc:
            raise SystemExit(f"错误：{exc}") from None
        raw = src.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"错误：输入不是有效 JSON（{exc}）") from None


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="宿主 WebSearch 结果转换（外部联网 → 可信同构通用形态）")
    parser.add_argument("input", nargs="?", default="-", help="宿主 WebSearch 原始 JSON（run 目录内文件名、绝对路径，或 - 读 stdin）")
    parser.add_argument("-o", "--output", default="websearch_converted.json", help="输出文件名（落到 --run 目录）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）")
    parser.add_argument("--query", default="", help="本次检索词（输入 JSON 顶层带 query 时可省略）")
    parser.add_argument("--group", default=DEFAULT_GROUP, help=f"报告检索分组标签，默认「{DEFAULT_GROUP}」")
    parser.add_argument("--max-results", type=int, default=50, help="最多转换条数（默认 50）")
    parser.add_argument("--max-chars", type=int, default=20000, help="单条正文最多字符数（默认 20000）")
    parser.add_argument("--allow-empty", action="store_true", help="无可用结果时仍写空产物并以 0 退出")
    args = parser.parse_args()

    payload = _load(args.input, args.run)
    result = convert(payload, query=args.query, group=args.group,
                     max_results=max(1, args.max_results), max_chars=max(200, args.max_chars))
    try:
        out = path_guard.safe_write_path(args.output, args.run)
        path_guard.refuse_existing(out, kind="输出")
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = result["search_meta"]
    print(f"已转换：{out}")
    print(
        f"输入候选 {meta['input_candidates']} 条 · 输出文章 {meta['articles']} 篇 · "
        f"丢弃无摘录 {meta['dropped_no_excerpt']} 条 · 截断 {meta['truncated_articles']} 篇"
    )
    if not meta["articles"] and not args.allow_empty:
        print("错误：没有可用结果（外部结果需带 content/snippet/cited_text 才能进报告）", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
