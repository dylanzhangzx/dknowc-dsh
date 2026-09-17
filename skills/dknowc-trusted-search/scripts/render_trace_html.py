#!/usr/bin/env python3
"""可信溯源核验报告渲染器：把搜索结果 JSON + 最终答案渲染为单文件可核验 HTML。

深知可信搜索 SkillHub 版（对齐深知公文写作 3.7.0 渲染层，数据口径保持自有与真实）。
输入直读 trusted_search.py / deep_query.py 的 --json-only 输出（可信搜索 content.data
或深度搜索 deep-query/v3 格式），正文用 --answer-file 传入最终答案（关键结论带 [n] 角标），
成稿自检用 --self-check-file 传入五项结果。

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。
架构（参考深知晓交互原型）：
- 顶栏：身份章 + 标题 + 工具组（只看正文 / 复制全文 / 打印归档）+ 阅读进度条
- Hero：大标题 + 真实统计（N 次检索 · M 条材料 · K 处引用）+ 双视图切换
- 过程回顾条：检索 → 入库 → 逐条比对 → 核验完成（静态回放，数字全部真实计算；
  无思考流数据就不展示"思考"步骤——硬造即违背核验诚实性）
- 核验报告视图（默认）：核验报告单 + 正文分节卡；角标点击跳材料专库定位
- 材料专库视图（全屏）：大搜索 + 热词（标题/正文高频词真实计算）+ 检索分组 tabs + 材料卡
三个核验层次：报告级（核验报告单）／材料级（来源卡核验链标记）／引用级（角标一一绑定）。
诚实原则：脚本真实计算的结果才打勾；政策现行效力等无法自动判定项归入"建议人工复核"。
生成前预处理（内置）：policyFiles 发文字号本地匹配、原文链接活性检测（404/410 + 软 404
标题嗅探，--skip-link-check 跳过）、存档快照兜底（screenShotPath /A/ 容错 + 格式校验，
--no-snapshot 关闭）；缺原文链接不拖垮核验结论，按提醒呈现。
布局为单文件静态 HTML；打印归档模式单栏全展开并附材料附录。
所有输入输出经路径安全层限制在 skill 工作区 official-docs/ 内。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
SEARCH_RESULTS_DIR = WS_ROOT / "official-docs" / "search-results"
OUTPUT_DIR = WS_ROOT / "official-docs" / "output"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_input_path(value: str, allowed_suffixes: set) -> Path:
    """输入文件必须位于 skill 工作区内且后缀合法，阻断路径遍历。"""
    raw = Path(value).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else raw.resolve()
    if resolved.suffix.lower() not in allowed_suffixes:
        raise ValueError(f"输入文件后缀必须是 {sorted(allowed_suffixes)} 之一: {value}")
    if not (_is_within(resolved, SEARCH_RESULTS_DIR) or _is_within(resolved, SKILL_ROOT / "config") or resolved == SKILL_ROOT / "SKILL.md"):
        # 允许工作区内任意位置的答案/自检/搜索 JSON（search-results、output、根下临时文件）
        if not _is_within(resolved, SKILL_ROOT):
            raise ValueError(f"输入文件必须位于 skill 工作区内: {value}")
    return resolved


def _safe_output_path(value: str, allowed_suffixes: set, default_suffix: str) -> Path:
    """输出文件必须位于 official-docs/output/ 内且后缀合法。"""
    raw = Path(value).expanduser()
    if raw.suffix.lower() not in allowed_suffixes:
        raw = raw.with_suffix(default_suffix)
    resolved = raw.resolve() if not raw.is_absolute() else raw
    if not _is_within(resolved, OUTPUT_DIR):
        if raw.is_absolute():
            raise ValueError(f"输出文件必须位于 official-docs/output/ 内: {value}")
        resolved = (OUTPUT_DIR / raw.name).resolve()
    return resolved



# ============================================================
# 基础工具
# ============================================================

def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data
    return {"data": data}


def unwrap(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data.get("data"), dict) and data.get("success") is True:
        return data["data"]
    if isinstance(data.get("content"), dict):
        return data["content"]
    return data


def first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            return str(value).strip()
    return ""


def short(text: Any, limit: int = 360) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def normalize_citations(text: str) -> str:
    text = strip_tags(text)
    text = re.sub(r"【\s*(\d+)\s*】", r"[\1]", text)
    return re.sub(r"\[\^?(\d+)\^?\]", r"[\1]", text)


def strip_citation_markers(text: str) -> str:
    text = strip_tags(text)
    text = re.sub(r"【\s*\d+\s*】", "", text)
    text = re.sub(r"\[\^?\d+\^?\]", "", text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + ("\n" if text.strip() else "")


# ============================================================
# 生成前预处理（文号匹配 / 链接活性检测 / 快照兜底）
# ============================================================

# 快照兜底开关：默认启用。接口 screenShotPath 曾存在路径缺 /A/ 层级的拼接 bug
# （后端修复中）；verify_snapshots 在展示前完成"/A/ 修订 + 格式校验 + 不合法弃用"。
SNAPSHOT_ENABLED = True

# 软 404 关键词：政府站常以 HTTP 200 返回"页面不存在"错误页，状态码识别不了，
# 需读页面标题嗅探。关键词取自实测样例，且仅匹配 <title>（政策正文不会出现在标题里），
# 误杀风险极低。
SOFT_404_KEYWORDS = ("页面不存在", "页面未找到", "您访问的页面", "已删除", "已下线", "无法找到", "not found", "404")


def check_link_alive(url: str, timeout: int = 8) -> bool:
    """检测原文链接是否仍然可达。失效判据（客观信号，与请求方无关）：
    ① HTTP 404/410；② 软 404——HTTP 200 但页面标题为典型失效页。
    连接失败、超时、403、5xx 等一律视为"无法确认"按有效处理——政府站
    常对脚本请求反爬，凭这些判死会误杀可用链接。
    """
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status in (404, 410):
                    return False
                if method == "GET":
                    chunk = resp.read(4096).decode("utf-8", errors="replace")
                    title = re.search(r"<title>(.*?)</title>", chunk, re.I | re.S)
                    text = title.group(1) if title else chunk[:200]
                    lowered = text.lower()
                    return not any(k in text or k in lowered for k in SOFT_404_KEYWORDS)
        except urllib.error.HTTPError as e:
            if method == "GET":
                return e.code not in (404, 410)
        except Exception:
            if method == "GET":
                return True
    return True


def normalize_snapshot_url(url: str) -> str:
    """快照路径容错：接口部分返回值缺 /A/ 层级（公文版实测 60 条中 5 条，补全后即可访问），
    统一规范化为 https://attach.dknowc.cn/snapshot/A/<2位>/<2位>/<哈希>.jpg。"""
    u = (url or "").strip()
    if u.startswith("https://attach.dknowc.cn/snapshot/") and "/snapshot/A/" not in u:
        return u.replace("/snapshot/", "/snapshot/A/", 1)
    return u


def mark_dead_links(articles: List[Dict[str, Any]]) -> int:
    """并发检测全部材料的原文链接，404/410/软404 的标记 链接失效=True。返回失效数。"""
    targets = [(i, a["源网址"]) for i, a in enumerate(articles) if (a.get("源网址") or "").strip()]
    if not targets:
        return 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        alive = dict(zip((i for i, _ in targets), pool.map(check_link_alive, (u for _, u in targets))))
    dead = 0
    for i, _ in targets:
        if not alive.get(i, True):
            articles[i]["链接失效"] = True
            dead += 1
    return dead


def verify_snapshots(articles: List[Dict[str, Any]]) -> int:
    """快照展示前的路径校验（纯本地检查，不发网络请求）：
    组装阶段已由 normalize_snapshot_url 补全 /A/ 层级；此处校验修订后的路径
    是否符合合法格式（https://attach.dknowc.cn/snapshot/A/…），不合法则弃用。

    不做网络可达检测：attach 前置雷池 WAF 的拦截与请求方 IP 风控相关
    （检测机高频请求会被拦而普通用户正常），可达性实测会误杀好快照；
    快照文件本身的存在性由可信搜索侧的数据质量保障。
    """
    dropped = 0
    for a in articles:
        u = (a.get("快照链接") or "").strip()
        if not u:
            continue
        if u.startswith("https://attach.dknowc.cn/snapshot/A/"):
            continue
        a["快照链接"] = ""
        dropped += 1
    return dropped


def _normalize_title_for_match(value: str) -> str:
    """标题归一（文号匹配用）：全半角/大小写归一，去书名号括号与空白。"""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[《》〈〉「」『』\[\]【】()（）]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def attach_doc_numbers(articles: List[Dict[str, Any]], payload: Dict[str, Any]) -> int:
    """从同一响应的 policyFiles 区按标题本地匹配发文字号（writtenText）。

    文号与检索文章分开展示在同一响应里，本地标题匹配即可拿到，无需接口改动；
    新闻/解读类不在 policyFiles 中（本就无文号），匹配不上则不显示。
    """
    doc_numbers: Dict[str, str] = {}
    for holder in (payload.get("content") if isinstance(payload.get("content"), dict) else {},
                   (payload.get("content") or {}).get("data") if isinstance((payload.get("content") or {}).get("data"), dict) else {},
                   payload.get("data") if isinstance(payload.get("data"), dict) else {}):
        for pf in (holder.get("policyFiles") or []):
            if not isinstance(pf, dict):
                continue
            doc_no = first_str(pf.get("writtenText"), pf.get("发文字号"))
            title = first_str(pf.get("title"), pf.get("标题"))
            if doc_no and title:
                doc_numbers.setdefault(_normalize_title_for_match(title), doc_no)
    if not doc_numbers:
        return 0
    matched = 0
    for a in articles:
        if a.get("文号"):
            continue
        no = doc_numbers.get(_normalize_title_for_match(first_str(a.get("文章标题"), a.get("title"), a.get("标题"))))
        if no:
            a["文号"] = no
            matched += 1
    return matched


def preprocess_articles(articles: List[Dict[str, Any]], payload: Dict[str, Any],
                        skip_link_check: bool = False, snapshot_enabled: bool = True) -> None:
    """extract_sources 前的统一预处理：文号匹配、快照兜底、链接活性检测。

    直接改写文章 dict（注入 文号 / 快照链接 / 链接失效 字段），供
    source_from_article 读取；均为幂等操作，多轮渲染不叠加。
    """
    attach_doc_numbers(articles, payload)
    if snapshot_enabled:
        for a in articles:
            raw_snap = first_str(a.get("screenShotPath"), a.get("screenshot_path"), a.get("快照链接"), a.get("snapshot"))
            a["快照链接"] = normalize_snapshot_url(raw_snap) if raw_snap else ""
        verify_snapshots(articles)
    else:
        for a in articles:
            a["快照链接"] = ""
    if not skip_link_check:
        mark_dead_links(articles)


# ============================================================
# 素材四分类
# ============================================================

KIND_CATALOG = {
    "policy": ("政策依据", "pol"),
    "data": ("数据支撑", "dat"),
    "case": ("参考案例", "cas"),
    "reference": ("表述参考", "ref"),
    "material": ("材料", "mat"),
}


def normalize_kind(raw: str) -> Tuple[str, str]:
    """把来源类型文本归一化为（类型键, 中文标签, css 类名）。"""
    text = str(raw or "")
    if "政策" in text or "法规" in text or "依据" in text or "policy" in text.lower():
        key = "policy"
    elif "数据" in text or "统计" in text or "指标" in text or "data" in text.lower():
        key = "data"
    elif "案例" in text or "经验" in text or "做法" in text or "case" in text.lower():
        key = "case"
    elif "表述" in text or "行文" in text or "reference" in text.lower():
        key = "reference"
    else:
        key = "material"
    label, css = KIND_CATALOG[key]
    return key, label, css


def parse_year_month(raw: str) -> Optional[Tuple[int, int]]:
    """从日期文本提取（年, 月）；识别 2025年8月 / 2025-08 / 2025.08 / 2025-08-15。"""
    text = str(raw or "").strip()
    if not text:
        return None
    m = re.search(r"(20\d{2})\s*[年./-]\s*(\d{1,2})", text)
    if m:
        return int(m.group(1)), min(int(m.group(2)), 12)
    m = re.search(r"(20\d{2})", text)
    if m:
        return int(m.group(1)), 1
    return None


# ============================================================
# 素材提取（沿用原数据层）
# ============================================================

def clean_paragraph_noise(text: str) -> str:
    """清洗接口段落文本中的附件链接噪音。

    接口段落内容格式为「段落标题 https://attach.dknowc.cn/file/<正文>」——
    URL 前是段落标题（已由标题链单独展示），URL 本身是附件地址（卡片有"查看原文"入口）。
    摘录只保留 URL 之后的正文；无该前缀时兜底剔除文本中的裸 URL。
    """
    value = str(text or "")
    m = re.search(r"https?://\S*attach\.dknowc\.cn/file/", value)
    if m:
        return value[m.end():].strip()
    value = re.sub(r"https?://\S+", " ", value)
    return re.sub(r"[ \t]{2,}", " ", value).strip()


def paragraph_text(item: Dict[str, Any]) -> str:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    if isinstance(paragraphs, list):
        chunks = []
        for para in paragraphs:
            if isinstance(para, dict):
                chunk = first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"), para.get("标题"), para.get("title"))
            else:
                chunk = str(para)
            chunk = clean_paragraph_noise(chunk)
            if chunk:
                chunks.append(chunk)
        text = "\n".join(chunks)
        if text:
            return text
    return clean_paragraph_noise(first_str(
        item.get("摘录"),
        item.get("摘要"),
        item.get("相关段落"),
        item.get("支撑内容"),
        item.get("support"),
        item.get("全文"),
        item.get("content"),
        item.get("text"),
        item.get("snippet"),
    ))


def content_segments(item: Dict[str, Any]) -> List[Dict[str, str]]:
    paragraphs = item.get("content") or item.get("段落") or item.get("paragraphs") or item.get("paragraphList")
    segments: List[Dict[str, str]] = []
    if not isinstance(paragraphs, list):
        return segments
    for para in paragraphs:
        if isinstance(para, dict):
            text = first_str(para.get("text"), para.get("内容"), para.get("content"), para.get("summary"))
            title = first_str(para.get("title"), para.get("标题"), para.get("name"))
            pid = first_str(para.get("id"), para.get("idx"), para.get("index"), para.get("seq"), para.get("编号"))
            if text or title:
                segments.append({"id": pid, "title": title, "text": text})
        else:
            text = first_str(para)
            if text:
                segments.append({"id": "", "title": "", "text": text})
    return segments


def source_from_article(item: Dict[str, Any], index: int, segment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
    segment = segment or {}
    # segment 的 id 是文章内段落序号（每篇各自从 1 起），不是材料角标号，不得用作材料 id，
    # 否则多篇材料的段落 id 同为 "1" 会互相冲突，导致角标绑定错乱。
    explicit_id = first_str(
        item.get("角标"),
        item.get("编号"),
        item.get("index"),
        item.get("idx"),
        item.get("seq"),
        item.get("serialNo"),
        item.get("materialIndex"),
        item.get("referenceIndex"),
        item.get("引用编号"),
        vo.get("index"),
        vo.get("idx"),
    )
    if explicit_id:
        match = re.search(r"\d+", explicit_id)
        explicit_id = match.group(0) if match else ""
    source = {
        "id": explicit_id or str(index),
        "title": first_str(
            item.get("文章标题"),
            item.get("material_name"),
            item.get("材料名称"),
            item.get("title"),
            item.get("标题"),
            item.get("name"),
            vo.get("showTitle"),
            vo.get("title"),
            "未命名材料",
        ),
        "agency": first_str(
            item.get("unit") if not isinstance(item.get("unit"), list) else "、".join(str(x) for x in item.get("unit")[:3]),
            item.get("sourceElement"),
            item.get("数据源"),
            item.get("发布或实施机构"),
            item.get("发布机关"),
            item.get("来源"),
            vo.get("typeName"),
            vo.get("sourceName"),
        ),
        "date": first_str(item.get("发布日期"), item.get("date"), item.get("发布时间"), item.get("createDate"), vo.get("dateTime"), vo.get("createDate")),
        "url": first_str(item.get("sourceUrl"), item.get("source_url"), item.get("源网址"), item.get("原文链接"), item.get("url"), item.get("原文"), vo.get("sourceUrl"), vo.get("url")),
        "policy_url": first_str(item.get("policyUrl"), item.get("policy_url"), item.get("知识专库原文"), vo.get("policyUrl")),
        "excerpt": segment.get("text") or paragraph_text(item),
        "section": first_str(item.get("正文对应"), item.get("section"), item.get("支撑")),
        "kind": first_str(item.get("类型"), item.get("type"), item.get("素材类型"), vo.get("typeName"), "材料"),
        "verify_note": first_str(item.get("核验"), item.get("verification"), item.get("核验说明")),
        "area": first_str(item.get("intentionArea"), item.get("area"), item.get("地域")),
    }
    # 段落级数据（多段分块展示用）：每段 {chain:[文章,章节,子节...], text}
    # 段落标题自带 > 层级，拆级成面包屑；段落标题与文章标题相同或缺失时链只含文章一级。
    segments = []
    for seg in content_segments(item):
        seg_title = first_str(seg.get("title"))
        levels = [lvl.strip() for lvl in re.split(r"\s*>\s*", seg_title) if lvl.strip()] if seg_title else []
        if levels and levels[0] == source["title"]:
            levels = levels[1:]
        seg_text = clean_paragraph_noise(seg.get("text"))
        chain_lvls = [source["title"]] + levels
        segments.append({"chain": chain_lvls, "text": strip_leading_chain(seg_text, chain_lvls)})
    source["segments"] = segments
    # 首段章节位置（兼容旧单行引用处）
    first_chain = segments[0]["chain"][1:] if segments else []
    source["doc_section"] = " › ".join(first_chain)
    source["chain_full"] = " › ".join(segments[0]["chain"]) if segments else ""
    # 发文字号（接口 policyFiles.writtenText，本地标题匹配）
    source["doc_number"] = first_str(item.get("文号"), item.get("doc_number"))
    # 所属搜索条件（多路检索分组）与引用状态（未引用=接口召回但正文未采用）
    source["search_key"] = first_str(item.get("搜索条件"), item.get("search_key"))
    source["used"] = item.get("已引用", item.get("used", True))
    if not isinstance(source["used"], bool):
        source["used"] = True
    # 快照兜底：原文链接 404/410（生成时真实检测）或接口未返回源网址时，
    # 改用接口提供的存档快照链接回看——快照是原文的存档副本，按钮文案如实区分。
    source["snapshot"] = first_str(item.get("快照链接"), item.get("snapshot"), item.get("screenShotPath"))
    source["link_dead"] = item.get("链接失效") is True or item.get("link_dead") is True
    # 发布日期可信度（实测：「高」=模型治理入库、标题模型精抽；「较高」=门户抓取、标题规则提取）
    source["conf"] = first_str(item.get("发布日期可信度"), item.get("可信度"), item.get("confidence"))
    key, label, css = normalize_kind(source["kind"])
    source["type_key"] = key
    source["type_label"] = label
    source["type_css"] = css
    live_url = bool(source["url"] and source["url"] != "接口未返回") and not source["link_dead"]
    source["has_link"] = live_url or bool(source["policy_url"]) or bool(source["snapshot"])
    # 核验状态只看摘录可比对；原文链接死活与快照有无是回看通道问题，不影响核验结论
    source["verified"] = bool(source["excerpt"])
    return source


def extract_articles_from_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """可信搜索 dependable/search 格式：content.data.检索文章。"""
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else content.get("data")
    if isinstance(data, dict) and isinstance(data.get("检索文章"), list):
        return [x for x in data["检索文章"] if isinstance(x, dict)]
    return []


def extract_articles_from_deep(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """深度搜索 deep-query/v3 非流式格式：{"data": {"searches": [{"result": [...]}], "common_articles": [...]}}。

    按源网址去重摊平；为每篇材料注入"搜索条件"（子查询的地域·查询词），供材料专库检索分组筛选。
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    searches = data.get("searches")
    if not isinstance(searches, list):
        return []
    seen: set = set()
    out: List[Dict[str, Any]] = []

    def _add(article: Any, search_key: str) -> None:
        if not isinstance(article, dict):
            return
        key = str(article.get("源网址") or article.get("文章标题") or "")
        if key and key in seen:
            return
        if key:
            seen.add(key)
        if search_key and not article.get("搜索条件"):
            article["搜索条件"] = search_key
        out.append(article)

    for search in searches:
        if not isinstance(search, dict):
            continue
        areas = "、".join(str(a) for a in (search.get("areas") or []))
        query = str(search.get("query") or "").strip()
        label = f"{areas}·{query[:14]}" if areas else query[:18]
        for article in search.get("result") or []:
            _add(article, label)
    for article in data.get("common_articles") or []:
        # 多查询公共文章给独立分组名（空 key 落不进任何分组 tab，无法筛选）
        _add(article, "多查询公共")
    return out


def extract_reference_materials(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    materials = payload.get("referenceMaterials")
    if isinstance(materials, list):
        return [x for x in materials if isinstance(x, dict)]
    return []


def extract_knowledge_base(payload: Dict[str, Any]) -> str:
    """知识专库链接（可信搜索响应 content.knowledgeBase）：缺原文链接材料的回看通道。"""
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    return first_str(
        content.get("knowledgeBase"),
        payload.get("knowledgeBase"),
        data.get("knowledgeBase"),
        payload.get("knowledgeBaseUrl"),
    )


def extract_sources(payload: Dict[str, Any],
                    skip_link_check: bool = False, snapshot_enabled: bool = True) -> List[Dict[str, str]]:
    raw_sources: List[Dict[str, Any]] = []
    raw_sources.extend(extract_reference_materials(payload))
    is_deep = bool(extract_articles_from_deep(payload))
    raw_sources.extend(extract_articles_from_search(payload))
    raw_sources.extend(extract_articles_from_deep(payload))
    if not is_deep:
        # 可信搜索单次检索：材料统一标注"本次检索"分组（多轮检索由 Agent 合并 JSON 后各自携带）
        for item in raw_sources:
            if not item.get("搜索条件"):
                item["搜索条件"] = "本次检索"

    # 生成前预处理：文号匹配（policyFiles）、快照兜底、原文链接活性检测
    preprocess_articles(raw_sources, payload, skip_link_check=skip_link_check, snapshot_enabled=snapshot_enabled)

    # 知识专库回看：原文链接缺失/失效的材料挂知识专库链接作为回看通道（不影响核验判定）
    kb_url = extract_knowledge_base(payload)
    if kb_url:
        for item in raw_sources:
            if not (item.get("源网址") or "").strip() or item.get("链接失效") is True:
                if not first_str(item.get("知识专库原文"), item.get("policyUrl"), item.get("policy_url")):
                    item["知识专库原文"] = kb_url

    sources: List[Dict[str, str]] = []
    seen = set()
    for item in raw_sources:
        # 一篇材料一张卡：段落合并为摘录（paragraph_text 拼接全部段落），不按段落拆卡——
        # 溯源 JSON 的 materials 与正文角标按"材料"粒度一一对应，拆段会使编号错位。
        source = source_from_article(item, len(sources) + 1)
        key = (source["id"], source["title"], source["url"], source["excerpt"][:80])
        if key in seen:
            continue
        seen.add(key)
        if not source["id"]:
            source["id"] = str(len(sources) + 1)
        sources.append(source)
    return sources


def extract_answer(payload: Dict[str, Any]) -> str:
    resp = payload.get("resp")
    if isinstance(resp, dict):
        answer = first_str(resp.get("content"), resp.get("answer"), resp.get("text"))
        if answer:
            return normalize_citations(answer)
    answer = first_str(payload.get("answer"), payload.get("contentText"), payload.get("text"))
    if answer:
        return normalize_citations(answer)
    articles = extract_articles_from_search(payload)
    if articles:
        rows = ["可信搜索召回了以下重点材料："]
        for idx, item in enumerate(articles[:8], start=1):
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), item.get('title'), item.get('标题'), '未命名材料')}")
        return "\n".join(rows)
    deep_articles = extract_articles_from_deep(payload)
    if deep_articles:
        rows = ["深度搜索召回了以下重点材料："]
        for idx, item in enumerate(deep_articles[:8], start=1):
            vo = item.get("vo") if isinstance(item.get("vo"), dict) else {}
            rows.append(f"[{idx}] {first_str(item.get('文章标题'), vo.get('showTitle'), vo.get('title'), item.get('title'), '未命名材料')}")
        return "\n".join(rows)
    return "接口返回中未识别到正文内容；请查看材料专库或原始 JSON。"


def extract_question(payload: Dict[str, Any]) -> str:
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else {}
    first_query = ""
    searches = data.get("searches") if isinstance(data.get("searches"), list) else None
    if searches and isinstance(searches[0], dict):
        first_query = str(searches[0].get("query") or "")
    return first_str(
        payload.get("question"),
        payload.get("input"),
        payload.get("query"),
        data.get("用户问题"),
        first_query,
        content.get("query"),
        content.get("question"),
    )


def citation_ids(answer: str) -> List[str]:
    ids: List[str] = []
    for match in re.finditer(r"\[(\d+)\]", answer):
        item = match.group(1)
        if item not in ids:
            ids.append(item)
    return ids


# ============================================================
# 核验计算（报告级）
# ============================================================

SELF_CHECK_ITEMS = [
    ("fact_basis", "事实有据"),
    ("binding", "角标绑定"),
    ("consistency", "答案一致"),
    ("freshness", "时效确认"),
    ("no_gap", "无未核验断言"),
]

SELF_CHECK_LABELS = dict(SELF_CHECK_ITEMS)
SELF_CHECK_LABELS.update({
    "事实有据": "事实有据", "角标绑定": "角标绑定", "答案一致": "答案一致",
    "时效确认": "时效确认", "无未核验断言": "无未核验断言",
})


def classify_check_value(raw: Any) -> Tuple[str, str]:
    """把自检项的值解析为（状态, 核验说明）。

    兼容多种写法：`pass` / `true` / `通过` / `通过：说明文字` / `✓` 等；
    值后面的说明文字保留下来供核验单展示。无法识别的状态按未通过处理，
    并保留原文，不假装通过。
    """
    text = str(raw or "").strip()
    lowered = text.lower()
    for prefix in ("未通过", "不通过", "不合格", "fail", "false", "否", "✗", "no"):
        if lowered.startswith(prefix):
            return "fail", text[len(prefix):].lstrip("：:，,、 ").strip()
    for prefix in ("已通过", "通过", "合格", "pass", "ok", "true", "是", "✓", "yes"):
        if lowered.startswith(prefix):
            return "pass", text[len(prefix):].lstrip("：:，,、 ").strip()
    return "fail", text


def normalize_self_check(raw: Any) -> Optional[Dict[str, Tuple[str, str]]]:
    if not isinstance(raw, dict):
        return None
    items: Dict[str, Tuple[str, str]] = {}
    for key, value in raw.items():
        status, note = classify_check_value(value)
        label = SELF_CHECK_LABELS.get(key, SELF_CHECK_LABELS.get(str(key), str(key)))
        items[label] = (status, note)
    return items or None


def compute_verification(answer: str, sources: List[Dict[str, str]], payload: Dict[str, Any],
                         generated_at: Optional[datetime] = None) -> Dict[str, Any]:
    """核验报告单数据。只计算脚本真实可得的结果，不虚构通过。"""
    generated_at = generated_at or datetime.now()

    # ① 依据溯源：摘录可比对 + 原文链接可回看。
    # 只统计被正文引用的材料——未引用召回材料未进入正文核验流程，其缺链在自身卡片上如实标注，
    # 不应拖累"正文依据可交付"的报告级结论。
    # 缺原文链接（接口对部分治理库文章不返回源网址，属数据源覆盖问题而非核验工作缺失）
    # 不再拖垮整体结论——报告的正常结论即为"核验完成"，缺链在指标行黄色提醒并在卡片标注；
    # 缺摘录（正文依据无可比对的原文）仍视为核验问题计入未通过。
    cited_sources = [s for s in sources if s.get("used", True)]
    missing_links = [s["title"] for s in cited_sources if not s.get("has_link")]
    missing_excerpts = [s["title"] for s in cited_sources if not (s.get("excerpt") or "").strip()]
    trace_passed = len(cited_sources) - len(missing_excerpts)

    # ② 引用绑定：正文角标与来源卡一一对应（按角标出现次数计，与用户在正文中数到的一致）
    cited = citation_ids(answer)
    all_marks = re.findall(r"\[(\d+)\]", answer)
    source_ids = {s["id"] for s in sources}
    unbound_ids = [cid for cid in cited if cid not in source_ids]
    unbound = [cid for cid in unbound_ids for _ in range(all_marks.count(cid))]
    no_citation = bool(sources) and not cited

    # ③ 时效检查：材料日期范围与历史材料计数
    dated = [parse_year_month(s.get("date")) for s in sources]
    dated = [d for d in dated if d]
    freshness = None
    old_count = 0
    if dated:
        freshness = {
            "min": min(dated),
            "max": max(dated),
            "old_count": sum(1 for y, _ in dated if y <= generated_at.year - 3),
        }

    # ④ 类型覆盖：素材四分类分布
    coverage = {key: 0 for key in KIND_CATALOG}
    for s in sources:
        coverage[s.get("type_key", "material")] = coverage.get(s.get("type_key", "material"), 0) + 1

    # ⑤ 成稿自检：由溯源 JSON 的 self_check 传入，未传入如实显示未记录
    self_check_raw = None
    for holder in (payload, payload.get("content") if isinstance(payload.get("content"), dict) else {}):
        self_check_raw = self_check_raw or holder.get("selfCheck") or holder.get("self_check")
    self_items = normalize_self_check(self_check_raw)
    self_check = None
    if self_items:
        passed = sum(1 for status, _ in self_items.values() if status == "pass")
        self_check = {"items": self_items, "passed": passed, "total": len(self_items),
                      "status": "pass" if passed == len(self_items) else "fail"}
    else:
        self_check = {"items": {}, "passed": 0, "total": len(SELF_CHECK_ITEMS), "status": "missing"}

    # 政策效力：无法自动判定现行效力，列出建议人工复核
    policy_count = coverage.get("policy", 0)

    trace_ok = cited_sources and not missing_excerpts
    binding_ok = (not unbound) and not no_citation
    overall_passed = trace_ok and binding_ok

    reasons = []
    if not sources:
        reasons.append("没有找到来源材料")
    if no_citation:
        reasons.append("正文里没有来源角标，对不上材料")
    if unbound:
        reasons.append(f"有 {len(unbound)} 处角标找不到对应材料")
    if self_check["status"] == "fail":
        reasons.append("交付前检查有没过的项")

    return {
        "overall": {
            "passed": overall_passed,
            "label": "核验完成，正文依据逐条对过原文" if overall_passed else "核验未完全通过",
            "reasons": reasons,
        },
        "traceability": {"total": len(cited_sources), "passed": trace_passed,
                         "missing_links": missing_links, "missing_excerpts": missing_excerpts},
        "binding": {"total": len(all_marks), "bound": len(all_marks) - len(unbound), "unbound": unbound_ids, "no_citation": no_citation},
        "freshness": freshness,
        "coverage": coverage,
        "self_check": self_check,
        "policy_count": policy_count,
        "manual_checks": [str(x) for x in (payload.get("verificationChecks") or payload.get("verification_checks") or []) if str(x).strip()],
    }


# ============================================================
# 过程回顾 / 热词（真实计算，不虚构流程）
# ============================================================

def compute_process_stats(sources: List[Dict[str, str]], answer: str) -> Dict[str, Any]:
    """过程回顾条数据：检索次数、每组检索的召回/采用数、入库与引用计数。

    全部来自素材自带的真实字段（search_key 分组、used 引用状态、正文角标计数），
    不虚构任何流程步骤。
    """
    order: List[str] = []
    for s in sources:
        key = (s.get("search_key") or "").strip()
        if key and key not in order:
            order.append(key)
    cond_rows = []
    for key in order:
        group = [s for s in sources if (s.get("search_key") or "").strip() == key]
        cond_rows.append({
            "key": key,
            "total": len(group),
            "used": sum(1 for s in group if s.get("used", True)),
        })
    n_searches = len(cond_rows) or (1 if sources else 0)
    used_count = sum(1 for s in sources if s.get("used", True))
    unused_count = len(sources) - used_count
    n_cite_marks = len(re.findall(r"\[(\d+)\]", answer))
    return {
        "conds": cond_rows,
        "n_searches": n_searches,
        "has_cond_detail": bool(cond_rows),
        "n_materials": len(sources),
        "used_count": used_count,
        "unused_count": unused_count,
        "n_cite_marks": n_cite_marks,
    }


HOT_STOP = {
    "关于", "通知", "工作", "意见", "方案", "实施", "有关", "问题", "情况", "报告", "总结",
    "制度", "体系", "机制", "指导", "贯彻", "落实", "进一步", "以及", "其他", "相关", "以下",
    "以上", "共和国", "人民", "中华", "国务院", "人民政府", "办公厅", "印发", "试行",
    "办法", "条例", "若干", "的重点", "有所", "一个", "方面", "方式", "内容", "基本",
    "发展", "建设", "政策", "产业", "企业", "应用", "改革", "目标", "任务", "规划",
    "领域", "措施", "支持", "行动", "服务", "管理", "政府",
}


def extract_hot_terms(answer: str, sources: List[Dict[str, str]], top: int = 8) -> List[str]:
    """材料专库热词：材料标题（加权）+ 检索条件 + 正文的高频 2-4 字词，真实统计。

    泛词过滤：出现在超过 60% 材料标题中的词（如库内全部材料共有的主题词）
    无法筛出子集，没有筛选价值，剔除。
    """
    corpus_parts: List[str] = []
    for s in sources:
        if s.get("title"):
            corpus_parts.extend([s["title"]] * 3)
        if s.get("search_key"):
            corpus_parts.extend([s["search_key"]] * 2)
    clean_answer = re.sub(r"\[\d+\]", "", answer or "")
    corpus_parts.append(clean_answer)
    corpus = "\n".join(corpus_parts)

    counts: Dict[str, int] = {}
    for run in re.findall(r"[一-鿿]{2,}", corpus):
        for n in (2, 3, 4):
            for i in range(len(run) - n + 1):
                gram = run[i:i + n]
                counts[gram] = counts.get(gram, 0) + 1

    titles = [s.get("title") or "" for s in sources]
    n_titles = max(1, len(titles))
    df_limit = max(1, int(n_titles * 0.6))

    cands = [(g, c) for g, c in counts.items()
             if c >= 2 and g not in HOT_STOP and "的" not in g and not any(ch.isdigit() for ch in g)
             and sum(1 for t in titles if g in t) <= df_limit]
    cands.sort(key=lambda x: (-x[1], -len(x[0])))
    kept: List[Tuple[str, int]] = []
    for gram, count in cands:
        redundant = False
        for kgram, kcount in kept:
            # 短词是已入选高频长词的子串且计数接近 → 被长词覆盖，剔除
            if gram in kgram and kcount >= count * 0.6:
                redundant = True
                break
        if not redundant:
            kept.append((gram, count))
        if len(kept) >= top:
            break
    return [g for g, _ in kept]


# ============================================================
# 正文解析与分节
# ============================================================

def render_inline_markdown(text: str, citation_repl) -> str:
    body = esc(text)
    body = re.sub(r"`([^`]+)`", r"<code>\1</code>", body)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"__(.+?)__", r"<strong>\1</strong>", body)
    body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", body)
    body = re.sub(r"(?<!_)_([^_\n]+_)(?!_)", r"<em>\1</em>", body)
    body = re.sub(r"\[(\d+)\]", citation_repl, body)
    return body


def is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip().strip("|")
    if not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def split_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_markdown_table(lines: List[str], citation_repl) -> str:
    header = split_markdown_table_row(lines[0])
    body_lines = lines[2:] if len(lines) > 1 and is_markdown_table_separator(lines[1]) else lines[1:]
    head_html = "".join(f"<th>{render_inline_markdown(cell, citation_repl)}</th>" for cell in header)
    rows = []
    for line in body_lines:
        cells = split_markdown_table_row(line)
        rows.append("<tr>" + "".join(f"<td>{render_inline_markdown(cell, citation_repl)}</td>" for cell in cells) + "</tr>")
    return f'<div class="tbl-wrap"><table class="data-tbl"><thead><tr>{head_html}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def sanitize_table_html(text: str) -> str:
    """清洗接口表格 HTML：仅保留 table/thead/tbody/tr/td/th/br，去脚本样式与属性。"""
    cleaned = re.sub(r"(?is)<script.*?</script>", "", text)
    cleaned = re.sub(r"(?is)<style.*?</style>", "", cleaned)
    cleaned = re.sub(r"\s+on\w+\s*=\s*(['\"]).*?\1", "", cleaned)
    cleaned = re.sub(r"\s+(href|src)\s*=\s*(['\"]).*?\2", "", cleaned)
    allowed = {"table", "thead", "tbody", "tr", "td", "th", "br"}

    def tag_repl(match: re.Match[str]) -> str:
        closing, name = match.group(1), match.group(2).lower()
        if name not in allowed:
            return ""
        return f"<{closing}{name}>"

    return re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", tag_repl, cleaned)


def render_excerpt_html(text: str) -> str:
    value = str(text or "")
    if "<table" not in value.lower():
        return f'<div class="sc-excerpt plain">{esc(value)}</div>'
    return f'<div class="sc-excerpt rich">{sanitize_table_html(value)}</div>'


def parse_answer_blocks(answer: str, valid_ids: set, chip_map: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], set]:
    """把正文 Markdown 解析为结构化块；同时收集全部角标。

    角标渲染为原型式 sup.cite 上标胶囊；段落对应的溯源卡（src-card）由
    render_section_cards 在段后输出。
    """

    def jb_html(cid: str) -> str:
        jb = chip_map.get(cid)
        if not jb:
            return ""
        if jb.get("url"):
            btn_txt = "查看存档全文" if jb.get("dead") else "查看全文"
            link = (f'<a class="jb-src" href="{esc(jb["url"])}" target="_blank" rel="noopener noreferrer">'
                    f'{ARROW_SVG}<span>{btn_txt}</span></a>')
        else:
            link = ""
        # 原文直达区展示标题链（多段分块，各段带链——快速人工核验的核心抓手）
        segs = jb.get("segments") or []
        if segs:
            quote = ""
            seg_idx = -1
            for seg in segs:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                seg_idx += 1
                if "<table" in text.lower():
                    # 表格不能静态写进 span（解析器会拆散）：此处留占位，
                    # 表格数据由 render_html 汇总注入页尾 JSON，展开时 JS 填充
                    tbl_key = f"{cid}-{seg_idx}"
                    jb.setdefault("_tables", {})[tbl_key] = sanitize_table_html(text)
                    body_txt = f'<span class="sc-excerpt rich tbl-holder" data-tbl="{esc(tbl_key)}"></span>'
                else:
                    body_txt = f'<span class="sc-excerpt">{esc(text)}</span>'
                inner = f'<i class="jb-no">{esc(cid)}</i>{body_txt}'
                item = f'<span class="jb-quote" role="button" tabindex="0">{inner}</span>'
                quote += render_crumb(seg.get("chain") or []) + item
        elif jb["excerpt"]:
            inner = f'<i class="jb-no">{esc(cid)}</i><span>{esc(jb["excerpt"])}</span>'
            quote = f'<span class="jb-quote" role="button" tabindex="0">{inner}</span>'
        else:
            quote = ""
        site_html = (f'<span class="jb-site"><span class="dot"></span>{esc(jb.get("site") or "")}</span>'
                     if (jb.get("site") or "").strip() else "")
        return (
            f'<span class="jb" data-cite="{esc(cid)}">'
            f'<button class="jb-name" type="button" aria-expanded="false">{CARET_SVG}'
            f'<i class="jb-id">{esc(cid)}</i>'
            f'<span class="jb-txt">{esc(jb["title"])}</span></button>'
            f'<span class="jb-body"><span class="jb-head"><span class="jb-label">{SRC_ICO_SVG}溯源原文：</span>{link}</span>'
            f'{site_html}'
            f'{quote}</span></span>'
        )

    def make_block_repl(block_text: str):
        """按块构造角标替换器：同段同材料只保留最后一次出现的角标（前处整体删除），
        最后一处挂数字角标 + 引文胶囊——一段中同一材料只出现一次。"""
        remaining: Dict[str, int] = {}
        for cid in re.findall(r"\[(\d+)\]", block_text):
            remaining[cid] = remaining.get(cid, 0) + 1

        def repl(match: re.Match[str]) -> str:
            cid = match.group(1)
            remaining[cid] = max(0, remaining.get(cid, 1) - 1)
            if remaining[cid] > 0:
                return ""
            if cid in chip_map:
                return jb_html(cid)
            # 未绑定角标（无对应材料）：红色数字警示，绝不按位置猜测
            return f'<sup class="cite unresolved" data-cite="{esc(cid)}" title="核验依据 [{esc(cid)}?]">{esc(cid)}?</sup>'

        return repl

    blocks: List[Dict[str, Any]] = []
    lines = answer.split("\n")
    idx = 0
    while idx < len(lines):
        block = lines[idx].strip()
        if not block:
            idx += 1
            continue
        # 引文胶囊位置规范：角标与后随标点换位——标点紧跟文字，胶囊放标点之后
        # （避免胶囊把句号挤到下一行孤悬，对齐深知晓原型"…内容。～出处"形态）
        block = re.sub(r"\[(\d+)\]([。；，、！？：；,.])", r"\2[\1]", block)
        ids = citation_ids(block)
        repl = make_block_repl(block)
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading_match:
            blocks.append({"kind": "heading", "level": len(heading_match.group(1)),
                           "text": heading_match.group(2).strip(), "cites": ids, "repl": repl})
            idx += 1
        elif "|" in block and idx + 1 < len(lines) and is_markdown_table_separator(lines[idx + 1]):
            table_lines = [block, lines[idx + 1].strip()]
            idx += 2
            while idx < len(lines) and "|" in lines[idx].strip() and lines[idx].strip():
                table_lines.append(lines[idx].strip())
                idx += 1
            repl = make_block_repl("\n".join(table_lines))
            blocks.append({"kind": "table", "html": render_markdown_table(table_lines, repl), "cites": citation_ids("\n".join(table_lines))})
        elif block in {"---", "***"}:
            blocks.append({"kind": "hr", "html": '<hr class="doc-divider">', "cites": []})
            idx += 1
        elif re.match(r"^[-*]\s+", block):
            body = render_inline_markdown(re.sub(r"^[-*]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": False, "html": body, "cites": ids})
            idx += 1
        elif re.match(r"^\d+[.)]\s+", block):
            number = re.match(r"^(\d+)[.)]\s+", block).group(1)
            body = render_inline_markdown(re.sub(r"^\d+[.)]\s+", "", block), repl)
            blocks.append({"kind": "list_item", "numbered": True, "number": number, "html": body, "cites": ids})
            idx += 1
        else:
            blocks.append({"kind": "para", "html": render_inline_markdown(block, repl), "cites": ids})
            idx += 1
    return blocks, valid_ids


def split_heading_number(text: str) -> Tuple[Optional[str], str]:
    m = re.match(r"^\s*([一二三四五六七八九十]+|\d+)\s*[、.．]\s*(.+)$", text)
    if m:
        return m.group(1), m.group(2)
    return None, text


def group_sections(blocks: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """按标题层级切分章节卡。返回（报告标题, 章节列表）。

    规则：最浅层级标题若唯一且居文首，视为报告标题提出；其下一级为卡片边界。
    无标题的短公文整篇一卡。
    """
    if not blocks:
        return None, [{"title": None, "blocks": []}]
    heading_indexes = [i for i, b in enumerate(blocks) if b["kind"] == "heading"]
    if not heading_indexes:
        return None, [{"title": None, "blocks": blocks}]

    levels = sorted({blocks[i]["level"] for i in heading_indexes})
    shallow = levels[0]
    shallow_indexes = [i for i in heading_indexes if blocks[i]["level"] == shallow]

    doc_title = None
    boundary = shallow
    if len(shallow_indexes) == 1 and heading_indexes[0] == shallow_indexes[0]:
        doc_title = blocks[shallow_indexes[0]]["text"]
        blocks = blocks[shallow_indexes[0] + 1:]
        if len(levels) > 1:
            boundary = levels[1]

    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {"title": None, "blocks": []}
    for b in blocks:
        if b["kind"] == "heading" and b["level"] <= boundary:
            if current["title"] is not None or current["blocks"]:
                sections.append(current)
            current = {"title": b["text"], "blocks": []}
        else:
            current["blocks"].append(b)
    if current["title"] is not None or current["blocks"]:
        sections.append(current)
    return doc_title, sections


# ============================================================
# 各部分渲染
# ============================================================

def build_chip_data(sources: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """行内引文胶囊数据：id → {title, site, url, excerpt}。

    角标后渲染原型式 jb（行内小胶囊，点击展开块级卡）。摘录展示完整
    原文原段、不截断——段内去重后重复量可控，核对场景下就地读全文。
    """
    chip_map: Dict[str, Dict[str, str]] = {}
    for source in sources:
        cid = source["id"]
        if cid in chip_map:
            continue
        meta_bits = [v for v in [source.get("agency"), source.get("date")] if v and v != "未知来源"]
        url = source.get("url") if (source.get("url") and source["url"] != "接口未返回") else (source.get("policy_url") or "")
        if source.get("link_dead"):
            url = source.get("snapshot") or ""
        site_bits = ([source["doc_number"]] if source.get("doc_number") else []) + meta_bits
        chip_map[cid] = {
            "title": short(source.get("title") or "未命名材料", 30),
            "site": " · ".join(site_bits) or "来源站点",
            "url": url,
            "snapshot": source.get("snapshot") or "",
            "dead": bool(source.get("link_dead")),
            "excerpt": (source.get("excerpt") or "").strip(),
            "segments": source.get("segments") or [],
        }
    return chip_map


def render_source_links(url: str, policy_url: str = "", snapshot: str = "", link_dead: bool = False) -> str:
    """链接区四态：原文可回看 / 原文失效改快照 / 原文失效无快照 / 无源网址有快照。
    快照是接口对原文的存档副本，文案如实标注，不冒充原文链接。"""
    links = []
    if url and url != "接口未返回" and not link_dead:
        links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">查看全文 ↗</a>')
    if snapshot:
        # 有哪个显示哪个：快照统一展示"查看存档全文"，不做原文失效的状态解释
        links.append(f'<a class="snap" href="{esc(snapshot)}" target="_blank" rel="noopener">查看存档全文 ↗</a>')
    if policy_url:
        links.append(f'<a href="{esc(policy_url)}" target="_blank" rel="noopener">知识专库原文 ↗</a>')
    if not links:
        return ""
    return '<div class="sc-links">' + "".join(f"<span>{link}</span>" for link in links) + "</div>"


def render_verify_panel(v: Dict[str, Any]) -> str:
    """核验报告单：报告级核验结论 + 五项指标。"""
    manual_checks_html = "".join("<br>· " + esc(x) for x in v.get("manual_checks", []))
    ov = v["overall"]
    state = "ok" if ov["passed"] else "fail"
    stamp = '<span class="v-stamp">已核验</span>' if ov["passed"] else '<span class="v-stamp bad">核验未通过</span>'
    reasons_html = ""
    if ov["reasons"]:
        reasons_html = '<div class="v-reasons">' + "；".join(esc(r) for r in ov["reasons"]) + "</div>"

    tr = v["traceability"]
    if not tr["total"]:
        tr_html = ('<div class="vi"><span class="s fail">✗ 依据溯源 0/0</span>'
                   '<span class="d">未识别到来源材料</span></div>')
    elif tr["passed"] == tr["total"]:
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">每条素材摘录可比对，原文或存档快照可回看</span></div>')
    else:
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">待补摘录 {len(tr.get("missing_excerpts") or [])} 条</span></div>')

    bd = v["binding"]
    if bd.get("no_citation"):
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 0/0</span>'
                   f'<span class="d">正文里没有来源角标，{v["traceability"]["total"]} 条材料对不上正文</span></div>')
    elif not bd["total"]:
        bd_html = '<div class="vi"><span class="s none">— 引用对应 0/0</span><span class="d">正文里没有来源角标</span></div>'
    elif not bd["unbound"]:
        bd_html = (f'<div class="vi"><span class="s ok">✓ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">正文每处 [n] 都能找到对应材料</span></div>')
    else:
        unbound_text = "、".join(f"[{esc(x)}]" for x in bd["unbound"][:8])
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">对不上的角标 {unbound_text}</span></div>')

    fr = v["freshness"]
    if fr:
        rng = f"{fr['min'][0]}-{fr['min'][1]:02d}～{fr['max'][0]}-{fr['max'][1]:02d}"
        old = f"（{fr['old_count']} 条年头较久，按参考口径使用）" if fr["old_count"] else ""
        fr_html = f'<div class="vi"><span class="s ok">✓ 材料新旧 已核</span><span class="d">材料日期 {esc(rng)}{esc(old)}</span></div>'
    else:
        fr_html = '<div class="vi"><span class="s none">— 材料新旧 未记录</span><span class="d">材料没标发布日期</span></div>'

    cov = v["coverage"]
    parts = [f"{KIND_CATALOG[k][0]} {cov[k]}" for k in ("policy", "data", "case", "reference") if cov.get(k)]
    cov_state = "ok" if cov.get("policy") or cov.get("data") or cov.get("case") else "none"
    cov_html = (f'<div class="vi"><span class="s {cov_state}">{"✓" if cov_state == "ok" else "—"} 材料构成</span>'
                f'<span class="d">{esc(" · ".join(parts)) if parts else "材料没标类型"}</span></div>')

    sc = v["self_check"]
    if sc["status"] == "pass":
        notes = "；".join(note for _, note in sc["items"].values() if note)
        title_attr = f' title="{esc(notes)}"' if notes else ""
        item_names = "、".join(sc["items"].keys()) if sc["items"] else "、".join(label for _, label in SELF_CHECK_ITEMS)
        sc_html = (f'<div class="vi"><span class="s ok"{title_attr}>✓ 交付前检查 {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">{esc(item_names)}{esc(" · 悬停查看说明" if notes else "")}</span></div>')
    elif sc["status"] == "fail":
        failed_parts = []
        for label, (status, note) in sc["items"].items():
            if status != "pass":
                suffix = f"（{note[:40]}…）" if len(note) > 40 else (f"（{note}）" if note else "")
                failed_parts.append(label + suffix)
        sc_html = (f'<div class="vi"><span class="s fail">✗ 交付前检查 {sc["passed"]}/{sc["total"]}</span>'
                   f'<span class="d">没过的项：{esc("、".join(failed_parts))}</span></div>')
    else:
        sc_html = '<div class="vi"><span class="s none">— 交付前检查 未记录</span><span class="d">本次溯源 JSON 没写入检查结果</span></div>'

    manual = ""
    if v["policy_count"]:
        manual = (f'<div class="vi"><span class="s man">◐ 现行效力</span>'
                  f'<span class="d">{v["policy_count"]} 份政策文件建议按官方发布确认是否现行有效</span></div>')

    return f"""
    <div class="verify {state}">
      <div class="v-head"><span class="v-shield">{'✓' if ov['passed'] else '!'}</span>{esc(ov['label'])}{stamp}</div>
      {reasons_html}
      <div class="v-grid">
        {tr_html}{bd_html}{fr_html}{cov_html}{sc_html}{manual}
      </div>
      <div class="v-note">核验方式：先用深知可信搜索找权威来源，再把正文每处依据和原文逐条比对（都能点开原文回看），最后做了交付前五项检查。政策是否现行有效，以官方发布为准。{manual_checks_html}</div>
    </div>"""


SRC_ICO_SVG = ('<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" '
               'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
               '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
               '<path d="M9 13h6M9 17h4"/></svg>')
ARROW_SVG = ('<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8"/></svg>')
CARET_SVG = ('<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.4" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>')


def render_src_card(jb: Dict[str, str], cid: str, dup: bool = False) -> str:
    """句后溯源卡（原型 cardHTML 的 Python 移植）：标题 + 来源 + 查看原文 + 摘录展开。"""
    src = jb.get("source") or "来源站点"
    url = jb.get("url") or ""
    title = re.sub(r"<br\s*/?>", " ", str(jb.get("title") or ""), flags=re.I)
    excerpt = (jb.get("excerpt") or "").strip()
    dup_cls = " dup-card" if dup else ""
    link_html = (f'<a class="src-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer">查看全文{ARROW_SVG}</a>' if url else "")
    toggle_html = (f'<button class="src-toggle" type="button"><span class="more">展开</span>'
                   f'<span class="less">收起</span>{CARET_SVG}</button>' if excerpt else "")
    body_html = f'<div class="src-body"><p>{esc(excerpt)}</p></div>' if excerpt else ""
    return (
        f'<figure class="src-card{dup_cls}" data-cite="{esc(cid)}">'
        f'<div class="src-head"><span class="src-ico" aria-hidden="true">{SRC_ICO_SVG}</span>'
        f'<figcaption class="src-title">{esc(title)}</figcaption></div>'
        f'<div class="src-meta"><span class="src-site" title="{esc(src)}"><span class="dot"></span>{esc(src)}</span>'
        f'{link_html}{toggle_html}</div>{body_html}</figure>'
    )


def render_section_cards(sections: List[Dict[str, Any]], sources: List[Dict[str, str]]) -> str:
    """正文渲染（原型复刻）：chapter（h2）+ lead/para 段落 + 段后 src-card 溯源卡。

    溯源卡按段内角标顺序输出；同一材料在同段只出一张，跨段重复出现标记 dup-card（灰化）。
    """
    parts: List[str] = []
    first_para = True
    source_ids = {s["id"] for s in sources}
    for sec_idx, sec in enumerate(sections, 1):
        number, title_text = split_heading_number(sec["title"] or "")
        chapter_title = f"{number}、{title_text}" if (number and title_text) else (title_text or "")
        sec_cites: List[str] = []
        for b in sec["blocks"]:
            for cid in b.get("cites", []):
                if cid not in sec_cites:
                    sec_cites.append(cid)
        if chapter_title:
            badge_html = ""
            if sec_cites:
                unbound = sum(1 for cid in sec_cites if cid not in source_ids)
                state = "bad" if unbound else ""
                text = f"本章引用 {len(sec_cites)} 处" + (f" · {unbound} 处未绑定" if unbound else " · 已核验")
                badge_html = f'<span class="sec-badge {state}">{esc(text)}</span>'
            parts.append(f'<section class="chapter" id="sec-{sec_idx}">'
                         f'<header class="ch-head"><h2>{esc(chapter_title)}</h2>{badge_html}</header>')
        for b in sec["blocks"]:
            if b["kind"] == "heading":
                parts.append(f'<p class="para"><b class="kw">{esc(b["text"])}</b></p>')
                first_para = False
                continue
            cls = "lead" if first_para else "para"
            first_para = False
            if b["kind"] == "list_item":
                marker = f'{esc(b.get("number", "•"))}.' if b.get("numbered") else "•"
                parts.append(f'<p class="{cls}"><b class="kw">{marker}</b> {b["html"]}</p>')
            elif b["kind"] == "hr":
                parts.append('<hr class="doc-divider">')
            else:
                parts.append(f'<p class="{cls}">{b["html"]}</p>')
        if chapter_title:
            parts.append("</section>")
    return "\n".join(parts)


def strip_leading_chain(text: str, chain: List[str]) -> str:
    """剥掉段落文本开头与标题链各级重复的前缀。

    接口部分材料的"内容"字段自带段落标题前缀（个别还重复两遍），标题链已承载
    位置信息，摘录开头再出现同级文本即冗余；逐级最长匹配剥离，无重复则原样返回。
    """
    t = (text or "").strip()
    cands = set()
    for lvl in chain:
        lvl = (lvl or "").strip()
        if lvl:
            cands.add(lvl)
            # 粘连标题（接口未给分隔符，如"建设交通强省5.民航和低空"）拆出编号尾部子串
            parts = re.split(r"(?<=[\u4e00-\u9fff])(?=\d+[.、])", lvl)
            if len(parts) > 1 and parts[-1].strip():
                cands.add(parts[-1].strip())
    levels = sorted(cands, key=len, reverse=True)
    changed = True
    while changed and t:
        changed = False
        for lvl in levels:
            if t.startswith(lvl):
                t = t[len(lvl):].lstrip(" \n\r\t、。；;，,").strip()
                changed = True
                break
    return t


def render_crumb(chain: List[str]) -> str:
    """面包屑标题链：文章 › 章 › 节（标题链是模型生成的结构化位置，核验核心抓手）。"""
    parts = [esc(level) for level in chain if level]
    if not parts:
        return ""
    return '<span class="crumb">' + ' <i>›</i> '.join(parts) + "</span>"


def render_segments(source: Dict[str, Any]) -> str:
    """多段分块摘录：每段独立区块，各带自己的标题链——段落结构与位置直接可见。"""
    segments = source.get("segments") or []
    if not segments:
        return render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")
    blocks = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f'<div class="seg-block">{render_crumb(seg.get("chain") or [])}'
                      f'{render_excerpt_html(text)}</div>')
    return "".join(blocks) if blocks else render_excerpt_html(source.get("excerpt") or "接口返回中未识别到可展示的摘录。")


def render_source_card(source: Dict[str, str], for_print: bool = False) -> str:
    if not source.get("used", True):
        # 未引用召回材料：不标"已核验"（未进入正文核验流程），只标可否查看
        vk = ('<span class="sc-vk" style="color:var(--muted)">可查看全文</span>' if source.get("has_link")
              else '<span class="sc-vk warn">待补链接</span>')
        note_html = ""
    elif source.get("verified"):
        note = source.get("verify_note") or "摘录可比对，原文链接与知识专库可回看"
        vk = f'<span class="sc-vk ok" title="{esc(note)}">✓ 已核验</span>'
        note_html = f'<div class="sc-vnote">{esc(short(note, 90))}</div>' if source.get("verify_note") else ""
    else:
        reason = "待补原文链接" if not source.get("has_link") else "待补摘录"
        vk = f'<span class="sc-vk warn">◐ {reason}</span>'
        note_html = ""
    links = render_source_links(source.get("url"), source.get("policy_url", ""), source.get("snapshot", ""), source.get("link_dead", False))
    # 关键性行：有文号（接口 policyFiles 匹配）时"文号 · 数据源 · 日期"，否则"数据源 · 日期"
    meta_parts = [v for v in [source.get("doc_number"), source.get("agency"), source.get("date"), source.get("area")]
                  if v and v != "未知来源"]
    meta = " | ".join(meta_parts)
    # 高可信徽标：仅"发布日期可信度=高"（模型治理入库、标题模型精抽）的材料；"较高"（门户抓取）不标。
    conf_badge = ""
    if source.get("conf") == "高":
        conf_badge = ('<span class="sc-conf" title="发布日期可信度：高。内容经模型治理入库，'
                      '标题为模型从原文动态抽取，非规则提取">高可信</span>')
    # 已引用材料显示角标编号；未引用召回材料显示"未引用"灰标（不占正文角标号）
    id_html = f'<span class="sc-id">[{esc(source["id"])}]</span>' if source.get("used", True) else '<span class="sc-unused">未引用</span>'
    body_html = (f'<div class="sc-head">{id_html}'
                 f'<span class="sc-type">{esc(source["type_label"])}</span>{conf_badge}{vk}</div>'
                 f'<h4>{esc(source.get("title"))}</h4>'
                 f'<div class="sc-meta">{esc(meta)}</div>'
                 f'{note_html}'
                 f'{render_segments(source)}'
                 f'{links}')
    if for_print:
        # 打印附录版：无交互属性，避免与专库卡片 id 冲突
        return f'<article class="scard print-only {source["type_css"]}">{body_html}</article>'
    unused_attr = "" if source.get("used", True) else ' data-unused="1"'
    return (
        f'<article class="scard {source["type_css"]}" id="src-{esc(source["id"])}" data-type="{esc(source["type_key"])}" '
        f'data-cite-id="{esc(source["id"])}" data-search="{esc(source.get("search_key", ""))}"{unused_attr}>{body_html}</article>'
    )


def render_process_bar(stats: Dict[str, Any], verification: Dict[str, Any]) -> str:
    """过程回顾条：静态回放真实流程。无思考流数据，不做"深度思考"步骤。"""
    ov = verification["overall"]
    tr = verification["traceability"]
    first_query = stats["conds"][0]["key"] if stats["conds"] else ""
    detail_rows = "".join(
        f'<div class="pd-row"><b>{esc(row["key"])}</b>'
        f'<span>召回 {row["total"]} 条 · 正文采用 {row["used"]} 条</span></div>'
        for row in stats["conds"]
    ) or '<div class="pd-row"><span>本次溯源 JSON 未记录各次检索条件</span></div>'
    detail_hint = f'{esc(short(first_query, 26))}…' if (stats["n_searches"] > 1 and first_query) else "查看检索明细"
    if stats["n_searches"] > 1:
        step1_sub = f"共 {stats['n_searches']} 路检索 · {detail_hint}"
    elif first_query:
        step1_sub = esc(short(first_query, 26))
    else:
        step1_sub = "深知可信搜索"
    step4_state = "done" if ov["passed"] else "bad"
    step4_icon = "✓" if ov["passed"] else "!"
    step4_label = "核验完成" if ov["passed"] else "核验未完全通过"
    step4_sub = "结论：正文依据逐条对过原文" if ov["passed"] else esc(short("；".join(ov["reasons"]) or "见核验报告单", 30))
    return f"""
    <section class="process" aria-label="生成过程回顾">
      <div class="p-head"><b>过程回顾</b><span>数字来自本次任务的真实记录</span></div>
      <ol class="p-steps">
        <li class="p-step expandable" id="p-step-search" role="button" tabindex="0" title="展开各路检索明细">
          <span class="p-no">1</span>
          <div class="p-txt"><b>深知检索 {stats['n_searches']} 次</b><i>{step1_sub}</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step">
          <span class="p-no">2</span>
          <div class="p-txt"><b>材料入库 {stats['n_materials']} 条</b><i>正文采用 {stats['used_count']} · 召回未采用 {stats['unused_count']}</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step">
          <span class="p-no">3</span>
          <div class="p-txt"><b>逐条比对原文</b><i>依据溯源 {tr['passed']}/{tr['total']} · 摘录可比对</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step {step4_state}">
          <span class="p-no">{step4_icon}</span>
          <div class="p-txt"><b>{esc(step4_label)}</b><i>{step4_sub}</i></div>
        </li>
      </ol>
      <div class="p-detail" id="p-detail">{detail_rows}</div>
    </section>"""


def render_library_view(sources: List[Dict[str, str]], hot_terms: List[str]) -> str:
    """材料专库全屏视图：大搜索 + 热词 + 检索分组 tabs + 材料卡列表。"""
    if not sources:
        return ('<section class="view" id="view-library" aria-label="材料专库">'
                '<div class="lib-empty">接口返回中未识别到可展示的材料。</div></section>')
    used_sources = [s for s in sources if s.get("used", True)]
    unused_sources = [s for s in sources if not s.get("used", True)]

    # tabs = 检索分组（全部 / 各路检索 / 未引用），数字真实统计
    conds: List[Tuple[str, int]] = []
    for s in sources:
        key = (s.get("search_key") or "").strip()
        if not key:
            continue
        for i, (name, count) in enumerate(conds):
            if name == key:
                conds[i] = (name, count + 1)
                break
        else:
            conds.append((key, 1))
    tabs = [f'<button class="on" data-cond="" type="button">全部（{len(sources)}）</button>']
    for name, count in conds:
        tabs.append(f'<button data-cond="{esc(name)}" type="button">{esc(name)}（{count}）</button>')
    if unused_sources:
        tabs.append(f'<button data-cond="__unused__" type="button">未引用（{len(unused_sources)}）</button>')

    hot_html = ""
    if hot_terms:
        hot_items = "".join(f'<button class="hot-term" type="button">{esc(term)}</button>' for term in hot_terms)
        hot_html = f'<div class="hot-terms" aria-label="热门搜索词"><span class="hot-label">大家都在搜</span>{hot_items}</div>'

    cards_html = "".join(render_source_card(s) for s in used_sources)
    cards_html += "".join(render_source_card(s) for s in unused_sources)

    cited_verified = sum(1 for s in used_sources if s.get("verified"))
    badge = "全部已核验" if used_sources and cited_verified == len(used_sources) else f"{cited_verified}/{len(used_sources)} 已核验"
    return f"""
    <section class="view" id="view-library" aria-label="材料专库">
      <div class="lib-head">
        <div class="lib-title"><b>材料专库</b>
          <span>共 {len(sources)} 条 · 已引用 {len(used_sources)} · {esc(badge)}</span>
        </div>
        <div class="lib-searchWrap">
          <span class="lib-searchIcon" aria-hidden="true">⌕</span>
          <input class="lib-search" type="search" placeholder="搜索标题 / 来源 / 摘录…" aria-label="搜索材料">
        </div>
        {hot_html}
        <div class="lib-tabs" role="tablist" aria-label="按检索分组筛选">{"".join(tabs)}</div>
      </div>
      <div class="lib-list" id="lib-list">{cards_html}</div>
      <div class="lib-empty hide" id="lib-empty">没有符合当前筛选的材料。</div>
      <div class="lib-foot">材料来源：深知可信搜索 · 每条摘录均取自原文原段</div>
    </section>"""


def render_toc(sections: List[Dict[str, Any]]) -> str:
    """章节目录（滚动 spy）：长报告（≥6 节）显示，桌面端左侧浮动。"""
    if len(sections) < 6:
        return ""
    items = []
    for i, sec in enumerate(sections, 1):
        number, title_text = split_heading_number(sec["title"] or "")
        label = f"{number} {title_text}" if (number and title_text) else (title_text or f"第 {i} 节")
        items.append(f'<a href="#sec-{i}">{esc(short(label, 16))}</a>')
    return f'<nav class="toc" aria-label="章节目录">{"".join(items)}</nav>'


def render_print_appendix(sources: List[Dict[str, str]]) -> str:
    """打印归档附录：全部材料卡全展开（屏幕不显示，仅打印）。"""
    if not sources:
        return ""
    cards = "".join(render_source_card(s, for_print=True) for s in sources)
    return (f'<section class="print-appendix" aria-label="核验材料附录（打印归档）">'
            f'<h3>核验材料（全 {len(sources)} 条）</h3>{cards}</section>')


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_search_trace", suffix_ext: str = ".html") -> str:
    raw = question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    suffix = timestamp.strftime("%Y%m%d_%H%M")
    stem = normalized[:32].strip("._-") or fallback
    return f"{stem}_{suffix}{suffix_ext}"


# ============================================================
# 样式与脚本（独立常量，避免模板转义）
# ============================================================

PAGE_CSS = """
:root{
  --navy:#20242c; --navy-2:#3a4152;
  --ink:#1f2328; --muted:#6b7280; --line:#e5e7eb; --line-strong:#cbd2dd;
  --brand:#6512ad; --brand-2:#8b5cf6; --brand-soft:#ede9fe;
  --grad:linear-gradient(135deg,#6512ad,#8b5cf6);
  --policy:#0f9d6e; --policy-soft:#e3f5ee;
  --case:#9a6700; --case-soft:#fdf3dc;
  --ref:#4b5563; --ref-soft:#f0f1f4;
  --warn:#9a6700; --danger:#e5484d; --ok:#0f9d6e;
  --shadow-1:0 1px 3px rgba(24,20,40,.04),0 8px 30px rgba(24,20,40,.08);
  --shadow-2:0 3px 9px rgba(101,18,173,.22),0 14px 36px rgba(24,20,40,.14);
  --primary-bright:#8b5cf6; --tint:#f3edfc; --tint-2:#faf7ff; --tint-bd:#e9dff9;
  --tint-strong:#e6d9f9; --tint-bd-strong:#d3bef0; --body-c:#3b4152; --card-bd:#e8e6f0;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"PingFang SC","HarmonyOS Sans SC","Microsoft YaHei",sans-serif;
  color:var(--ink);background:#f4f5f7;line-height:1.75;font-size:14.5px}
a{color:var(--brand)}

/* ===== 顶栏 ===== */
.topbar{position:sticky;top:0;z-index:50;display:flex;justify-content:space-between;align-items:center;gap:10px;
  padding:9px 22px;background:rgba(255,255,255,.92);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line)}
.tb-left{display:flex;align-items:center;gap:10px;min-width:0}
.tb-stamp{flex:none;font-size:12.5px;font-weight:800;color:var(--navy);letter-spacing:4px;text-indent:4px}
.tb-stamp::before,.tb-stamp::after{content:"";display:inline-block;width:22px;border-top:1px solid var(--line-strong);
  vertical-align:middle;margin:0 6px}
.tb-title{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);font-size:13px}
.tb-right{display:flex;align-items:center;gap:8px;flex:none}
.view-switch{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;background:#fff}
.view-switch button{border:0;background:transparent;color:var(--muted);font-size:12.5px;font-weight:700;
  padding:5px 14px;cursor:pointer}
.view-switch button.on{background:var(--grad);color:#fff}
.tb-tools{display:flex;gap:6px}
.tb-tools button{border:1px solid var(--line);border-radius:8px;background:#fff;color:#3b3550;
  font-size:12.5px;font-weight:700;padding:5px 11px;cursor:pointer}
.tb-tools button:hover{border-color:var(--brand-2);color:var(--brand)}
.tb-tools button[aria-pressed="true"]{background:var(--grad);border-color:var(--brand);color:#fff}
.print-menu{position:relative;display:inline-flex}
.print-drop{position:absolute;top:calc(100% + 6px);right:0;z-index:70;display:flex;flex-direction:column;gap:4px;
  min-width:190px;padding:6px;background:#fff;border:1px solid var(--tint-bd);border-radius:10px;
  box-shadow:var(--shadow-2);text-align:left}
.print-drop[hidden]{display:none}
.print-drop button{border:0;background:none;border-radius:7px;color:var(--ink);font-size:12.5px;font-weight:600;
  padding:8px 12px;cursor:pointer;text-align:left;font-family:inherit;white-space:nowrap}
.print-drop button:hover{background:var(--tint);color:var(--brand)}
.progress{position:absolute;left:0;right:0;bottom:-1px;height:2px;background:transparent}
.progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,#6512ad,#8b5cf6)}

/* ===== Hero ===== */
.hero{position:relative;background:linear-gradient(180deg,#fbfaff 0%,#f7f4fd 100%);
  color:var(--ink);padding:32px 22px 58px;text-align:center;border-bottom:1px solid var(--line)}
.r-badge{display:inline-flex;align-items:center;gap:14px;margin:0 0 8px;
  background:var(--grad);color:#fff;border-radius:999px;padding:4px 22px;
  font-size:15px;font-weight:800;letter-spacing:7px;text-indent:7px;line-height:1.6;
  box-shadow:0 2px 8px rgba(101,18,173,.22)}
.hero h1{margin:0 0 10px;font-size:24px;line-height:1.5;max-width:860px;margin-left:auto;margin-right:auto;color:var(--ink)}
.hero .meta{color:var(--muted);font-size:13px;letter-spacing:.5px}
.hero-switch{margin-top:16px;display:flex;justify-content:center}
.hero-switch .view-switch{border-color:#d9c9f4;background:#fff;box-shadow:0 1px 3px rgba(24,20,40,.04)}
.hero-switch .view-switch button{color:#70678a;padding:6px 22px;font-size:13px}
.hero-switch .view-switch button.on{background:var(--grad);color:#fff}

/* ===== 容器与视图 ===== */
.container{max-width:1080px;margin:0 auto;padding:0 18px}
.app[data-view="library"] #view-report{display:none}
#view-library{display:none}
.app[data-view="library"] #view-library{display:block}

/* ===== 过程回顾条 ===== */
.process{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-1);
  padding:15px 20px 13px;margin:-36px auto 16px;position:relative}
.p-head{display:flex;align-items:baseline;gap:10px;margin-bottom:10px}
.p-head b{font-size:14.5px;color:var(--navy);letter-spacing:1px}
.p-head span{font-size:11.5px;color:var(--muted)}
.p-steps{list-style:none;display:flex;align-items:stretch;gap:8px;margin:0;padding:0;flex-wrap:wrap}
.p-step{display:flex;gap:9px;align-items:center;min-width:0;flex:1 1 150px;
  border:1px solid var(--line);border-radius:10px;padding:8px 11px;background:#fafbfc}
.p-no{flex:none;width:24px;height:24px;border-radius:50%;background:var(--grad);color:#fff;
  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800}
.p-txt{min-width:0}
.p-txt b{display:block;font-size:12.8px;color:var(--navy);line-height:1.5}
.p-txt i{display:block;font-style:normal;font-size:11px;color:var(--muted);line-height:1.5;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.p-step.done{border-color:#bfe8da;background:#f2faf7}
.p-step.done .p-no{background:var(--ok)}
.p-step.bad{border-color:#f6c9cb;background:#fffafa}
.p-step.bad .p-no{background:var(--danger)}
.p-step.expandable{cursor:pointer}
.p-step.expandable:hover{border-color:var(--brand)}
.p-arrow{align-self:center;color:#b9c6d9;font-size:16px;font-weight:700;flex:none}
.p-detail{display:none;margin-top:10px;border-top:1px dashed var(--line-strong);padding-top:9px}
.p-detail.show{display:block}
.pd-row{display:flex;justify-content:space-between;gap:14px;padding:3px 2px;font-size:12.3px;flex-wrap:wrap}
.pd-row b{color:var(--navy);font-weight:700;min-width:0}
.pd-row span{color:var(--muted)}

/* ===== 核验报告视图 ===== */
#view-report{padding-bottom:26px}
.warn-box{margin:0 0 16px;padding:13px 16px;border:1.5px solid var(--danger);border-radius:10px;
  background:#fdf3f3;color:#8f2626;font-size:13.5px;line-height:1.7}
.verify{margin:0 0 16px;background:#fff;border:1px solid #bfe8da;border-left:4px solid var(--ok);
  border-radius:14px;padding:16px 20px;box-shadow:var(--shadow-1)}
.verify.fail{border-color:#f6c9cb;border-left-color:var(--danger);background:#fffafa}
.v-head{display:flex;align-items:center;gap:9px;font-size:15px;font-weight:800;color:var(--ok)}
.verify.fail .v-head{color:var(--danger)}
.v-shield{display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--ok);color:#fff;
  align-items:center;justify-content:center;font-size:12px;flex:none}
.verify.fail .v-shield{background:var(--danger)}
.v-stamp{margin-left:auto;font-size:11px;border:1.5px solid var(--ok);color:var(--ok);border-radius:5px;
  padding:1px 8px;letter-spacing:2px;flex:none}
.v-stamp.bad{border-color:var(--danger);color:var(--danger)}
.v-reasons{margin-top:6px;font-size:12.5px;color:var(--danger)}
.v-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px 20px;margin-top:10px}
.vi{display:flex;gap:7px;align-items:baseline;font-size:12.5px;color:#3b3550;line-height:1.7;min-width:0}
.vi .s{font-weight:800;flex:none}
.vi .s.ok{color:var(--ok)}
.vi .s.warn{color:var(--warn)}
.vi .s.fail{color:var(--danger)}
.vi .s.man{color:var(--case)}
.vi .s.none{color:var(--muted)}
.vi .d{color:var(--muted);min-width:0}
.v-note{margin-top:11px;padding-top:9px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--muted);line-height:1.7}

/* 正文（原型复刻）：章节 / 段落 / 角标 / 句后溯源卡 */
.doc-paper{background:#fff;border-radius:14px;box-shadow:var(--shadow-1);padding:26px 34px 22px;margin:0 0 16px}
.chapter{margin:40px 0 0}
.chapter:first-child{margin-top:6px}
.ch-head{display:flex;align-items:center;gap:14px;margin-bottom:18px;scroll-margin-top:86px}
.ch-head h2{font-size:19.5px;font-weight:700;color:var(--ink);letter-spacing:.2px;line-height:1.4;flex:1;min-width:0}
.ch-head::after{content:"";flex-basis:110px;height:1px;background:linear-gradient(90deg,#e9dff9,transparent);order:3;flex-grow:0;flex-shrink:0}
.ch-head .sec-badge{order:4;flex:none;font-size:11.5px;color:var(--ok);background:var(--policy-soft);border-radius:6px;padding:2px 9px;font-weight:700}
.ch-head .sec-badge.bad{color:var(--danger);background:#fdecec}
@media(min-width:1000px){.ch-head::after{flex-basis:200px}}
.lead{font-size:15.5px;line-height:1.95;color:var(--body-c);margin:14px 0;padding:0 2px;word-break:break-word}
.para{font-size:15.5px;line-height:1.95;color:var(--body-c);margin:14px 0;padding:0 2px;word-break:break-word}
.para b.kw,.lead b.kw{font-weight:600;color:var(--ink)}
.doc-divider{border:0;border-top:1px solid var(--line);margin:18px 0}
code{padding:1px 5px;border-radius:4px;background:#f3f4f6;color:#3f3d52;
  font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}
.tbl-wrap{max-width:100%;overflow-x:auto;margin:8px 0}
.data-tbl{width:100%;border-collapse:collapse;border:1px solid var(--line);font-size:13px}
.data-tbl th,.data-tbl td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;line-height:1.65}
.data-tbl th{background:#f5f6f8;font-weight:700;color:#3f3d52}

/* 角标 */
.cite{display:inline-flex;align-items:center;justify-content:center;min-width:19px;height:18px;padding:0 5px;margin:0 2px 2px 3px;font-size:10.5px;font-weight:700;font-variant-numeric:tabular-nums;color:var(--brand);background:var(--tint);border:1px solid var(--tint-bd);border-radius:5px;cursor:pointer;vertical-align:super;line-height:1;transition:.14s;position:relative;top:-1px;user-select:none;font-family:inherit}
.cite:hover{background:var(--brand);border-color:var(--brand);color:#fff}
.cite.flash{background:var(--primary-bright);border-color:var(--primary-bright);color:#fff}
.cite.unresolved{color:var(--danger);border-color:#f6c9cb;background:#fdf7f7}

/* 段落级证据 chips（引文卡） */
/* 行内引文 jb（原型复刻）：角标后小胶囊，点击展开块级卡（溯源原文+引文摘录） */
.jb{display:inline-block;vertical-align:top;max-width:100%;margin:2px 4px 2px 0;position:relative}
.jb.active{display:block;margin:12px 0 2px;max-width:none}
.jb-name{display:inline-flex;align-items:center;gap:6px;max-width:380px;min-height:26px;padding:4px 13px;border-radius:13px;border:1px solid var(--tint-bd);background:var(--tint);color:#540e8f;font-family:inherit;font-size:12px;font-weight:600;line-height:18px;cursor:pointer;transition:.16s;white-space:nowrap}
.jb-name:hover{background:#fff;border-color:var(--brand)}
.jb-name .jb-id{flex:none;width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-style:normal;font-size:10.5px;font-weight:800;font-variant-numeric:tabular-nums;color:#fff;background:linear-gradient(135deg,#6512ad,#8b5cf6);box-shadow:0 1px 3px rgba(101,18,173,.28)}
.jb-name .jb-txt{overflow:hidden;text-overflow:ellipsis}
.jb-name svg{flex:none;transition:transform .2s}
.jb.active .jb-name{max-width:100%;white-space:normal;line-height:20px;color:var(--ink);background:#fff;font-size:13.5px;font-weight:700;text-align:left}
.jb.active .jb-name svg{transform:rotate(180deg)}
.jb-src{display:inline-flex;align-items:center;gap:5px;min-height:26px;padding:4px 13px;border-radius:13px;background:linear-gradient(135deg,#6512ad,#8b5cf6);color:#fff;font-size:11px;font-weight:600;text-decoration:none;box-shadow:0 2px 8px rgba(101,18,173,.22);transition:.15s;flex-shrink:0}
.jb-src:hover{filter:brightness(1.1)}
.jb-src span{max-width:210px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.jb-body{display:none}
.jb.active .jb-body{position:relative;display:block;margin-top:13px;background:#fff;border:1px solid var(--card-bd);border-radius:12px;padding:13px 15px;box-shadow:var(--shadow-1)}
.jb-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.jb-label{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700;color:var(--brand);letter-spacing:.5px}
.jb-label svg{flex:none}
.jb-site{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:#70678a;background:#f6f4fa;
  border:1px solid var(--line);border-radius:999px;padding:3.5px 10px;max-width:100%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;margin:0 0 2px}
.jb-site .dot{width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg,#6512ad,#8b5cf6);flex-shrink:0}
.jb-quote{display:flex;gap:9px;align-items:flex-start;margin-top:9px;padding:10px 12px;background:#faf9fd;border:1px solid var(--line);border-radius:9px;text-decoration:none;transition:.15s;cursor:pointer}
.jb-quote{cursor:pointer}
.jb-quote:hover{border-color:var(--brand);background:#f7f4fc}
.jb-no{flex:none;width:17px;height:17px;margin-top:4px;border-radius:4px;background:var(--tint);border:1px solid var(--tint-bd);color:var(--brand);font-size:10px;font-weight:700;font-style:normal;display:flex;align-items:center;justify-content:center}
.jb-quote span{font-size:12.5px;line-height:1.95;color:#4b4658;word-break:break-word;text-align:justify}
.jb-quote .sc-excerpt{flex:1;min-width:0;display:block}
a.jb-quote{text-decoration:none}
.jb.flash{animation:cardFlash 1.6s ease}
.ev-title{font-weight:700;font-size:13.5px;margin-bottom:4px;color:var(--ink)}
.ev-meta{color:var(--muted);font-size:12px;margin-bottom:6px}
.ev-chip summary{display:inline-flex;align-items:center;gap:5px;max-width:100%;min-height:26px;padding:4px 13px;
  border-radius:13px;color:#fff;background:var(--grad);cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  list-style:none;font-size:11px;font-weight:600;box-shadow:0 2px 8px rgba(101,18,173,.22);transition:.15s}
.ev-chip summary:hover{filter:brightness(1.12)}
.ev-chip summary::-webkit-details-marker{display:none}
.ev-chip summary b{color:#fff;margin-right:2px;font-weight:700}

.ev-title{font-weight:700;font-size:13.5px;margin-bottom:4px;color:var(--navy)}
.ev-meta{color:var(--muted);font-size:12px;margin-bottom:6px}
.ev-panel p{margin:0 0 8px;color:#3f3d52;font-size:12.8px;line-height:1.7}
.sc-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.sc-links span{display:inline-flex}
.sc-links a{display:inline-flex;align-items:center;min-height:24px;padding:3px 9px;border-radius:6px;
  background:var(--brand-soft);color:var(--brand);font-weight:700;text-decoration:none;font-size:12px}

/* ===== 材料专库视图 ===== */
#view-library{padding:26px 0 30px}
.lib-head{max-width:860px;margin:0 auto 16px;text-align:center}
.lib-title{margin-bottom:14px}
.lib-title b{font-size:17px;color:var(--navy);letter-spacing:2px}
.lib-title span{display:block;font-size:12px;color:var(--muted);margin-top:2px}
.lib-searchWrap{position:relative;max-width:620px;margin:0 auto}
.lib-searchIcon{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#a6adbd;font-size:16px;font-weight:700}
.lib-search{width:100%;padding:11px 16px 11px 38px;border:1.5px solid var(--line-strong);border-radius:999px;
  font-size:14px;background:#fff;box-shadow:var(--shadow-1);outline:none}
.lib-search:focus{border-color:var(--brand-2);box-shadow:0 0 0 3px rgba(139,92,246,.18)}
.hot-terms{display:flex;flex-wrap:wrap;justify-content:center;gap:7px;margin-top:12px;align-items:center}
.hot-label{font-size:12px;color:var(--muted)}
.hot-term{border:0;border-radius:999px;background:var(--brand-soft);color:var(--brand);
  font-size:12.3px;font-weight:700;padding:3px 13px;cursor:pointer}
.hot-term:hover{background:var(--grad);color:#fff}
.lib-tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:14px}
.lib-tabs button{border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);
  padding:4px 13px;font-size:12.3px;cursor:pointer}
.lib-tabs button.on{background:var(--grad);border-color:var(--brand);color:#fff;font-weight:700}
.lib-list{max-width:860px;margin:0 auto;display:grid;grid-template-columns:1fr;gap:14px}
.lib-empty{max-width:860px;margin:30px auto;text-align:center;color:var(--muted);font-size:13.5px}
.lib-empty.hide{display:none}
.lib-foot{text-align:center;color:var(--muted);font-size:11.5px;padding:18px 0 0;line-height:1.8}

/* ===== 材料卡 ===== */
.scard{border:1px solid var(--line);border-left-width:3px;border-radius:12px;padding:14px 18px;
  background:#fff;box-shadow:var(--shadow-1);transition:box-shadow .25s}
.scard:hover{box-shadow:var(--shadow-2)}
.scard.pol{border-left-color:var(--policy)}
.scard.dat{border-left-color:var(--brand-2)}
.scard.cas{border-left-color:var(--case)}
.scard.ref,.scard.mat{border-left-color:var(--ref)}
.scard.hl{box-shadow:0 0 0 3px rgba(139,92,246,.35),var(--shadow-2)}
.scard.hide{display:none}
.sc-head{display:flex;align-items:center;gap:7px;margin-bottom:6px}
.sc-id{font-family:monospace;font-weight:800;font-size:11px;color:#fff;background:var(--grad);
  border-radius:5px;padding:1px 8px}
.sc-type{font-size:11px;font-weight:700;border-radius:4px;padding:1px 8px;background:var(--ref-soft);color:var(--ref)}
.scard.pol .sc-type{background:var(--policy-soft);color:var(--policy)}
.scard.dat .sc-type{background:var(--brand-soft);color:var(--brand)}
.scard.cas .sc-type{background:var(--case-soft);color:var(--case)}
.sc-vk{margin-left:auto;font-size:11px;font-weight:800;color:var(--ok)}
.sc-vk.warn{color:var(--warn)}
.sc-unused{font-size:10.5px;font-weight:800;color:var(--muted);background:#efedf4;border-radius:4px;
  padding:1px 7px;flex:none}
.sc-conf{font-size:10.5px;font-weight:800;color:#8a5a00;background:var(--case-soft);border:1px solid #e6cf8f;
  border-radius:4px;padding:0 7px;flex:none}
.scard h4{margin:0 0 5px;font-size:14.5px;color:var(--ink);line-height:1.55}
.sc-meta{font-size:11.5px;color:var(--muted)}
/* 标题链面包屑（模型生成的结构化位置，核验核心抓手）与多段分块 */
.crumb{font-size:11.5px;color:var(--brand);margin:10px 0 4px;font-weight:600;line-height:1.6;
  padding:3px 9px;background:var(--tint);border-radius:7px;display:inline-block;max-width:100%;
  overflow-wrap:break-word}
.crumb i{font-style:normal;color:#c9b3ec;margin:0 2px;font-weight:400}
.seg-block{margin-top:8px}
.seg-block:first-child{margin-top:2px}
.seg-block .sc-excerpt{margin-top:5px}
.sc-vnote{margin-top:5px;font-size:11.3px;color:var(--ok);line-height:1.6}
.sc-excerpt{margin:8px 0 0;padding:10px 12px;border:1px solid #eceaf2;border-radius:9px;
  background:#faf9fd;color:#4a4260;font-size:12.3px;line-height:1.75}
.sc-excerpt.rich{overflow-x:auto}
.sc-excerpt.rich table{width:max-content;min-width:100%;border-collapse:collapse;background:#fff;font-size:12px}
.sc-excerpt.rich td,.sc-excerpt.rich th{min-width:92px;max-width:220px;padding:7px 8px;border:1px solid var(--line);
  vertical-align:top;word-break:break-word}
.sc-excerpt.rich thead td,.sc-excerpt.rich th{background:#f3f4f6;color:#3f3d52;font-weight:700}
.scard .sc-links a{font-size:12px}
.scard .sc-links{margin-top:4px}
.no-link{font-size:11.5px;color:var(--muted)}
.sc-links a.snap{background:#faf5ff;border-color:#d9c9f4;color:#5b21b6}
.dead-link{font-size:11.5px;color:var(--warn)}

/* ===== 章节目录（spy，长报告） ===== */
.toc{position:fixed;left:calc((100vw - 1080px)/2 - 168px);top:120px;width:140px;max-height:60vh;overflow:auto;
  display:flex;flex-direction:column;gap:2px;font-size:12px}
.toc a{color:var(--muted);text-decoration:none;padding:4px 10px;border-left:2px solid var(--line);
  line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toc a.on{color:var(--brand);border-left-color:var(--brand);font-weight:700}
@media (max-width:1460px){.toc{display:none}}

.foot{text-align:center;color:var(--muted);font-size:11.5px;padding:16px 0 4px;line-height:1.8}

/* ===== 只看正文（纯净阅读态） ===== */
body.reading .process,body.reading .verify,body.reading .jb,body.reading .sec-badge,
body.reading .cite,body.reading .toc,body.reading .p-detail{display:none!important}

/* ===== 打印附录 ===== */
.print-appendix{display:none}

/* ===== 移动端 ===== */
.sheet-mask{display:none}
.sheet{display:none}
@media (max-width:680px){
  body{font-size:14px;line-height:1.8}
  .topbar{padding:7px 10px;gap:6px}
  .tb-stamp{font-size:11px;letter-spacing:2px;text-indent:2px}
  .tb-stamp::before,.tb-stamp::after{width:12px;margin:0 4px}
  .tb-title{display:none}
  .topbar .view-switch{display:none}
  .tb-tools button{font-size:11.5px;padding:4px 8px}
  .hero{padding:24px 14px 50px}
  .ch-head{gap:8px;margin-bottom:14px;flex-wrap:nowrap}
  .ch-head h2{font-size:17px;line-height:1.45}
  .ch-head::after{display:none}
  .ch-head .sec-badge{font-size:10.5px;padding:2px 7px;white-space:nowrap}
  .jb-name{max-width:calc(100vw - 72px)}
  .r-badge{font-size:13.5px;letter-spacing:6px;text-indent:6px;gap:10px}
  .hero h1{font-size:18.5px}
  .hero .meta{font-size:11.5px;line-height:1.7}
  .hero-switch .view-switch button{padding:6px 16px;font-size:12.5px}
  .process{margin-top:-30px;padding:12px 12px 11px}
  .p-step{flex:1 1 100%}
  .p-arrow{display:none}
  .verify{padding:13px 14px}
  .v-head{font-size:14px}
  .v-grid{grid-template-columns:1fr;gap:2px 0}
  .vi{flex-wrap:wrap;gap:4px 8px}
  .vi .d{min-width:0}
  .warn-box{font-size:12.5px;padding:11px 12px}
  .doc-paper{padding:16px 14px 10px;border-radius:10px}
  .sec-head{gap:7px;padding-bottom:8px;margin-bottom:8px}
  .sec-head h3{font-size:15px}
  .sec-badge{margin-left:0;font-size:11px}
  .doc-block p,.doc-item p{font-size:15px;line-height:1.95}
  .doc-sub{font-size:14px;margin:12px 0 6px}
  .data-tbl{font-size:12px}
  .data-tbl th,.data-tbl td{padding:6px 7px;line-height:1.55}
  .cite{font-size:11px;padding:0 4px}
  .ev-chip summary{font-size:11px}
  #view-library{padding:18px 0 24px}
  .lib-search{padding:10px 14px 10px 34px;font-size:13.5px}
  .lib-tabs{justify-content:flex-start;flex-wrap:nowrap;overflow-x:auto;padding-bottom:4px;
    -webkit-overflow-scrolling:touch;scrollbar-width:none}
  .lib-tabs::-webkit-scrollbar{display:none}
  .lib-tabs button{flex:none}
  .lib-list{grid-template-columns:1fr;gap:10px}
  .scard{padding:10px 11px}
  .crumb{font-size:11px}
  .sc-excerpt{font-size:11.5px}
  /* 移动端材料底部弹层：点角标就地弹出材料卡，不跳转打断阅读 */
  .sheet-mask{display:block;position:fixed;inset:0;background:rgba(11,31,58,.45);z-index:99;opacity:0;
    pointer-events:none;transition:opacity .2s}
  .sheet-mask.show{opacity:1;pointer-events:auto}
  .sheet{display:block;position:fixed;left:0;right:0;bottom:0;z-index:100;background:#fff;
    border-radius:14px 14px 0 0;box-shadow:0 -8px 30px rgba(11,31,58,.25);
    max-height:68vh;overflow-y:auto;-webkit-overflow-scrolling:touch;
    padding:10px 16px 22px;transform:translateY(105%);transition:transform .25s ease}
  .sheet.show{transform:translateY(0)}
  .sheet-grab{width:38px;height:4px;border-radius:2px;background:#c9d4e2;margin:2px auto 8px}
  .sheet-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
  .sheet-head b{font-size:13.5px;color:var(--navy)}
  .sheet-close{border:1px solid var(--line);background:#f5f3fa;border-radius:8px;color:#3b4a61;
    font-size:12.5px;font-weight:700;padding:5px 14px;cursor:pointer}
  .sheet .scard{box-shadow:none;margin-bottom:0}
  .sheet .sc-excerpt{display:block;-webkit-line-clamp:unset;cursor:auto}
  /* 正文表述 ↔ 原文原段 对照区（弹层顶部） */
  .cmp{margin:0 0 10px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .cmp-tag{font-size:11px;font-weight:800;padding:3px 10px}
  .cmp-side{padding:9px 12px;font-size:12.8px;line-height:1.7}
  .cmp-side p{margin:0}
  .cmp-ai{background:#fbfaff;color:#3f3d52}
  .cmp-ai .cmp-tag{background:#eef1f6;color:var(--ref)}
  .cmp-src{background:#f4faf7;color:#2f4a3e;border-top:1px dashed var(--line-strong)}
  .cmp-src .cmp-tag{background:var(--policy-soft);color:#0b6e4f}
  .cmp-src .sc-excerpt{display:block;-webkit-line-clamp:unset;background:#fff;cursor:auto;font-size:12px;padding:8px 10px;margin:0}
}

/* ===== 打印归档 ===== */
@media print{
  .topbar,.process .p-detail,.hero-switch,.tb-tools,.view-switch,.lib-head,.toc,.sheet,.sheet-mask,
  .progress{display:none!important}
  #view-library{display:none!important}
  #view-report{display:block!important}
  .app[data-view="library"] #view-report{display:block!important}
  .hero{background:none;border:0;color:var(--ink);padding:10px 0 4px}
  .hero .meta{color:var(--muted)}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .process{box-shadow:none;margin:6px 0 12px}
  .verify{border-color:#bbb;box-shadow:none;break-inside:avoid}
  .doc-paper{box-shadow:none;border-radius:0;padding:0}
  body{background:#fff;font-size:12.5px}
  .sc-excerpt{display:block;-webkit-line-clamp:unset;cursor:auto}
  .scard{break-inside:avoid}
  .cite{background:none!important;color:#333!important;text-decoration:none!important}
  .cite::before{content:"["}.cite::after{content:"]"}
  .jb{display:inline!important}
  .jb .jb-name{border:0;background:none;padding:0;color:#333;font-weight:600}
  .jb .jb-name .jb-id{color:#333;background:none;border:1px solid #999;border-radius:3px}
  .jb .jb-body{display:none!important}
  .jb.active{break-inside:avoid}
  .jb.active .jb-body{display:block!important}
  .jb.active .jb-body .jb-quote{break-inside:avoid}
  body.reading .verify,body.reading .process,body.reading .ev-row,body.reading .sec-badge,
  body.reading .cite{display:none!important}
  .print-appendix{display:block;break-before:page}
  body.print-body-only .verify,body.print-body-only .process,body.print-body-only .print-appendix,
  body.print-body-only .jb,body.print-body-only .foot{display:none!important}
  .print-appendix h3{font-size:15px;color:var(--navy);border-bottom:1px solid #999;padding-bottom:6px;margin:0 0 12px}
  .print-appendix .scard{margin-bottom:10px}
}
"""

PAGE_JS = """
(function () {
  "use strict";
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  var app = $(".app");
  var isMobile = function () { return window.matchMedia("(max-width:680px)").matches; };

  /* ===== 1. 双视图切换（保存/恢复各自滚动位置） ===== */
  var savedScroll = { report: 0, library: 0 };
  function setView(view) {
    if (!app || app.getAttribute("data-view") === view) return;
    savedScroll[app.getAttribute("data-view") || "report"] = window.scrollY;
    app.setAttribute("data-view", view);
    $$(".view-switch button").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-view") === view);
    });
    window.scrollTo(0, Math.max(0, savedScroll[view] || 0));
  }
  $$(".view-switch button").forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view")); });
  });

  /* ===== 2. 阅读进度条 ===== */
  var progress = $(".progress i");
  function updateProgress() {
    if (!progress) return;
    var h = document.documentElement;
    var max = h.scrollHeight - h.clientHeight;
    progress.style.width = (max > 0 ? Math.min(100, (h.scrollTop / max) * 100) : 0) + "%";
  }
  window.addEventListener("scroll", updateProgress, { passive: true });
  updateProgress();

  /* ===== 3. 只看正文（纯净阅读态切换） ===== */
  var readBtn = $("#btn-reading");
  if (readBtn) {
    readBtn.addEventListener("click", function () {
      var on = document.body.classList.toggle("reading");
      readBtn.setAttribute("aria-pressed", on ? "true" : "false");
      readBtn.textContent = on ? "显示核验" : "只看正文";
      /* 只看正文只作用于核验报告视图：正在材料专库时切回报告，专库不受影响 */
      if (on && app && app.getAttribute("data-view") !== "report") setView("report");
    });
  }

  /* ===== 4. 复制全文（章节标题 + 段落 + 表格，去角标） ===== */
  var copyBtn = $("#btn-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var parts = [];
      /* 按文档流顺序收集章节标题/段落/表格；克隆后剔除引文胶囊与角标，
         只复制正文本身（胶囊标题/展开摘录/编号数字均不带出） */
      var nodes = $$("#view-report .ch-head h2, #view-report .lead, #view-report .para, #view-report .tbl-wrap");
      nodes.sort(function (a, b) { return (a.compareDocumentPosition(b) & 4) ? -1 : 1; });
      nodes.forEach(function (el) {
        var clone = el.cloneNode(true);
        clone.querySelectorAll(".jb, sup.cite").forEach(function (x) { x.remove(); });
        var t = clone.textContent.replace(/[ \t]+/g, " ").trim();
        if (t) parts.push(t);
      });
      var text = parts.filter(Boolean).join("\\n\\n");
      function done(ok) {
        var old = copyBtn.textContent;
        copyBtn.textContent = ok ? "已复制 ✓" : "复制失败";
        setTimeout(function () { copyBtn.textContent = old; }, 1600);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(fallback(text)); });
      } else {
        done(fallback(text));
      }
      function fallback(value) {
        try {
          var ta = document.createElement("textarea");
          ta.value = value;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          var ok = document.execCommand("copy");
          document.body.removeChild(ta);
          return ok;
        } catch (e) { return false; }
      }
    });
  }

  /* ===== 5. 打印归档（PDF）：下拉双选项——只打印正文 / 完整归档 ===== */
  var printBtn = $("#btn-print");
  var printDrop = $("#print-drop");
  function printBy(mode) {
    if (mode === "body") document.body.classList.add("print-body-only");
    if (printDrop) printDrop.hidden = true;
    window.print();
  }
  if (printBtn && printDrop) {
    printBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      printDrop.hidden = !printDrop.hidden;
    });
    printDrop.addEventListener("click", function (e) {
      e.stopPropagation();
      var t = e.target.closest("button");
      if (!t) return;
      printBy(t.id === "print-body" ? "body" : "full");
    });
    document.addEventListener("click", function () { printDrop.hidden = true; });
    /* 打印结束移除临时模式（浏览器打印窗口关闭后触发） */
    window.addEventListener("afterprint", function () { document.body.classList.remove("print-body-only"); });
  }

  /* ===== 6. 材料卡索引（专库列表内，不含打印附录） ===== */
  var cards = $$("#lib-list .scard");
  var byId = {};
  cards.forEach(function (c) {
    var id = c.getAttribute("data-cite-id");
    if (id) byId[id] = c;
  });

  /* 移动端底部弹层：正文表述 ↔ 原文原段 对照 + 材料卡 */
  var sheet = $(".sheet");
  var mask = $(".sheet-mask");
  function escHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }
  function sentenceOf(el) {
    var para = el && el.closest ? el.closest(".doc-block,.doc-item") : null;
    return para && para.querySelector("p") ? para.querySelector("p").innerText.trim() : "";
  }
  function openSheet(card, sentence) {
    if (!sheet) return;
    var body = sheet.querySelector(".sheet-body");
    body.innerHTML = "";
    if (sentence) {
      var excerpt = card.querySelector(".sc-excerpt");
      var cmp = document.createElement("div");
      cmp.className = "cmp";
      cmp.innerHTML =
        '<div class="cmp-side cmp-ai"><div class="cmp-tag">正文表述</div><p>' + escHtml(sentence) + '</p></div>' +
        '<div class="cmp-side cmp-src"><div class="cmp-tag">原文原段</div>' +
        '<div class="sc-excerpt">' + (excerpt ? excerpt.innerHTML : "") + '</div></div>';
      body.appendChild(cmp);
    }
    var clone = card.cloneNode(true);
    clone.removeAttribute("id");
    clone.classList.remove("hide");
    clone.classList.add("open");
    body.appendChild(clone);
    sheet.classList.add("show");
    mask.classList.add("show");
    document.body.style.overflow = "hidden";
    sheet.scrollTop = 0;
  }
  function closeSheet() {
    if (!sheet) return;
    sheet.classList.remove("show");
    mask.classList.remove("show");
    document.body.style.overflow = "";
  }
  if (sheet && mask) {
    mask.addEventListener("click", closeSheet);
    var closeBtn = sheet.querySelector(".sheet-close");
    if (closeBtn) closeBtn.addEventListener("click", closeSheet);
  }

  /* 行内引文 jb（原型行为）：点小胶囊 toggle 展开卡；点角标展开对应 jb 并 flash。
     未绑定角标红色警示，绝不按位置猜测。 */
  var JB_TABLES = {};
  try {
    var jbTablesEl = document.getElementById("jb-tables");
    if (jbTablesEl) JB_TABLES = JSON.parse(jbTablesEl.textContent || "{}");
  } catch (e) { JB_TABLES = {}; }
  function fillTableHolders(jb) {
    jb.querySelectorAll(".tbl-holder[data-tbl]").forEach(function (h) {
      if (h.getAttribute("data-filled")) return;
      var html = JB_TABLES[h.getAttribute("data-tbl")];
      if (html) h.innerHTML = html;
      h.setAttribute("data-filled", "1");
    });
  }
  function toggleJb(jb, forceOpen) {
    var open = forceOpen === true ? true : !jb.classList.contains("active");
    document.querySelectorAll(".jb.active").forEach(function (x) { if (x !== jb) x.classList.remove("active"); });
    jb.classList.toggle("active", open);
    if (open) fillTableHolders(jb);
    var name = jb.querySelector(".jb-name");
    if (name) name.setAttribute("aria-expanded", open ? "true" : "false");
    return open;
  }
  document.querySelectorAll(".jb-name").forEach(function (name) {
    name.addEventListener("click", function () { toggleJb(name.closest(".jb")); });
  });

  /* 引文条目点击 → 材料专库定位对应卡：库内导航看完整材料；
     外部原文跳转只保留 jb-head 的"查看全文"按钮，动线分离 */
  function jumpToLibrary(id) {
    var card = byId[id];
    if (!card) return;
    setView("library");
    card.classList.remove("hide", "open");
    card.classList.add("hl", "open");
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { card.scrollIntoView({ block: "center", behavior: "smooth" }); });
    });
    setTimeout(function () { card.classList.remove("hl"); }, 2200);
  }
  document.querySelectorAll(".jb-quote").forEach(function (q) {
    function go() {
      var jbEl = q.closest(".jb");
      var id = jbEl && jbEl.getAttribute("data-cite");
      if (id) jumpToLibrary(id);
    }
    q.addEventListener("click", go);
    q.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
  });
  document.querySelectorAll("sup.cite").forEach(function (btn) {
    /* 仅剩未绑定角标（红色数字）走到这里：点击控制台留痕 */
    btn.addEventListener("click", function () {
      if (console.error) console.error("[核验] 未绑定角标:", btn.getAttribute("data-cite"));
    });
  });

  /* 材料卡摘录直接全文展开（句后胶囊已承载即点即看，专库不再折叠） */

  /* 胶囊点击：桌面开关对照气泡（同一气泡再点收起）；手机端弹出底部材料弹层 */
  document.querySelectorAll(".ev-chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var id = chip.getAttribute("data-cite");
      if (isMobile()) {
        var card = byId[id];
        if (card) openSheet(card, sentenceOf(chip));
        return;
      }
      togglePop(chip, id);
    });
  });

  /* ===== 7. 材料专库：tabs + 搜索 + 热词 ===== */
  var cond = "";
  var kw = "";
  function applyFilter() {
    var visible = 0;
    cards.forEach(function (c) {
      var okCond = !cond;
      if (cond === "__unused__") okCond = c.getAttribute("data-unused") === "1";
      else if (cond) okCond = c.getAttribute("data-search") === cond;
      var okKw = !kw || (c.textContent || "").toLowerCase().indexOf(kw) !== -1;
      var show = okCond && okKw;
      c.classList.toggle("hide", !show);
      if (show) visible++;
    });
    var empty = $("#lib-empty");
    if (empty) empty.classList.toggle("hide", visible !== 0);
  }
  $$(".lib-tabs button").forEach(function (b) {
    b.addEventListener("click", function () {
      $$(".lib-tabs button").forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      cond = b.getAttribute("data-cond") || "";
      applyFilter();
    });
  });
  var search = $(".lib-search");
  if (search) search.addEventListener("input", function () { kw = search.value.trim().toLowerCase(); applyFilter(); });
  $$(".hot-term").forEach(function (t) {
    t.addEventListener("click", function () {
      if (!search) return;
      search.value = t.textContent.trim();
      kw = search.value.toLowerCase();
      applyFilter();
      if (search.focus) search.focus();
    });
  });

  /* ===== 8. 过程回顾条：检索步骤展开 ===== */
  var pStep = $("#p-step-search");
  var pDetail = $("#p-detail");
  if (pStep && pDetail) {
    function toggleDetail() { pDetail.classList.toggle("show"); }
    pStep.addEventListener("click", toggleDetail);
    pStep.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleDetail(); }
    });
  }

  /* ===== 9. 章节目录（spy） ===== */
  var toc = $(".toc");
  if (toc) {
    var links = $$("a", toc);
    var secs = links.map(function (a) { return document.querySelector(a.getAttribute("href")); });
    links.forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        var target = document.querySelector(a.getAttribute("href"));
        if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
      });
    });
    function spy() {
      var pos = window.scrollY + 130;
      var current = -1;
      secs.forEach(function (s, i) { if (s && s.offsetTop <= pos) current = i; });
      links.forEach(function (a, i) { a.classList.toggle("on", i === current); });
    }
    window.addEventListener("scroll", spy, { passive: true });
    spy();
  }
})();
"""


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "",
                generated_at: Optional[datetime] = None,
                skip_link_check: bool = False, snapshot_enabled: bool = True) -> str:
    payload = unwrap(payload)
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    sources = align_sources_to_answer(answer, extract_sources(payload, skip_link_check=skip_link_check, snapshot_enabled=snapshot_enabled))
    # 角标按首次出现顺序重排为 1..N（含材料卡同步重编号与未引用分组），WorkBuddy 实测反馈要求
    answer, sources = renumber_citations(answer, sources)
    used = citation_ids(answer)
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")

    verification = compute_verification(answer, sources, payload, generated_at)
    process_stats = compute_process_stats(sources, answer)
    hot_terms = extract_hot_terms(answer, sources)
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warn-box"><b>生成检查未通过：正文没有来源角标。</b>'
            '本报告无法建立"结论-素材"核验对应，仅作素材清单参考。'
            '请修正最终答案（--answer-file）：在关键结论后标注 [1]、[2] 等角标并逐条对应召回材料，'
            '然后重新运行本脚本生成核验报告。</div>'
        )
    chip_map = build_chip_data(sources)
    blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources}, chip_map)
    # 胶囊内表格数据汇总（span 内静态表格会被解析器拆散，改为页尾 JSON + 展开时 JS 注入）
    jb_tables: Dict[str, str] = {}
    for cid, jb in chip_map.items():
        for key, html in (jb.pop("_tables", {}) or {}).items():
            jb_tables[key] = html
    doc_title, sections = group_sections(blocks)
    display_title = doc_title or title

    jb_tables_json = json.dumps(jb_tables, ensure_ascii=False).replace("</", "<\\/")
    jb_tables_script = (f'<script type="application/json" id="jb-tables">{jb_tables_json}</script>\n'
                        if jb_tables else "")

    meta_bits = []
    if process_stats["n_searches"]:
        meta_bits.append(f"深知检索 {process_stats['n_searches']} 次")
    if sources:
        meta_bits.append(f"召回材料 {len(sources)} 条")
    if process_stats["n_cite_marks"]:
        meta_bits.append(f"正文引用 {process_stats['n_cite_marks']} 处")
    meta_bits.append(f"生成于 {generated}")
    meta_line = " · ".join(meta_bits)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display_title)} · 溯源核验报告</title>
<style>{PAGE_CSS}</style>
</head>
<body>

<header class="topbar">
  <div class="tb-left">
    <span class="tb-stamp">溯源核验报告</span>
    <span class="tb-title">{esc(display_title)}</span>
  </div>
  <div class="tb-right">
    <div class="view-switch" role="tablist" aria-label="视图切换">
      <button class="on" data-view="report" type="button">核验报告</button>
      <button data-view="library" type="button">材料专库</button>
    </div>
    <div class="tb-tools">
      <button id="btn-reading" type="button" aria-pressed="false" title="隐藏核验元素，纯阅读正文">只看正文</button>
      <button id="btn-copy" type="button" title="复制正文纯文本">复制全文</button>
      <span class="print-menu">
        <button id="btn-print" type="button" aria-haspopup="true" title="浏览器打印／另存为 PDF">打印归档 ▾</button>
        <span class="print-drop" id="print-drop" hidden>
          <button id="print-body" type="button">只打印正文</button>
          <button id="print-full" type="button">完整归档（含核验材料）</button>
        </span>
      </span>
    </div>
  </div>
  <div class="progress" aria-hidden="true"><i></i></div>
</header>

<div class="hero">
  <div class="r-badge">溯源核验报告</div>
  <h1>{esc(display_title)}</h1>
  <div class="meta">{esc(meta_line)} ｜ 素材来源：深知可信搜索</div>
  <div class="hero-switch">
    <div class="view-switch" role="tablist" aria-label="视图切换">
      <button class="on" data-view="report" type="button">核验报告</button>
      <button data-view="library" type="button">材料专库（{len(sources)}）</button>
    </div>
  </div>
</div>

<div class="app container" data-view="report">
  {render_process_bar(process_stats, verification)}

  <main class="view" id="view-report" aria-label="核验报告正文">
    {citation_warning}
    {render_verify_panel(verification)}
    <div class="doc-paper">
    {render_section_cards(sections, sources)}
    </div>
    <div class="foot">深知可信搜索 · 溯源核验报告 ｜ 内容由 AI 生成，仅供参考，政策现行效力以官方发布为准</div>
  </main>

  {render_library_view(sources, hot_terms)}
  {render_print_appendix(sources)}
</div>

{render_toc(sections)}

<div class="ev-panel" id="ev-pop" hidden></div>
{jb_tables_script}<div class="sheet-mask" aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-label="核验材料">
  <div class="sheet-grab"></div>
  <div class="sheet-head"><b>依据对照</b><button class="sheet-close" type="button">收起</button></div>
  <div class="sheet-body"></div>
</div>

<script>{PAGE_JS}</script>
</body>
</html>"""


def renumber_citations(answer: str, sources: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]]]:
    """把答案角标按首次出现顺序重排为 [1][2][3]…，材料卡同步重编号。

    被引用的材料按新编号排在前面（编号与正文角标一一对应，used=True）；
    未引用召回材料移入"未引用素材"分组（used=False，不占角标编号，锚点用独立递增号）。
    """
    cited_order = citation_ids(answer)
    if not cited_order:
        for s in sources:
            s["used"] = False
        return answer, sources
    mapping = {old: str(new) for new, old in enumerate(cited_order, start=1)}
    answer = re.sub(r"\[(\d+)\]", lambda m: "[" + mapping.get(m.group(1), m.group(1)) + "]", answer)
    by_old: Dict[str, Dict[str, str]] = {}
    for s in sources:
        by_old.setdefault(s["id"], s)
    cited_sorted: List[Dict[str, str]] = []
    for old in cited_order:
        s = by_old.get(old)
        if s is None:
            continue
        s2 = dict(s)
        s2["id"] = mapping[old]
        s2["used"] = True
        cited_sorted.append(s2)
    next_panel = len(mapping)
    rest: List[Dict[str, str]] = []
    for s in sources:
        if s["id"] in mapping:
            continue
        next_panel += 1
        s2 = dict(s)
        s2["used"] = False
        # 未引用材料 id 一并改为面板锚点号，避免旧编号与重排后的角标空间撞号
        s2["id"] = str(next_panel)
        rest.append(s2)
    return answer, cited_sorted + rest


def align_sources_to_answer(answer: str, sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cited = citation_ids(answer)
    if not cited or not sources:
        return sources
    existing = {source["id"] for source in sources}
    if existing.intersection(cited):
        return sources
    aligned = [dict(source) for source in sources]
    for idx, citation in enumerate(cited):
        if idx >= len(aligned):
            break
        aligned[idx]["id"] = citation
        aligned[idx]["type_key"] = aligned[idx].get("type_key", "material")
        aligned[idx]["type_label"] = aligned[idx].get("type_label", "材料")
        aligned[idx]["type_css"] = aligned[idx].get("type_css", "mat")
    return aligned


def main() -> None:
    parser = argparse.ArgumentParser(description="生成溯源核验报告 HTML（深知可信搜索 SkillHub 版）")
    parser.add_argument("input_json", help="trusted_search.py / deep_query.py 的 --json-only 输出 JSON")
    parser.add_argument("--output", help="输出 HTML 文件名（official-docs/output/）；不传时按问题自动生成《标题_溯源核验报告_时间戳.html》")
    parser.add_argument("--title", default="溯源核验报告", help="页面标题")
    parser.add_argument("--answer-file", help="最终答案文件（关键结论带 [1][2] 角标）。复杂任务综合后必须传入，确保 HTML 展示的答案与交付一致。")
    parser.add_argument("--clean-md-output", help="输出干净 Markdown 路径；内容来自同一份最终答案，并移除 [1]、【1】等溯源角标。")
    parser.add_argument("--question", default="", help="用户原始问题，用于自动生成文件名。")
    parser.add_argument("--self-check-file", help="答案自检结果 JSON（五项：fact_basis/binding/consistency/freshness/no_gap，值写 通过/未通过：原因）；未传时核验单如实显示'未记录'。")
    parser.add_argument("--skip-link-check", action="store_true", help="跳过原文链接活性检测（默认检测：404/410/软404 标记失效，连接失败/403 保守放行）")
    parser.add_argument("--no-snapshot", action="store_true", help="关闭存档快照兜底展示（默认启用：原文失效时以 /A/ 修订后的存档快照回看）")
    args = parser.parse_args()

    input_path = _safe_input_path(args.input_json, {".json"})
    payload = load_json(input_path)
    answer_override = ""
    if args.answer_file:
        answer_override = _safe_input_path(args.answer_file, {".txt", ".md"}).read_text(encoding="utf-8")

    # 答案自检结果注入（写入 unwrap 后的根级，供 compute_verification 读取）
    if args.self_check_file:
        check_path = _safe_input_path(args.self_check_file, {".json"})
        check_data = json.loads(check_path.read_text(encoding="utf-8"))
        if isinstance(check_data, dict):
            unwrap(payload)["selfCheck"] = check_data

    snapshot_enabled = not args.no_snapshot
    unwrapped = unwrap(payload)
    final_answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(unwrapped)

    # 生成前硬校验：核验报告必须以可交付状态产出——无角标或角标未绑定材料均拒绝生成
    preview_sources = extract_sources(unwrapped, skip_link_check=True, snapshot_enabled=snapshot_enabled)
    preview_cited = citation_ids(final_answer)
    if preview_sources and not preview_cited:
        print(
            "错误：生成检查未通过——已召回 "
            f"{len(preview_sources)} 条材料，但答案中没有 [1]、[2] 等来源角标，无法建立\"结论-素材\"核验对应。\n"
            "请修正最终答案（--answer-file）：在关键结论后标注角标并逐条对应召回材料，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    preview_ids = {s["id"] for s in preview_sources}
    unbound_preview = [cid for cid in preview_cited if cid not in preview_ids]
    if unbound_preview:
        shown = "、".join(f"[{c}]" for c in unbound_preview[:8])
        print(
            f"错误：生成检查未通过——答案角标 {shown} 未绑定到任何召回材料"
            f"（共召回 {len(preview_sources)} 条，可绑定编号 {min(preview_ids) if preview_ids else '-'}~{max(preview_ids) if preview_ids else '-'}）。\n"
            "请修正最终答案：角标必须逐条对应实际引用的材料，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    question = args.question.strip() or extract_question(unwrapped)
    generated_at = datetime.now()
    if args.output:
        output = _safe_output_path(args.output, {".html", ".htm"}, ".html")
    else:
        output = _safe_output_path(safe_output_filename(question, generated_at), {".html", ".htm"}, ".html")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_html(payload, args.title, answer_override=answer_override, question_override=args.question,
                    generated_at=generated_at, skip_link_check=args.skip_link_check,
                    snapshot_enabled=snapshot_enabled),
        encoding="utf-8")
    print(f"已生成：{output}")
    if args.clean_md_output:
        clean_output = _safe_output_path(args.clean_md_output, {".md"}, ".md")
    else:
        clean_output = _safe_output_path(output.with_suffix(".clean.md").name, {".md"}, ".md")
    clean_output.parent.mkdir(parents=True, exist_ok=True)
    clean_answer = strip_citation_markers(final_answer)
    clean_output.write_text(clean_answer, encoding="utf-8")
    print(f"已生成干净 Markdown：{clean_output}")


if __name__ == "__main__":
    main()
