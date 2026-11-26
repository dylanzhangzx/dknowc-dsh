#!/usr/bin/env python3
"""溯源核验报告生成器：把通用材料 JSON + 最终答案渲染为单文件可核验 HTML。

输入为一种通用 JSON 格式（materials 数组 + answer），不依赖任何特定接口产物；
各业务 Skill 只需把检索/研究结果的要素映射到这份 JSON，即可获得统一版式的溯源核验报告。
正文用 --answer-file 传入最终答案（关键结论带 [n] 角标），成稿自检用 --self-check-file 传入五项结果。

报告定位：不止展示"材料从哪来"（溯源），更要传达"我们查过了，可以交付"（核验）。
架构：
- 顶栏：身份章 + 标题 + 工具组（只看正文 / 复制全文 / 打印归档）+ 阅读进度条
- Hero：大标题 + 真实统计（N 次检索 · M 篇来源文章 · K 处引用）+ 双视图切换
- 过程回顾条：检索 → 入库 → 逐条比对 → 核验完成（静态回放，数字全部真实计算）
- 核验报告视图（默认）：核验报告单 + 正文分节卡；角标点击弹「引用依据」弹窗
- 知识专库视图（全屏）：大搜索 + 检索分组 tabs + 材料卡（未引用材料折叠区）
三个核验层次：报告级（核验报告单）／材料级（来源卡核验链标记）／引用级（角标一一绑定）。
诚实原则：脚本真实计算的结果才打勾；无法自动判定的项不虚构展示。
核验口径（脚本管字面、模型管语义）：硬错误判"核验未通过"，语义类只作"待人工复核"。
原文链接原样进报告、不做活性探测；--no-snapshot 关闭存档快照兜底。
布局为单文件静态 HTML；打印归档模式单栏全展开并附材料附录。
所有输入输出经路径安全层限制在会话 run 目录（--run）内，拒绝写回 Skill 安装目录。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from run_paths import RunPathError, resolve_input_path, resolve_output_path, resolve_run_dir
import chart_embed  # 图表渲染共享模块（1.0.1，opt-in：传 --charts-json 才画）
import trust_digest  # 核验记录指纹（1.0.1，--verify-file 的失效检测）


# ============================================================
# 配置系统（1.0.1）：品牌 / 通道 / 自检标签 / 双版 / 图表 / 域内核验
# ============================================================
# 各业务 Skill 通过 --config 传入自己的 trace_report.config.json；
# 未传时使用下列默认值（通用报告形态，品牌=溯源核验报告生成器）。
# 设计约束：定制只走配置，不在渲染代码里 fork。

DEFAULT_CONFIG: Dict[str, Any] = {
    "brand": {
        "product_name": "溯源核验报告生成器",
        "footer_body": "{product} · 正文 ｜ 内容由 AI 生成，仅供参考",
        "footer_report": "{product} · 溯源核验报告 ｜ 内容由 AI 生成，仅供参考",
        "argparse_desc": "生成溯源核验报告 HTML（{product}）",
        "lib_foot_source": "来源：{product} · 每段摘录均取自原文原段",
        "lib_foot_external": "来源：{product} · 部分材料来自公开网络，已标注非官方来源，请以官方口径复核",
        "source_fallback": "{product}",
        "source_fallback_external": "{product}（含公开网络材料）",
        "report_title_prefix": "溯源核验报告",
        "default_page_title": "溯源核验报告",
    },
    "channels": {
        "tokens": {},
        "route_keywords": {},
        "labels": {},
        "summary": {"fallback": "通用检索 {n} 路"},
        "step1_fallback": "通用检索",
        "internal_token_filter": ["联网", "公开网络", "宿主 WebSearch"],
        "user_facing_replacements": [],
    },
    "selfcheck": {
        "labels": {
            "fact_basis": "事实有据",
            "binding": "角标绑定",
            "consistency": "答案一致",
            "freshness": "时效确认",
            "no_gap": "无未核验断言",
        }
    },
    # 1.0.2 两轨验收：Agent 轨要求"结论 + 可回查证据"；关掉 require_evidence 退回 1.0.1 行为
    "agent_track": {"enabled": True, "require_evidence": True},
    # 官方外部信源白名单（1.0.2 配置化）：法定机构自有域名，政府域名之外的第二条官方判据。
    # 业务 Skill 可在 config 里增删（如属地公积金局/立法会等）。
    "official_host_allow": ["mpfa.org.hk"],
    "stage": {"enable": False, "labels": {}},
    "charts": {"enable": True},
    "verify": {"enabled": True, "required": False, "compare_digests": True},
}

CONFIG: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并配置：override 覆盖 base，未知键保留（向前兼容）。"""
    out = json.loads(json.dumps(base))
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_config(override: Optional[Dict[str, Any]]) -> None:
    """载入业务 Skill 配置（缺省键回退默认值）。"""
    global CONFIG
    CONFIG = _deep_merge(DEFAULT_CONFIG, override or {})


def load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"错误：配置文件无法读取（{exc}）：{path}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"错误：配置文件必须是 JSON 对象：{path}", file=sys.stderr)
        raise SystemExit(2) from None
    return data


def brand_text(key: str) -> str:
    """品牌模板渲染：{product} 占位符替换为配置的产品名。"""
    brand = CONFIG.get("brand") or {}
    template = str(brand.get(key) or "")
    return template.replace("{product}", str(brand.get("product_name") or "溯源核验报告生成器"))


def selfcheck_labels() -> Dict[str, str]:
    labels = (CONFIG.get("selfcheck") or {}).get("labels") or {}
    return {str(k): str(v) for k, v in labels.items()}


def _safe_input_path(value: str, allowed_suffixes: set,
                     run_dir: Optional[Path] = None) -> Path:
    """输入文件支持绝对路径、run 目录内相对路径，或旧 Skill 目录产物。"""
    return resolve_input_path(value, run_dir, allowed_suffixes)


def _safe_output_path(value: Optional[str], allowed_suffixes: set, default_suffix: str,
                      run_dir: Optional[Path]) -> Path:
    """产物只写会话工作区的 run 目录，拒绝写回 Skill 安装目录。"""
    if value and not Path(value).expanduser().is_absolute() and run_dir is None:
        raise RunPathError("相对 --output 必须同时用 --run 指定运行目录")
    return resolve_output_path(value, run_dir, allowed_suffixes, default_suffix,
                               "溯源核验报告.html")



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
# 生成前预处理（文号匹配 / 快照兜底；链接活性检测已于 2026-10-08 移除）
# ============================================================

# 快照兜底开关：默认启用。接口 screenShotPath 曾存在路径缺 /A/ 层级的拼接 bug
# （后端修复中）；verify_snapshots 在展示前完成"/A/ 修订 + 格式校验 + 不合法弃用"。
SNAPSHOT_ENABLED = True

def normalize_snapshot_url(url: str) -> str:
    """快照路径容错：接口部分返回值缺 /A/ 层级（实测 60 条中 5 条，补全后即可访问），
    统一规范化为 https://attach.dknowc.cn/snapshot/A/<2位>/<2位>/<哈希>.jpg。"""
    u = (url or "").strip()
    if u.startswith("https://attach.dknowc.cn/snapshot/") and "/snapshot/A/" not in u:
        return u.replace("/snapshot/", "/snapshot/A/", 1)
    return u


def verify_snapshots(articles: List[Dict[str, Any]]) -> int:
    """快照展示前的路径校验（纯本地检查，不发网络请求）：
    组装阶段已由 normalize_snapshot_url 补全 /A/ 层级；此处校验修订后的路径
    是否符合合法格式（https://attach.dknowc.cn/snapshot/A/…），不合法则弃用。

    不做网络可达检测：attach 前置雷池 WAF 的拦截与请求方 IP 风控相关
    （检测机高频请求会被拦而普通用户正常），可达性实测会误杀好快照；
    快照文件本身的存在性由检索来源侧的数据质量保障。
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


def normalize_kind(raw: str) -> Tuple[str, str, str]:
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
    # 接口 kb 元数据段剔除（2026-10-14）：部分公告类材料把"生效时间：…\n所属地域：…
    # \n成文日期：…\n修订说明：【…】相关文件有下面这些版本：…"这类结构化字段串当段落返回，
    # 展示为摘录是纯噪音（日期/属地已在卡片 meta 行）——段首即"生效时间："且含
    # "所属地域："标签行的整段剔除
    if value.startswith("生效时间：") and "所属地域：" in value:
        return ""
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
        item.get("原文"),
        item.get("摘录"),
        item.get("excerpt"),
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


# ============================================================
# 来源等级：官方外部信源（政府域名/法定机构）不算"非官方"
# ============================================================
OFFICIAL_HOST_RE = re.compile(r"(^|\.)gov(\.|$)", re.I)
# 法定机构自有域名（非 .gov 后缀）：按机构白名单判定，避免把官方页误标"非官方来源"。
# 1.0.2 起白名单可由 config 的 official_host_allow 覆盖（默认仍为此常量）。
OFFICIAL_HOST_ALLOW = ("mpfa.org.hk",)


def official_host_allow() -> Tuple[str, ...]:
    """官方外部信源白名单（法定机构自有域名），config 可覆盖。"""
    values = CONFIG.get("official_host_allow")
    if isinstance(values, (list, tuple)):
        cleaned = tuple(str(v).strip().lower() for v in values if str(v).strip())
        if cleaned:
            return cleaned
    return OFFICIAL_HOST_ALLOW
# 机构名判据：必须以机关后缀结尾（避免"外部站""编辑部"这类词误判为官方）。
# 发布机构字段用全表；标题判据用收窄表——去掉"局/厅/署"单字后缀，
# 媒体标题（"XX税务局通报…"发在媒体站）不再被单字"局"误判官方；"管理局/总局/金管局"
# 等多字机关词与法定机构专名仍有效。
OFFICIAL_ORG_RE = re.compile(
    r"(人民政府|政府|委员会|委員會|管理局|监管局|監管局|总局|總局|局|厅|廳|署|法院|檢察院|检察院|"
    r"立法會|立法会|积金局|積金局|央行|中央银行|中央銀行|统计处|統計處|金管局)\s*$"
)
OFFICIAL_ORG_TITLE_RE = re.compile(
    r"(人民政府|政府|委员会|委員會|管理局|监管局|監管局|总局|總局|法院|檢察院|检察院|"
    r"立法會|立法会|积金局|積金局|央行|中央银行|中央銀行|统计处|統計處|金管局)\s*$"
)


def is_official_external(url: str, issuer: str = "", title: str = "") -> bool:
    """外部（非库内）信源是否官方：政府域名或官方机构名。"""
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        host = ""
    if host and (OFFICIAL_HOST_RE.search(host) or host.endswith((".gov.cn", ".gov.hk", ".gov.mo"))
                 or any(host == d or host.endswith("." + d) for d in official_host_allow())):
        return True
    for text, org_re in ((issuer or "", OFFICIAL_ORG_RE), (title or "", OFFICIAL_ORG_TITLE_RE)):
        # 去掉末尾空白与括号（"…（積金局）"要能按机构名判定），再做机关后缀匹配
        text = re.sub(r"[\s\-—_·（）()\[\]【】]+$", "", str(text))
        if org_re.search(text):
            return True
    return False


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
    title = first_str(
        item.get("文章标题"),
        item.get("material_name"),
        item.get("材料名称"),
        item.get("title"),
        item.get("标题"),
        item.get("name"),
        vo.get("showTitle"),
        vo.get("title"),
        "未命名来源文章",
    )
    # 发布机构：直接从通用 JSON 字段读取（不做标题推导）。
    issuer = first_str(item.get("发布机构"), item.get("issuer"), item.get("发布机关"), vo.get("issuer"))
    agency = issuer
    is_policy = "政策" in str(item.get("来源性质", "")) or "policy" in str(item.get("素材类型", "")).lower()

    source = {
        "id": explicit_id or str(index),
        "title": title,
        "agency": agency,
        "data_source": "",
        "issuer": issuer,
        "is_policy": is_policy,
        "date": first_str(item.get("发布日期"), item.get("date"), item.get("发布时间"), item.get("createDate"), vo.get("dateTime"), vo.get("createDate")),
        # 1.0.1：兜底链不得含「原文」——契约里它是必填摘录文本，兜底会令 has_link 恒真、缺链提醒失效
        "url": first_str(item.get("sourceUrl"), item.get("source_url"), item.get("源网址"), item.get("原文链接"), item.get("url"), vo.get("sourceUrl"), vo.get("url")),
        "policy_url": first_str(item.get("policyUrl"), item.get("policy_url"), vo.get("policyUrl")),
        "excerpt": segment.get("text") or paragraph_text(item),
        "section": first_str(item.get("正文对应"), item.get("section"), item.get("支撑")),
        "kind": first_str(item.get("类型"), item.get("type"), item.get("素材类型"), vo.get("typeName"), "材料"),
        "verify_note": user_facing_text(first_str(item.get("核验"), item.get("verification"), item.get("核验说明"))),
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
    # 发文字号：单路原始 JSON 与 merge 归一后的 JSON 都要兼容。
    # - 可信 V2 文章级字段为「发文字号」；深搜 V3 文章级字段为 writtenText；
    # - merge 会把两者归一为「文号」，但单路直接渲染不经过 merge，必须在本层兜住。
    source["doc_number"] = first_str(
        item.get("文号"),
        item.get("发文字号"),
        item.get("writtenText"),
        item.get("doc_number"),
    )
    # 所属搜索条件（多路检索分组）与引用状态（未引用=接口召回但正文未采用）
    # 分组标签面向用户：过滤「公开网络/外部联网/阶段X」等内部实现词
    source["search_key"] = user_facing_text(first_str(item.get("检索分组"), item.get("搜索条件"), item.get("search_key")))
    # 检索通道（通用检索来源 / 溯源核验报告生成器）：由检索脚本在产物上打标、merge 透传，
    # 供过程条/hero 按接口通道拆分计数；历史 JSON 无该字段时为空（渲染层回退旧文案）
    source["channel"] = first_str(item.get("检索通道"), item.get("channel"))
    # 非官方来源：联网路（searchChannel=webSearch）召回的非权威站点材料。
    # 双口径判定：联网路脚本打标 非官方来源=True；或接口 dataAuthority 返回 数据权威性=非权威。
    source["unofficial"] = (
        bool(item.get("非官方来源"))
        or str(item.get("来源性质") or item.get("source_kind") or "").strip().lower() in ("unofficial", "非官方", "非官方来源")
        or str(item.get("数据权威性") or item.get("authority") or "").strip() in ("非权威", "non-authoritative")
    )
    source["pending"] = bool(item.get("待核验") or item.get("pending"))
    # 1.0.2：外部信源再判等级——官方外部（政府域名/法定机构）不作"非官方"处理。
    _issuer_text = str(source.get("issuer") or "")
    _title_text = str(source.get("title") or "")
    source["official_external"] = bool(source["unofficial"]
                                      and is_official_external(source.get("url") or "", _issuer_text, _title_text))
    if source["official_external"]:
        source["unofficial"] = False
    # 可引用性（1.7.3）：policy 版本索引/无正文材料不得作为正文依据。
    # 缺字段时按摘录是否有内容兜底（历史 JSON 兼容）。
    source["citable"] = item.get("可引用") is not False
    source["material_kind"] = first_str(item.get("材料性质"))
    source["uncitable_reason"] = first_str(item.get("不可引用原因"))
    source["used"] = item.get("已引用", item.get("used", True))
    if not isinstance(source["used"], bool):
        source["used"] = True
    # 快照是接口自带的存档副本，统一作为附加回看入口展示（2026-10-08 起不再做
    # 链接活性探测，原文链接原样进报告；快照仅做本地格式校验，不发网络请求）。
    source["snapshot"] = first_str(item.get("快照链接"), item.get("snapshot"), item.get("screenShotPath"))
    # 发布日期可信度（实测：「高」=模型治理入库、标题模型精抽；「较高」=门户抓取、标题规则提取）
    source["conf"] = first_str(item.get("发布日期可信度"), item.get("可信度"), item.get("confidence"))
    # 材料类型只用于卡片左侧色条（内部样式），不再作为文字标签展示，也不再参与统计（1.0.2）。
    key, _label, css = normalize_kind(source["kind"])
    source["type_key"] = key
    source["type_css"] = css
    live_url = bool(source["url"] and source["url"] != "接口未返回")
    source["has_link"] = live_url or bool(source["policy_url"]) or bool(source["snapshot"])
    # 核验状态只看结构：摘录可比对且材料可引用。原文链接死活与快照有无是回看通道问题，
    # 不影响核验结论；"引用是否被核验通过"这类内容判断不由脚本采信（1.0.2 归 AI 轨）。
    source["verified"] = bool(source["excerpt"]) and source["citable"]
    return source


def load_materials(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从通用 JSON 读取材料列表。

    顶层 materials / 材料 / sources 均可；顶层是数组也接受。
    每条材料必须有"标题"与"原文"（摘录）；编号缺省按数组顺序 1-based。
    """
    raw = payload.get("materials")
    if not isinstance(raw, list):
        raw = payload.get("材料")
    if not isinstance(raw, list):
        raw = payload.get("sources")
    if not isinstance(raw, list) and isinstance(payload.get("data"), list):
        # 顶层数组经 load_json 包装为 {"data": [...]}（兼容裸材料数组输入）
        raw = payload["data"]
    if not isinstance(raw, list):
        if isinstance(payload, list):
            raw = payload
        else:
            return []
    articles = [x for x in raw if isinstance(x, dict)]
    # 编号缺省补齐
    for idx, item in enumerate(articles):
        if not first_str(item.get("编号"), item.get("角标"), item.get("index")):
            item["编号"] = str(idx + 1)
    return articles


def extract_sources(payload: Dict[str, Any],
                    snapshot_enabled: bool = True) -> List[Dict[str, str]]:
    """通用 JSON → 渲染器内部 source dict 列表。"""
    raw_sources = load_materials(payload)

    # 快照兜底
    if snapshot_enabled:
        for a in raw_sources:
            raw_snap = first_str(a.get("快照链接"), a.get("snapshot"), a.get("screenShotPath"))
            a["快照链接"] = normalize_snapshot_url(raw_snap) if raw_snap else ""
        verify_snapshots(raw_sources)
    else:
        for a in raw_sources:
            a["快照链接"] = ""

    sources: List[Dict[str, str]] = []
    seen_ids = set()
    for item in raw_sources:
        source = source_from_article(item, len(sources) + 1)
        # 编号重复报错
        if source["id"] in seen_ids:
            print(f"错误：材料编号 {source['id']} 重复（标题：{source['title'][:30]}）。"
                  "请检查通用 JSON 中各材料的 编号 字段。", file=sys.stderr)
            raise SystemExit(2)
        seen_ids.add(source["id"])
        if not source["search_key"]:
            source["search_key"] = "本轮检索"
        sources.append(source)
    return sources


def extract_answer(payload: Dict[str, Any]) -> str:
    answer = first_str(payload.get("answer"), payload.get("答案"))
    if answer:
        return normalize_citations(answer)
    materials = load_materials(payload)
    if materials:
        rows = ["以下材料已入库，但未传入答案正文；请用 --answer-file 传入带 [n] 角标的最终答案："]
        for idx, item in enumerate(materials[:8], start=1):
            rows.append(f"[{idx}] {first_str(item.get('标题'), item.get('title'), item.get('name'), '未命名材料')}")
        return "\n".join(rows)
    return "输入 JSON 中未识别到答案正文；请用 --answer-file 传入。"


def extract_question(payload: Dict[str, Any]) -> str:
    return first_str(payload.get("question"), payload.get("问题"), payload.get("query"))


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

def self_check_items() -> List[Tuple[str, str]]:
    """当前配置的五项自检（key, 显示名）；业务 Skill 可整体替换标签集。"""
    return [(str(k), str(v)) for k, v in selfcheck_labels().items()]


def classify_check_value(raw: Any) -> Tuple[str, str]:
    """把自检项的值解析为（状态, 核验说明）。

    兼容多种写法：`pass` / `true` / `通过` / `通过：说明文字` / `✓` 等；
    值后面的说明文字保留下来供核验单展示。无法识别的状态按未记录（none）处理：
    描述性文本不等于"未通过"——红项只给显式声明的未通过，避免书写格式问题
    被放大成核验未通过（2026-09-20 WorkBuddy 实测：Agent 把备注写成自检值导致 5/7 红项）。
    """
    text = str(raw or "").strip()
    lowered = text.lower()
    for prefix in ("未通过", "不通过", "不合格", "fail", "false", "否", "✗", "no"):
        if lowered.startswith(prefix):
            return "fail", text[len(prefix):].lstrip("：:，,、 ").strip()
    for prefix in ("已通过", "通过", "合格", "pass", "ok", "true", "是", "✓", "yes"):
        if lowered.startswith(prefix):
            return "pass", text[len(prefix):].lstrip("：:，,、 ").strip()
    return "none", text


# ============================================================
# 两轨验收：Agent 轨（标准由我们定义，Agent 提交结论与证据）
# ============================================================
# 可核对要素：材料编号、条款号、文号、日期、标准号——任一项即可回查。
CHECKABLE_PATTERNS = (
    re.compile(r"\[\d+\]"),
    re.compile(r"第[一二三四五六七八九十百零〇\d]+条"),
    re.compile(r"§\s*\d+"),
    re.compile(r"〔\s*20\d{2}\s*〕"),
    re.compile(r"20\d{2}\s*[-/.年]\s*\d{1,2}"),
    re.compile(r"20\d{2}\s*年"),
    re.compile(r"[A-Za-z0-9_./-]+\.(?:json|txt|md|html|csv)", re.I),
    re.compile(r"GB(?:/T)?\s*\d+", re.I),
)


def has_checkable_element(text: Any) -> bool:
    """证据里是否至少有一处可回查的要素（编号/条款/文号/日期/标准号）。"""
    value = str(text or "")
    return any(pattern.search(value) for pattern in CHECKABLE_PATTERNS)


def agent_track_config() -> Dict[str, Any]:
    return dict(CONFIG.get("agent_track") or {})


def _normalize_verdict(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return "none"
    for prefix in ("pending", "待定", "待确认", "待人工复核", "待复核"):
        if text.startswith(prefix):
            return "pending"
    for prefix in ("fail", "未通过", "不通过", "不合格", "false", "否", "✗", "no"):
        if text.startswith(prefix):
            return "fail"
    for prefix in ("pass", "已通过", "通过", "合格", "ok", "true", "是", "✓", "yes"):
        if text.startswith(prefix):
            return "pass"
    return "none"


def parse_agent_check(raw: Any, require_evidence: bool = True) -> Dict[str, Any]:
    """把一项（Agent 轨）自检解析为结构化结果。

    支持新旧两种写法：
    - 旧：`"通过：说明文字"`（字符串，兼容 1.0.1 及以前）
    - 新：`{"verdict": "pass|fail|pending", "basis": "…", "evidence": ["[1] …第五条"]}`
    返回 status ∈ pass / fail / pending / none / evidence_missing。
    """
    verdict = "none"
    basis = ""
    evidence: List[str] = []

    if isinstance(raw, dict):
        verdict = _normalize_verdict(raw.get("verdict") or raw.get("结论") or raw.get("status"))
        basis = str(raw.get("basis") or raw.get("依据") or raw.get("note") or "").strip()
        ev = raw.get("evidence") or raw.get("证据") or []
        if isinstance(ev, (list, tuple)):
            evidence = [str(x).strip() for x in ev if str(x).strip()]
        elif str(ev).strip():
            evidence = [str(ev).strip()]
    else:
        status, note = classify_check_value(raw)
        verdict = status if status in ("pass", "fail") else "none"
        basis = note

    # 旧写法的说明文字就是唯一"证据"来源
    if not evidence and basis:
        evidence = [basis]

    if verdict in ("pending", "none", "fail"):
        return {"verdict": verdict, "status": verdict, "basis": basis,
                "evidence": evidence, "missing": ""}

    # verdict = pass：必须有可核对证据，否则只作"证据不足"，不计通过
    if require_evidence:
        joined = "；".join(evidence)
        if not joined.strip() or not has_checkable_element(joined):
            return {"verdict": "pass", "status": "evidence_missing", "basis": basis,
                    "evidence": evidence,
                    "missing": "证据不足：未给出材料编号/条款号/文号/日期/标准号等可回查要素"}
    return {"verdict": "pass", "status": "pass", "basis": basis,
            "evidence": evidence, "missing": ""}


# 用户可见报告不得暴露内部检索实现（三阶段/联网通道）；自检说明里模型常写这些词，
# 渲染前统一换成用户能理解的口径。只作用于自检说明，不改正文与材料内容。
USER_FACING_REPLACEMENTS = (
    ("宿主 WebSearch", "公开网络检索"),
    ("外部联网材料", "公开网络材料"),
    ("外部联网", "公开网络"),
    ("公开网络", "检索来源"),
    ("阶段三", "补充检索"),
    ("阶段二", "补充检索"),
    ("阶段一", "检索"),
    # 外部来源只标「非官方来源」；核验由 AI 完成，不再叠加「待核验」
    ("非官方来源 · 待核验", "非官方来源"),
    ("（非官方来源，待核验）", "（非官方来源）"),
    ("(非官方来源，待核验)", "(非官方来源)"),
    ("非官方来源/待核验", "非官方来源"),
    ("非官方来源、待核验", "非官方来源"),
)


def user_facing_text(text: str) -> str:
    """单遍替换：按源词长度倒序拼一条正则一次替换，替换结果不参与后续匹配。

    顺序 str.replace 会级联（如"宿主 WebSearch→公开网络检索"再被"公开网络→检索来源"
    二次替换成"检索来源检索"）。配置的规则优先，未配置用默认表。
    """
    out = str(text or "")
    configured = (CONFIG.get("channels") or {}).get("user_facing_replacements") or []
    pairs = [(str(x[0]), str(x[1])) for x in configured if isinstance(x, (list, tuple)) and len(x) >= 2]
    mapping = {}
    for src, dst in (pairs or USER_FACING_REPLACEMENTS):
        mapping.setdefault(str(src), str(dst))
    if not mapping:
        return out
    pattern = re.compile("|".join(re.escape(src) for src in sorted(mapping, key=len, reverse=True)))
    return pattern.sub(lambda m: mapping[m.group(0)], out)


def normalize_self_check(raw: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    """把 selfCheck / agentCheck 归一化为逐项结构化结果（两轨验收）。"""
    if not isinstance(raw, dict):
        return None
    items: Dict[str, Dict[str, Any]] = {}
    labels = selfcheck_labels()
    require_evidence = bool(agent_track_config().get("require_evidence", True))
    for key, value in raw.items():
        # 只认配置里的自检键（英文 key 或与显示名相同的中文键）；白名单外的多余键
        # （如 Agent 自行追加的"备注"等描述性键）不构成核验项，直接忽略不计入。
        label = labels.get(key) or labels.get(str(key))
        if not label:
            # 兼容业务 Skill 直接用中文显示名作为键（如公文的"事实有据"）
            for display in labels.values():
                if str(key) == display:
                    label = display
                    break
        if not label:
            continue
        parsed = parse_agent_check(value, require_evidence=require_evidence)
        parsed["basis"] = user_facing_text(parsed.get("basis") or "")
        parsed["evidence"] = [user_facing_text(x) for x in (parsed.get("evidence") or [])]
        items[label] = parsed
    return items or None


def compute_verification(answer: str, sources: List[Dict[str, str]], payload: Dict[str, Any],
                         generated_at: Optional[datetime] = None) -> Dict[str, Any]:
    """核验报告单数据。只计算脚本真实可得的结果，不虚构通过。"""
    generated_at = generated_at or datetime.now()

    # ① 依据溯源：摘录可比对 + 原文链接可回看。
    # 只统计被正文引用的材料——未引用召回材料未进入正文核验流程，其缺链在自身卡片上如实标注，
    # 不应拖累"正文依据可交付"的报告级结论。
    # 缺原文链接（接口对部分治理库文章不返回源网址，属数据源覆盖问题而非核验工作缺失）
    # 不再拖垮整体结论——报告的正常结论即为"已核验"，缺链在指标行黄色提醒并在卡片标注；
    # 缺摘录（正文依据无可比对的原文）仍视为核验问题计入未通过。
    cited_sources = [s for s in sources if s.get("used", True)]
    missing_links = [s["title"] for s in cited_sources if not s.get("has_link")]
    missing_excerpts = [s["title"] for s in cited_sources if not (s.get("excerpt") or "").strip()]
    # 1.7.3：policy 版本索引/无正文材料显式标为不可引用，即使有摘录也不得作为正文依据
    uncitable = [s["title"] for s in cited_sources if s.get("citable") is False]
    # 1.0.2 责任分配：脚本轨只判**结构**——正文依据必须有可展开摘录、且非不可引用材料。
    # 内容类判断（数字/标准号/地域/缺席/金额对象/措辞）全部交给 AI 验收，不在此判红。
    bad_ids = {s["id"] for s in cited_sources
               if s.get("citable") is False or not (s.get("excerpt") or "").strip()}
    trace_passed = len(cited_sources) - len(bad_ids)

    # ② 引用绑定：正文角标与来源卡一一对应（按角标出现次数计，与用户在正文中数到的一致）
    cited = citation_ids(answer)
    all_marks = re.findall(r"\[(\d+)\]", answer)
    source_ids = {s["id"] for s in sources}
    unbound_ids = [cid for cid in cited if cid not in source_ids]
    unbound = [cid for cid in unbound_ids for _ in range(all_marks.count(cid))]
    no_citation = bool(sources) and not cited

    # ③ 时效检查：材料日期范围与历史材料计数
    # ③ 时效只统计**正文依据**（2026-09-29 起）：sources 含未引用召回材料，
    # 此前误用全集，未引用材料里的异常日期（如接口标注的未来年份）会写进交付物口径。
    dated = [parse_year_month(s.get("date")) for s in cited_sources]
    dated = [d for d in dated if d]
    freshness = None
    old_count = 0
    if dated:
        freshness = {
            "min": min(dated),
            "max": max(dated),
            "old_count": sum(1 for y, _ in dated if y <= generated_at.year - 3),
        }

    # ⑤ 成稿自检（AI 验收轨）：由溯源 JSON 的 selfCheck/agentCheck 传入，未传入如实显示未记录
    # （selfCheck/agentCheck 均可，agentCheck 是 1.0.2 起的别名）
    self_check_raw = None
    for holder in (payload, payload.get("content") if isinstance(payload.get("content"), dict) else {}):
        self_check_raw = self_check_raw or holder.get("selfCheck") or holder.get("self_check") \
            or holder.get("agentCheck") or holder.get("agent_check")
    self_items = normalize_self_check(self_check_raw)
    self_check = None
    if self_items:
        passed = sum(1 for item in self_items.values() if item.get("status") == "pass")
        failed = sum(1 for item in self_items.values() if item.get("status") == "fail")
        pending = sum(1 for item in self_items.values() if item.get("status") == "pending")
        evidence_missing = [label for label, item in self_items.items()
                            if item.get("status") == "evidence_missing"]
        # 状态只由显式 fail 决定：none（值无法识别，如描述性文本）不拖垮结论；
        # evidence_missing（声明通过但无可回查证据）单独点名，按结构违约拦在交付前。
        self_check = {"items": self_items, "passed": passed, "total": len(self_items), "failed": failed,
                      "pending": pending, "evidence_missing": evidence_missing,
                      "status": "fail" if failed else "pass"}
    else:
        self_check = {"items": {}, "passed": 0, "total": len(self_check_items()), "failed": 0,
                      "pending": 0, "evidence_missing": [], "status": "missing"}

    # 1.0.2：脚本不再做任何内容判断（数字/标准号/地域/缺席/金额/措辞均归 AI）。

    # ⑥ 域内核验记录（--verify-file）：业务 Skill 自己的核验器（verify_claims 等）产出。
    # 只做"并入"：verdict 为 fail / 记录指纹失效（答案或证据在核验后被改）按硬错误；
    # 其余 issues 计入核验明细（软提醒）。不要求所有 Skill 都用同一套核验实现。
    verify_record = None
    _content_holder = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    for holder in (payload, _content_holder):
        verify_record = verify_record or holder.get("verifyRecord") or holder.get("verify_record")
    verify_cfg = CONFIG.get("verify") or {}
    verify_state = {"present": False, "verdict": "", "stale": False, "notes": [], "hard": False}
    verify_manual: List[str] = []
    verify_ok = True
    if verify_cfg.get("enabled", True):
        if not verify_record:
            if verify_cfg.get("required"):
                verify_state["hard"] = True
                verify_state["notes"] = ["缺少核验记录（--verify-file 未传入）"]
                verify_ok = False
        else:
            verify_state["present"] = True
            record = verify_record.get("record") if isinstance(verify_record.get("record"), dict) else verify_record
            verdict = str(verify_record.get("verdict") or (record or {}).get("verdict") or "").strip()
            verify_state["verdict"] = verdict
            evidence_items = [{"id": s.get("id"), "url": s.get("url")} for s in sources]
            # 业务侧 digest 口径未对齐时可关闭比对（只采信 verdict/issues），避免"永远 stale"
            stale = (trust_digest.stale_reason(record, answer, evidence_items)
                     if verify_cfg.get("compare_digests", True) else "")
            issues = [str(x) for x in (verify_record.get("issues") or []) if str(x).strip()][:20]
            if stale:
                verify_state["stale"] = True
                if verify_cfg.get("required"):
                    verify_state["hard"] = True
                    verify_state["notes"].append(str(stale))
                    verify_ok = False
                else:
                    verify_manual.append(f"核验记录提示：{stale}")
            if verdict and verdict.lower() != "pass":
                verify_state["hard"] = True
                verify_state["notes"].append("域内核验未通过（verdict=fail）")
                verify_ok = False
            prefix = "核验问题：" if verify_state["hard"] else "核验提示："
            verify_manual.extend(prefix + issue for issue in issues)

    trace_ok = bool(cited_sources) and not bad_ids
    binding_ok = (not unbound) and not no_citation
    # 1.0.2：结构问题不再注入成 AI 验收项——脚本只管结构、AI 只管内容，两轨各自呈现。
    # 自检显式"未通过"纳为报告级否决项：不能自检失败还顶部打绿章。
    # 1.0.2：声明通过但没有可回查证据 = 结构不合规（contract 违约），同样拦在交付前；
    # pending（待人工复核）不算未通过，允许出报告。
    self_check_ok = (self_check["status"] != "fail") and not (self_check.get("evidence_missing") or [])
    # 1.0.2 两轨验收汇总：脚本轨（上面各指标）+ Agent 轨（五项自检与证据）
    agent_track = {
        "enabled": bool(agent_track_config().get("enabled", True)),
        "require_evidence": bool(agent_track_config().get("require_evidence", True)),
        "total": self_check["total"],
        "passed": self_check["passed"],
        "failed": self_check["failed"],
        "pending": self_check.get("pending", 0),
        "evidence_missing": list(self_check.get("evidence_missing") or []),
        "status": self_check["status"],
    }
    # 两轨合流：任一轨判不过即整体未通过，Agent 轨不能用"字面都找到了"翻案脚本轨。
    overall_passed = bool(trace_ok and binding_ok and self_check_ok and verify_ok)

    reasons = []
    if not sources:
        reasons.append("没有找到来源文章")
    if no_citation:
        reasons.append("正文里没有来源角标，对不上来源文章")
    if unbound:
        reasons.append(f"有 {len(unbound)} 处角标找不到对应来源文章")
    if uncitable:
        reasons.append(f"有 {len(uncitable)} 条正文依据为不可引用材料（版本索引/无正文）")
    if self_check["status"] == "fail":
        reasons.append("AI 验收有未通过项")
    if self_check.get("evidence_missing"):
        reasons.append("AI 验收有声明通过但无可回查证据的项")
    if not verify_ok:
        reasons.extend(verify_state["notes"] or ["域内核验未通过"])
    # 缺原文链接/存档快照属回看通道提醒（软项），只进顶部表述与指标行，不进红色失败原因。

    if overall_passed and missing_links:
        # 摘录可比对、结论成立，但确有材料无回看通道时，顶部表述要与事实一致
        overall_label = f"已核验（{len(missing_links)} 条依据无原文或存档快照可回看）" if overall_passed else "核验未通过"
    else:
        overall_label = "已核验" if overall_passed else "核验未通过"

    return {
        "overall": {
            "passed": overall_passed,
            "label": overall_label,
            "reasons": reasons,
        },
        "traceability": {"total": len(cited_sources), "passed": trace_passed,
                         "missing_links": missing_links, "missing_excerpts": missing_excerpts,
                         "uncitable": uncitable},
        "binding": {"total": len(all_marks), "bound": len(all_marks) - len(unbound), "unbound": unbound_ids, "no_citation": no_citation},
        "freshness": freshness,
        "self_check": self_check,
        "agent_track": agent_track,
        "verify": verify_state,
        "manual_checks": list(dict.fromkeys(
            [str(x) for x in (payload.get("verificationChecks") or payload.get("verification_checks") or []) if str(x).strip()]
            + verify_manual
        )),
    }


# ============================================================
# 过程回顾 / 热词（真实计算，不虚构流程）
# ============================================================

def route_kind(channel: str) -> str:
    """按配置的通道关键词把原始通道标记归为 deep / trusted / web。

    通用 JSON 默认无通道约定（route_keywords 为空 → 返回空，统计回退单通道）；
    业务 Skill 在 config.channels.route_keywords 里配置自己的词表。
    """
    text = str(channel or "")
    rules = (CONFIG.get("channels") or {}).get("route_keywords") or {}
    for kind in ("web", "deep", "trusted"):
        for keyword in (rules.get(kind) or []):
            if keyword and keyword in text:
                return kind
    return ""


def channel_label(channel: str) -> str:
    """过程条明细行的通道后缀：config.channels.labels 里 kind→显示名；未配置则空。"""
    kind = route_kind(channel)
    if not kind:
        return ""
    return str((CONFIG.get("channels") or {}).get("labels", {}).get(kind) or "")


def route_summary(deep_n: int, trusted_n: int, n_searches: int) -> str:
    """过程条/hero 的检索摘要：按配置模板拼装；未配置任何模板时按次数显示。"""
    summary = (CONFIG.get("channels") or {}).get("summary") or {}
    parts = []
    if deep_n and summary.get("deep"):
        parts.append(str(summary["deep"]).format(deep=deep_n, trusted=trusted_n, n=n_searches))
    if trusted_n and summary.get("trusted"):
        parts.append(str(summary["trusted"]).format(deep=deep_n, trusted=trusted_n, n=n_searches))
    if parts:
        return " · ".join(parts)
    fallback = str(summary.get("fallback") or "通用检索 {n} 路")
    return fallback.format(deep=deep_n, trusted=trusted_n, n=n_searches)


def channel_tokens(channels: List[str]) -> List[str]:
    """来源行通道 token 汇总：按配置过滤内部通道标记，可做 token 映射。"""
    chan_cfg = CONFIG.get("channels") or {}
    filters = {str(x) for x in (chan_cfg.get("internal_token_filter") or [])}
    token_map = {str(k): str(v) for k, v in (chan_cfg.get("tokens") or {}).items()}
    tokens: List[str] = []
    for channel in channels:
        for token in re.split(r"[、·]", str(channel or "")):
            token = token.strip()
            if not token or token in filters:
                continue
            token = token_map.get(token, token)
            if not token or token in filters:
                continue
            if token not in tokens:
                tokens.append(token)
    return tokens


def compute_process_stats(sources: List[Dict[str, str]], answer: str,
                         calls: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
        # 该路检索的接口通道（通用检索来源/溯源核验报告生成器）：取组内多数通道
        chan_counts: Dict[str, int] = {}
        for s in group:
            ch = (s.get("channel") or "").strip()
            if ch:
                chan_counts[ch] = chan_counts.get(ch, 0) + 1
        channel = max(chan_counts, key=chan_counts.get) if chan_counts else ""
        # 每路调用增量（1.6.0）：merge 的 search_meta.calls 按标签对齐到分组行，
        # 过程条展示『该路新增 N 篇 · 补充 K 段』——补搜的实际贡献不被分组统计吞掉
        delta = ""
        if calls:
            # 同名分组可能对应多条 --input（多个补搜复用同一 --search-key）。
            # 过程条按分组展示，必须汇总该组全部同名 calls；只取第一条会漏算
            # 后续同名路的“新增/补段”增量（2026-11-09 五验待确认项）。
            matched = [c for c in calls if str(c.get("label") or "").strip() == key]
            if not matched:
                matched = [c for c in calls
                           if str(c.get("label") or "").strip()
                           and key.startswith(str(c.get("label")).strip()[:12])]
            if matched:
                new_total = sum(int(c.get("new_articles") or 0) for c in matched)
                added_total = sum(int(c.get("added_paragraphs") or 0) for c in matched)
                delta = f"新增 {new_total} 篇 · 补充 {added_total} 段"
        cond_rows.append({
            "key": key,
            "total": len(group),
            "used": sum(1 for s in group if s.get("used", True)),
            "channel": channel,
            "delta": delta,
        })
    n_searches = len(cond_rows) or (1 if sources else 0)
    # 深度/可信互斥计数（2026-10-16 修复）：多数通道为拼接值（"通用检索来源、溯源核验报告生成器"）
    # 的组同时含两个关键词，若不互斥会被两边各计一次——WB 实测"补搜 10 次"被虚报成 13 次，
    # 与过程条明细行（if/else 口径）自相矛盾。此处与明细行同口径：含"深度"优先归深度。
    deep_routes = sum(1 for r in cond_rows if route_kind(r.get("channel", "")) == "deep")
    trusted_routes = sum(1 for r in cond_rows if route_kind(r.get("channel", "")) == "trusted")
    trusted_web_routes = sum(1 for r in cond_rows
                             if route_kind(r.get("channel", "")) == "trusted"
                             and "联网" in r.get("channel", ""))
    web_routes = sum(1 for r in cond_rows if route_kind(r.get("channel", "")) == "web")
    # 外部材料按 unofficial 判定，覆盖阶段二（溯源核验报告生成器·联网，route_kind=trusted）
    # 与阶段三（宿主 WebSearch）；不能只看 pending/web，否则阶段二口径切换不生效。
    external_materials = sum(1 for s in sources if s.get("unofficial") or s.get("pending"))
    used_count = sum(1 for s in sources if s.get("used", True))
    unused_count = len(sources) - used_count
    n_cite_marks = len(re.findall(r"\[(\d+)\]", answer))
    return {
        "conds": cond_rows,
        "n_searches": n_searches,
        "deep_routes": deep_routes,
        "trusted_routes": trusted_routes,
        "trusted_web_routes": trusted_web_routes,
        "web_routes": web_routes,
        "external_materials": external_materials,
        "has_cond_detail": bool(cond_rows),
        "n_materials": len(sources),
        "used_count": used_count,
        "unused_count": unused_count,
        "n_cite_marks": n_cite_marks,
    }


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


def _safe_url(url: str) -> str:
    """外链协议白名单（1.6.0）：仅允许 http/https，其余（javascript:/data: 等）置空不渲染。

    2026-11-09 审核补充：拒绝带 userinfo 的 URL（https://user:pass@host/...），
    避免凭据被原样写进报告。
    """
    value = str(url or "").strip()
    if value.lower().startswith(("http://", "https://")):
        if re.match(r"^https?://[^/?#]*@", value, re.I):
            return ""
        return value
    return ""


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
        if closing:
            return f"</{name}>"
        attrs = ""
        if name in ("td", "th"):
            raw = match.group(0)
            for attr in ("colspan", "rowspan"):
                found = re.search(rf"{attr}\s*=\s*[\"']?(\d+)", raw, re.I)
                if found:
                    attrs += f' {attr}="{found.group(1)}"'
        return f"<{name}{attrs}>"

    cleaned = re.sub(r"<\s*(/?)\s*([a-zA-Z0-9]+)(?:\s+[^>]*)?>", tag_repl, cleaned)
    # thead 修复（1.6.0，对齐公文写作 3.9.0）：接口偶发把数据行整片包在 thead 里，
    # 清洗后若直接透传会全部渲染成表头底色。逐表处理：表内任意 thead 含 ≥2 个 <tr>
    # 时，按文档顺序取全部行重建为「首行 thead + 其余 tbody」，行内容不变。
    def fix_table(m_t: re.Match[str]) -> str:
        block = m_t.group(0)
        # 嵌套表不能按单层行重建，否则内外层 tbody 会错位；保持原结构（同步多引擎 1.0.1）。
        if len(re.findall(r"(?is)<table\b", block)) > 1:
            return block
        rows = re.findall(r"(?is)<tr>.*?</tr>", block)
        thead_rows = re.findall(r"(?is)<tr>.*?</tr>", 
                                (re.search(r"(?is)<thead>(.*?)</thead>", block) or re.match(r"", "")).group(1)
                                if re.search(r"(?is)<thead>(.*?)</thead>", block) else "")
        if len(thead_rows) <= 1 or len(rows) <= 1:
            return block
        return "<table><thead>" + rows[0] + "</thead><tbody>" + "".join(rows[1:]) + "</tbody></table>"

    return re.sub(r"(?is)<table>.*?</table>", fix_table, cleaned)


def render_excerpt_html(text: str) -> str:
    value = str(text or "")
    if "<table" not in value.lower():
        return f'<div class="sc-excerpt plain">{esc(value)}</div>'
    return f'<div class="sc-excerpt rich">{sanitize_table_html(value)}</div>'


def parse_answer_blocks(answer: str, valid_ids: set, chip_map: Optional[Dict[str, str]] = None,
                         strip_cites: bool = False) -> Tuple[List[Dict[str, Any]], set]:
    """把正文 Markdown 解析为结构化块；同时收集全部角标。

    角标渲染为原型式 sup.cite 上标胶囊；段落对应的溯源卡（src-card）由
    render_section_cards 在段后输出。
    """

    def jb_html(cid: str) -> str:
        jb = chip_map.get(cid)
        if not jb:
            return ""
        if jb.get("url"):
            btn_txt = "查看全文" if jb.get("url") else "查看存档全文"
            _u = _safe_url(jb["url"])
            link = (f'<a class="jb-src" href="{esc(_u)}" target="_blank" rel="noopener noreferrer">'
                    f'{ARROW_SVG}<span>{btn_txt}</span></a>') if _u else ""
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
        if jb.get("unofficial"):
            _unofficial_text = "非官方来源"
            site_html = (f'<span class="jb-unofficial" title="公开网络检索的非官方来源，仅供参考，建议以官方口径复核">{_unofficial_text}</span>'
                         + site_html)
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
        最后一处挂数字角标 + 引文胶囊——一段中同一材料只出现一次。
        正文页（strip_cites=True）直接删掉全部角标，输出干净正文。"""
        if strip_cites:
            return lambda match: ""
        remaining: Dict[str, int] = {}
        for cid in re.findall(r"\[(\d+)\]", block_text):
            remaining[cid] = remaining.get(cid, 0) + 1

        def repl(match: re.Match[str]) -> str:
            cid = match.group(1)
            remaining[cid] = max(0, remaining.get(cid, 1) - 1)
            if remaining[cid] > 0:
                return ""
            if cid in chip_map:
                # 行内只保留一个可点击的引用编号；点编号弹出该来源的引用卡，
                # 完整摘录统一放知识专库，不再在正文里塞标题胶囊和全部段落。
                return (f'<sup class="cite"><a class="cite-link" href="#src-{esc(cid)}" '
                        f'data-cite="{esc(cid)}" title="查看引用依据 [{esc(cid)}]">[{esc(cid)}]</a></sup>')
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
        # 连续角标序列须整体换位（如 [13][14]；），否则标点被夹在两个胶囊中间
        block = re.sub(r"((?:\[\d+\])+)([。；，、！？：；,.])", r"\2\1", block)
        ids = [] if strip_cites else citation_ids(block)
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
            blocks.append({"kind": "table", "html": render_markdown_table(table_lines, repl),
                           "cites": [] if strip_cites else citation_ids("\n".join(table_lines))})
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
        site_bits = ([source["doc_number"]] if source.get("doc_number") else []) + meta_bits
        chip_map[cid] = {
            "title": short(source.get("title") or "未命名来源文章", 30),
            "site": " · ".join(site_bits) or "来源站点",
            "url": url,
            "snapshot": source.get("snapshot") or "",
            "excerpt": (source.get("excerpt") or "").strip(),
            "segments": source.get("segments") or [],
            "unofficial": bool(source.get("unofficial")),
            "pending": bool(source.get("pending")),
        }
    return chip_map


def render_source_links(url: str, policy_url: str = "", snapshot: str = "") -> str:
    """链接区：原文可回看 / 无源网址但有快照。接口返回的链接原样展示（不做活性探测，
    2026-10-08 起）；快照是接口对原文的存档副本，文案如实标注。"""
    links = []
    if _safe_url(url) and url != "接口未返回":
        links.append(f'<a href="{esc(_safe_url(url))}" target="_blank" rel="noopener">查看全文 ↗</a>')
    # 有哪个显示哪个：快照统一展示"查看存档全文"，不做原文失效的状态解释
    if _safe_url(snapshot):
        links.append(f'<a class="snap" href="{esc(_safe_url(snapshot))}" target="_blank" rel="noopener">查看存档全文 ↗</a>')
    # 回看通道只有原网址与快照（2026-09-29 起：外链知识专库属老能力，已移除）
    if not links:
        return ""
    return '<div class="sc-links">' + "".join(f"<span>{link}</span>" for link in links) + "</div>"


def render_verify_panel(v: Dict[str, Any]) -> str:
    """核验报告单：报告级核验结论 + 五项指标。"""
    # 核验明细（逐条"已完成…"文本可能很长）默认折叠，点开才展开——不用悬浮 tooltip（触屏不可用）
    _checks = [str(x) for x in (v.get("manual_checks") or []) if str(x).strip()]
    manual_checks_html = ""
    if _checks:
        _items = "".join(f"<li>{esc(x)}</li>" for x in _checks)
        manual_checks_html = (f'<details class="v-checks"><summary>查看核验明细（{len(_checks)} 项）</summary>'
                              f'<ul>{_items}</ul></details>')
    ov = v["overall"]
    state = "ok" if ov["passed"] else "fail"
    stamp = '<span class="v-stamp">已核验</span>' if ov["passed"] else '<span class="v-stamp bad">核验未通过</span>'
    reasons_html = ""
    if ov["reasons"]:
        reasons_html = '<div class="v-reasons">' + "；".join(esc(r) for r in ov["reasons"]) + "</div>"

    tr = v["traceability"]
    n_no_link = len(tr.get("missing_links") or [])
    if not tr["total"]:
        tr_html = ('<div class="vi"><span class="s fail">✗ 依据溯源 0/0</span>'
                   '<span class="d">未识别到来源文章</span></div>')
    elif tr["passed"] == tr["total"] and not n_no_link:
        tr_html = (f'<div class="vi"><span class="s ok">✓ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">每条素材摘录可比对，原文或存档快照可回看</span></div>')
    elif tr["passed"] == tr["total"]:
        # 软提醒：缺原文链接不改变“已核验”，但要点名无法回看的条数。
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">{n_no_link} 条没有原文链接或存档快照、无法回看</span></div>')
    else:
        detail = f'待补摘录 {len(tr.get("missing_excerpts") or [])} 条'
        if tr.get("uncitable"):
            detail += f'；不可引用 {len(tr["uncitable"])} 条'
        if n_no_link:
            detail += f'；{n_no_link} 条无原文链接或快照'
        tr_html = (f'<div class="vi"><span class="s warn">◐ 依据溯源 {tr["passed"]}/{tr["total"]}</span>'
                   f'<span class="d">{detail}</span></div>')

    bd = v["binding"]
    if bd.get("no_citation"):
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 0/0</span>'
                   f'<span class="d">正文里没有来源角标，{v["traceability"]["total"]} 篇来源文章对不上正文</span></div>')
    elif not bd["total"]:
        bd_html = '<div class="vi"><span class="s none">— 引用对应 0/0</span><span class="d">正文里没有来源角标</span></div>'
    elif not bd["unbound"]:
        bd_html = (f'<div class="vi"><span class="s ok">✓ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">正文每一处引用都已对回来源文章，点开即可核对原文</span></div>')
    else:
        unbound_text = "、".join(f"[{esc(x)}]" for x in bd["unbound"][:8])
        bd_html = (f'<div class="vi"><span class="s fail">✗ 引用对应 {bd["bound"]}/{bd["total"]}</span>'
                   f'<span class="d">对不上的角标 {unbound_text}</span></div>')

    fr = v["freshness"]
    if fr:
        rng = f"{fr['min'][0]}-{fr['min'][1]:02d}～{fr['max'][0]}-{fr['max'][1]:02d}"
        # 2026-09-29 起：去掉"N 条年头较久，按参考口径使用"——对长期有效的
        # 政策法规偏严，且"按参考口径使用"读者无从理解；old_count 仍照常计算留待后续。
        fr_html = f'<div class="vi"><span class="s ok">✓ 材料新旧 已核</span><span class="d">材料日期 {esc(rng)}</span></div>'
    else:
        fr_html = '<div class="vi"><span class="s none">— 材料新旧 未记录</span><span class="d">材料没标发布日期</span></div>'

    # 材料构成：类型分类依赖输入的 类型 字段，而它与实际文体常年对不上（官方公告显示成
    # "材料"、第三方网页显示成"政策依据"），界定成本高、对读者无决策价值，不再展示；
    # 正文依据条数已由「依据溯源 N/N」直接给出。
    # 域内核验行（--verify-file）：只在业务 Skill 传入核验记录时出现
    vr = v.get("verify") or {}
    verify_html = ""
    if vr.get("present"):
        if vr.get("hard"):
            detail = "；".join(vr.get("notes") or []) or "域内核验未通过"
            verify_html = (f'<div class="vi"><span class="s fail">✗ 域内核验 未通过</span>'
                           f'<span class="d">{esc(short(detail, 120))}</span></div>')
        else:
            verify_html = ('<div class="vi"><span class="s ok">✓ 域内核验 已通过</span>'
                           '<span class="d">结论台账校验记录已并入本核验单</span></div>')

    sc = v["self_check"]
    at = v.get("agent_track") or {}
    selfcheck_notes_html = ""
    am = list(sc.get("evidence_missing") or [])
    pend = int(sc.get("pending") or 0)
    total = sc["total"]
    verdict_zh = {"pass": "通过", "fail": "未通过", "pending": "待人工复核",
                  "evidence_missing": "证据不足", "none": "未记录"}

    def _item_text(label: str, item: dict) -> str:
        parts = [f"结论：{verdict_zh.get(item.get('status'), '未记录')}"]
        basis = (item.get("basis") or "").strip()
        if basis:
            parts.append(f"依据：{basis[:160]}")
        ev = [x for x in (item.get("evidence") or []) if x and x != basis][:3]
        if ev:
            parts.append("证据：" + "；".join(x[:90] for x in ev))
        if item.get("missing"):
            parts.append(item["missing"])
        return " ｜ ".join(parts)

    if sc["status"] == "pass":
        clean = not am and not pend
        cls = "ok" if clean else "warn"
        mark = "✓" if clean else "◐"
        head = f'AI 验收 {sc["passed"]}/{total} 有据'
        detail_parts = []
        if am:
            detail_parts.append(f"{len(am)} 项证据不足（{'、'.join(am[:3])}{'…' if len(am) > 3 else ''}）")
        if pend:
            detail_parts.append(f"{pend} 项待人工复核")
        sc_html = (f'<div class="vi"><span class="s {cls}">{mark} {head}</span>'
                   f'<span class="d">{esc("；".join(detail_parts) if detail_parts else "各项目均给出可回查证据")}</span></div>')
        items = [(label, item) for label, item in sc["items"].items()]
        if items:
            _li = "".join(f"<li><b>{esc(label)}</b>：{esc(_item_text(label, item))}</li>" for label, item in items)
            selfcheck_notes_html = (
                f'<details class="v-checks"><summary>查看 AI 验收明细（{len(items)} 项）</summary>'
                f'<ul>{_li}</ul></details>')
    elif sc["status"] == "fail":
        failed_parts = []
        for label, item in sc["items"].items():
            if item.get("status") == "fail":
                note = (item.get("basis") or "")[:40]
                failed_parts.append(label + (f"（{note}）" if note else ""))
        sc_html = (f'<div class="vi"><span class="s fail">✗ AI 验收 {sc["passed"]}/{total}</span>'
                   f'<span class="d">没过的项：{esc("、".join(failed_parts))}</span></div>')
        items = [(label, item) for label, item in sc["items"].items()]
        if items:
            _li = "".join(f"<li><b>{esc(label)}</b>：{esc(_item_text(label, item))}</li>" for label, item in items)
            selfcheck_notes_html = (
                f'<details class="v-checks"><summary>查看 AI 验收明细（{len(items)} 项）</summary>'
                f'<ul>{_li}</ul></details>')
    else:
        sc_html = '<div class="vi"><span class="s none">— AI 验收 未记录</span>' \
                  '<span class="d">本次输入没有写入 Agent 验收结论</span></div>'

    manual = ""

    return f"""
    <div class="verify {state}">
      <div class="v-head"><span class="v-shield">{'✓' if ov['passed'] else '!'}</span>{esc(ov['label'])}{stamp}</div>
      {reasons_html}
      <div class="v-grid">
        <div class="vi" style="grid-column:1/-1"><span class="s none">结构核验</span><span class="d">报告结构自检：依据溯源 / 引用对应 / 材料新旧</span></div>
        {tr_html}{bd_html}{fr_html}{verify_html}
        <div class="vi" style="grid-column:1/-1"><span class="s none">AI 验收</span><span class="d">按既定标准逐项判定，并留下可回查的证据</span></div>
        {sc_html}{manual}
      </div>
      <div class="v-note">结论 = 结构核验 ∧ AI 验收；任一轨不过则不出报告，修正后重跑。正文依据可逐条点开原文复核。{selfcheck_notes_html}{manual_checks_html}</div>
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
    link_html = (f'<a class="src-link" href="{esc(_safe_url(url))}" target="_blank" rel="noopener noreferrer">查看全文{ARROW_SVG}</a>' if _safe_url(url) else "")
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


_CN_DIGITS = {"〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5",
              "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def _norm_heading(text: Any) -> str:
    return re.sub(r"[\s、，,。.：:；;（）()\[\]【】]+", "", str(text or ""))


def _cn_to_digit(text: str) -> str:
    return _CN_DIGITS.get(text.strip(), text.strip())


def resolve_chart_anchor(sections: List[Dict[str, Any]], anchor: Any) -> int:
    """把图表的 section 锚点解析为章节序号（1-based）；解析不到返回 0。

    锚点容错：可写章节号（`二` / `2` / `二、`）、章节标题（`一次性奖励金额对比`）、
    或带序号的完整标题（`二、一次性奖励金额对比`）——统一去空白与顿号后按
    「序号相等」或「标题互相包含」匹配。
    """
    raw = _norm_heading(anchor)
    if not raw:
        return 0
    want_num = _cn_to_digit(raw[0]) if raw and _cn_to_digit(raw[0]).isdigit() else ""
    for idx, sec in enumerate(sections, 1):
        number, title_text = split_heading_number(sec["title"] or "")
        if want_num and number and _cn_to_digit(_norm_heading(number)) == want_num and len(raw) == 1:
            return idx
        title_norm = _norm_heading(title_text)
        if title_norm and (title_norm in raw or raw in title_norm):
            return idx
    return 0


def render_section_cards(sections: List[Dict[str, Any]], sources: List[Dict[str, str]],
                         charts_by_section: Optional[Dict[int, str]] = None,
                         id_prefix: str = "sec") -> str:
    """正文渲染（原型复刻）：chapter（h2）+ lead/para 段落 + 段后 src-card 溯源卡。

    溯源卡按段内角标顺序输出；同一材料在同段只出一张，跨段重复出现标记 dup-card（灰化）。
    charts_by_section：{章节序号: 图表 HTML}——图表**跟着它展示的数据所在的章节走**
    （1.4.0：不再固定堆在报告末尾），插在该章节正文之后。
    """
    parts: List[str] = []
    first_para = True
    source_ids = {s["id"] for s in sources}
    charts_by_section = charts_by_section or {}
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
                # 章节徽标只判结构（1.0.2）：该章引用的全部材料可作依据（有摘录、可引用）；
                # 内容是否被原文支持归 AI 验收，脚本不背书。
                _sec_sources = [s for s in sources if s.get("id") in sec_cites]
                _bad = [s for s in _sec_sources
                        if s.get("citable") is False or not (s.get("excerpt") or "").strip()]
                if unbound:
                    state = "bad"
                    text = f"本章引用 {len(sec_cites)} 处 · {unbound} 处未绑定"
                elif _bad:
                    state = "bad"
                    text = f"本章引用 {len(sec_cites)} 处 · {len(_bad)} 条不可作依据"
                else:
                    state = ""
                    text = f"本章引用 {len(sec_cites)} 处 · 已核验"
                badge_html = f'<span class="sec-badge {state}">{esc(text)}</span>'
            parts.append(f'<section class="chapter" id="{id_prefix}-{sec_idx}">'
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
            if sec_idx in charts_by_section:
                parts.append(charts_by_section[sec_idx])
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
    """面包屑标题链：文章 › 章 › 节（标题链是模型生成的结构化位置，核验核心抓手）。
    段落本身无章节层级（链上只有文章名）时不显示——材料卡标题已是文章名，
    单独一行重复文章名对定位无增量（2026-09-19 反馈）。"""
    parts = [esc(level) for level in chain if level]
    if len(parts) < 2:
        return ""
    return '<span class="crumb">' + ' <i>›</i> '.join(parts) + "</span>"


def render_segments(source: Dict[str, Any]) -> str:
    """多段分块摘录：每段独立区块，各带自己的标题链——段落结构与位置直接可见。"""
    segments = source.get("segments") or []
    if not segments:
        if not source.get("used", True):
            return '<div class="seg-empty">未引用，未进入正文</div>'
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
              else '<span class="sc-vk" style="color:var(--muted)" title="本条未返回原文链接，可查看接口返回的原文摘录">可查看摘录</span>')
        note_html = ""
    elif source.get("citable") is False:
        reason = source.get("uncitable_reason") or "版本索引记录，无正文，不可引用"
        vk = f'<span class="sc-vk warn" title="{esc(reason)}">◐ 不可引用</span>'
        note_html = f'<div class="sc-vnote">{esc(short(reason, 90))}</div>'
    elif source.get("verified"):
        # 1.0.2：来源卡只标结构状态（有可展开摘录、材料可引用），不标"内容核验通过"——
        # 内容是否被原文支持由 AI 验收判定，脚本不背书。
        note = source.get("verify_note") or "摘录可比对，原文或存档快照可回看"
        vk = f'<span class="sc-vk ok" title="{esc(note)}">✓ 可作为正文依据</span>'
        note_html = f'<div class="sc-vnote">{esc(short(note, 90))}</div>' if source.get("verify_note") else ""
    else:
        reason = "待补原文链接" if not source.get("has_link") else "待补摘录"
        vk = f'<span class="sc-vk warn">◐ {reason}</span>'
        note_html = ""
    links = render_source_links(source.get("url"), source.get("policy_url", ""), source.get("snapshot", ""))
    # 关键性行：有文号（接口 policyFiles 匹配）时"文号 · 发文机构/来源 · 日期"，否则"发文机构/来源 · 日期"。
    # 文号必须是标准格式——政府公文"〔年份〕序号"（杭政函〔2022〕81号）、公告/令类"第X号"
    # （财政部税务总局公告2023年第19号、主席令第三十五号、国务院令第765号，含汉字数字）；
    # 描述性文字（"XX印发"类自造描述）不显示，当无文号处理。
    _dn = source.get("doc_number") or ""
    _dn = _dn if re.search(r"〔\d{4}〕\s*\d+\s*号|第\s*(?:\d+|[〇零一二三四五六七八九十百千]+)\s*号", _dn) else ""
    meta_parts = [v for v in [_dn, source.get("agency"), source.get("date"), source.get("area")]
                  if v and v != "未知来源"]
    meta = " | ".join(meta_parts)
    # 高可信徽标：仅"发布日期可信度=高"（模型治理入库、标题模型精抽）的材料；"较高"（门户抓取）不标。
    conf_badge = ""
    if source.get("conf") == "高":
        conf_badge = ('<span class="sc-conf" title="发布日期可信度：高。内容经模型治理入库，'
                      '标题为模型从原文动态抽取，非规则提取">高可信</span>')
    # 已引用材料显示角标编号；未引用召回材料显示"未引用"灰标（不占正文角标号）
    id_html = f'<span class="sc-id">[{esc(source["id"])}]</span>' if source.get("used", True) else '<span class="sc-unused">未引用</span>'
    # 非官方来源徽标：联网路召回的非权威站点材料，报告页与知识专库卡统一标注；
    # 其中政府域名/官方机构名的归为「公开网络·官方」（官方信源不应作为问题）。
    _unofficial_text = "非官方来源"
    official_badge = ('<span class="sc-official" title="公开网络检索到的官方信源（政府机构/法定机构），请以原文复核">公开网络·官方</span>'
                      if source.get("official_external") else "")
    unofficial_badge = (f'<span class="sc-unofficial" title="公开网络检索的非官方来源，仅供参考，建议以官方口径复核">{_unofficial_text}</span>'
                        if source.get("unofficial") else "")
    # 来源卡不再显示"材料类型"标签——输入的类型字段与实际文体常年对不上，界定成本高、
    # 对读者无决策价值。卡片只保留有明确事实依据的徽标：高可信、公开网络·官方／非官方来源、引用核验态。
    body_html = (f'<div class="sc-head">{id_html}'
                 f'{conf_badge}{official_badge}{unofficial_badge}{vk}</div>'
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
    # 步骤一标题按接口通道拆分（检索来源/公开网络/宿主 WebSearch 是不同通道，不混计）；
    # 无通道信息（历史 JSON）时退回"通用检索 N 路"
    deep_n = stats.get("deep_routes", 0)
    trusted_n = stats.get("trusted_routes", 0)
    step1_title = route_summary(deep_n, trusted_n, stats["n_searches"])
    detail_rows = "".join(
        f'<div class="pd-row"><b>{esc(row["key"])}'
        + (f'（{esc(channel_label(row.get("channel", "")))}）'
           if channel_label(row.get("channel", ""))
           and channel_label(row.get("channel", "")) != row["key"] else "")
        + f'</b><span>召回 {row["total"]} 条 · 正文采用 {row["used"]} 条'
        + (f' · {esc(row["delta"])}' if row.get("delta") else '')
        + '</span></div>'
        for row in stats["conds"]
    ) or '<div class="pd-row"><span>本次溯源 JSON 未记录各次检索条件</span></div>'
    detail_hint = f'{esc(short(first_query, 26))}…' if (stats["n_searches"] > 1 and first_query) else "查看检索明细"
    if stats["n_searches"] > 1:
        step1_sub = f"共 {stats['n_searches']} 路检索 · {detail_hint}"
    elif first_query:
        step1_sub = esc(short(first_query, 26))
    else:
        step1_sub = str((CONFIG.get("channels") or {}).get("step1_fallback") or "通用检索")
    step4_state = "done" if ov["passed"] else "bad"
    step4_icon = "✓" if ov["passed"] else "!"
    step4_label = "已核验" if ov["passed"] else "核验未通过"
    step4_sub = (
        "结论：正文依据逐条对过来源（公开网络材料已标注非官方来源）"
        if ov["passed"] and stats.get("external_materials")
        else "结论：正文依据逐条对过原文" if ov["passed"]
        else esc(short("；".join(ov["reasons"]) or "见核验报告单", 30))
    )
    # 研究资料统计（1.5.0）：--research-notes-file 传入时在步骤 2 体现（事实/口径行数）；
    # 未传不显示（如实，不虚构）
    rn = stats.get("research_notes") or {}
    rn_bits = ""
    if rn.get("facts") is not None:
        rn_bits = f"研究资料 {rn['facts']} 项事实 · {rn.get('calibers', 0)} 项口径 ｜ "

    return f"""
    <section class="process" aria-label="AI 自验收">
      <div class="p-head"><b>AI 自验收</b><span>交付前由 AI 自动完成，数字来自本次任务的真实记录</span></div>
      <ol class="p-steps">
        <li class="p-step expandable" id="p-step-search" role="button" tabindex="0" title="展开各路检索明细">
          <span class="p-no">1</span>
          <div class="p-txt"><b>{esc(step1_title)}</b><i>{step1_sub}</i></div>
        </li>
        <li class="p-arrow" aria-hidden="true">›</li>
        <li class="p-step">
          <span class="p-no">2</span>
          <div class="p-txt"><b>来源文章入库 {stats['n_materials']} 篇</b><i>{rn_bits}正文采用 {stats['used_count']} · 召回未采用 {stats['unused_count']}</i></div>
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


def render_library_view(sources: List[Dict[str, str]], doc_title: str = "") -> str:
    """知识专库全屏视图：大搜索 + 检索分组 tabs + 材料卡列表。"""
    if not sources:
        return ('<section class="view" id="view-library" aria-label="知识专库">'
                '<div class="lib-empty">接口返回中未识别到可展示的来源文章。</div></section>')
    used_sources = [s for s in sources if s.get("used", True)]
    unused_sources = [s for s in sources if not s.get("used", True)]
    if not used_sources:
        return ('<section class="view" id="view-library" aria-label="知识专库">'
                '<div class="lib-empty">正文未引用任何来源文章。</div></section>')

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
    # 分组过多时折叠（2026-10-14）：多轮检索+补搜会产生 10+ 个分组 tab 平铺拥挤；
    # 按材料数降序保留前 6 组，其余收进"更多分组（N）"展开区（筛选功能不变）
    shown, folded = conds, []
    if len(conds) > 6:
        ranked = sorted(range(len(conds)), key=lambda i: -conds[i][1])
        keep = set(ranked[:6])
        shown = [c for i, c in enumerate(conds) if i in keep]
        folded = [c for i, c in enumerate(conds) if i not in keep]
    for name, count in shown:
        tabs.append(f'<button data-cond="{esc(name)}" type="button">{esc(name)}（{count}）</button>')
    if folded:
        fold_btns = "".join(f'<button data-cond="{esc(name)}" type="button">{esc(name)}（{count}）</button>'
                            for name, count in folded)
        tabs.append(f'<button class="tabs-toggle" type="button" aria-expanded="false">更多分组（{len(folded)}）</button>'
                    f'<span class="tabs-fold">{fold_btns}</span>')
    # 「未引用（N）」筛选胶囊已删（3.8.1 起整行占位、信息由卡片"未引用"灰标自表达）；
    # JS 的 __unused__ 过滤分支保留为兼容死代码

    cards_html = "".join(render_source_card(s) for s in used_sources)
    # 未进入正文的召回材料保留为参考资料，展示原文摘录，供用户判断是否值得回看。
    unused_html = "".join(render_source_card(s) for s in unused_sources)
    # 折叠区标题计数由 JS 随筛选动态更新（1.0.1）：data-total 保存全量数，
    # lu-title 在选中分组/搜索词时改为"本组未进入正文的参考材料（N）"。
    unused_block = (f'<details class="lib-unused" open data-total="{len(unused_sources)}">'
                    f'<summary><span class="lu-title">未进入正文的参考材料（{len(unused_sources)}）</span>'
                    f' · 供参考，未参与答案结论</summary><div class="lib-list">{unused_html}</div></details>'
                    if unused_sources else "")
    # 只有一组检索条件时，“全部/本次检索”两个 tab 完全重复，直接隐藏。
    tabs_html = (f'<div class="lib-tabs" role="tablist" aria-label="按检索分组筛选">{"".join(tabs)}</div>'
                 if len(conds) > 1 else "")

    lib_title = f"知识专库：{doc_title}" if doc_title.strip() else "知识专库"
    has_external = any(s.get("unofficial") or s.get("pending") for s in sources)
    lib_foot = (brand_text("lib_foot_source") if not has_external
                else brand_text("lib_foot_external"))
    return f"""
    <section class="view" id="view-library" aria-label="知识专库">
      <div class="lib-head">
        <div class="lib-title"><b>{esc(lib_title)}</b></div>
        <div class="lib-searchWrap">
          <span class="lib-searchIcon" aria-hidden="true">⌕</span>
          <input class="lib-search" type="search" placeholder="搜索标题 / 来源 / 摘录…" aria-label="搜索来源文章">
        </div>
        {tabs_html}
      </div>
      <div class="lib-list" id="lib-list">{cards_html}</div>
      {unused_block}
      <div class="lib-empty hide" id="lib-empty">没有符合当前筛选的来源文章。</div>
      <div class="lib-foot">{esc(lib_foot)}</div>
    </section>"""


def render_toc(sections: List[Dict[str, Any]], extra: str = "") -> str:
    """章节目录（滚动 spy）：长报告（≥6 个**有标题**的章节）显示，桌面端左侧浮动。

    无标题节（正文开头的导语段）跳过——此前兜底成「第 N 节」占位项，且该锚点
    #sec-i 在 render_section_cards 里根本不生成（死链接），点它没反应。
    extra 为附加条目 HTML（图表独立呈现时）；门槛按有标题章节数计。
    """
    items = []
    for i, sec in enumerate(sections, 1):
        title = (sec.get("title") or "").strip()
        if not title:
            continue  # 导语内容照常在正文展示，只是不占目录条目
        number, title_text = split_heading_number(title)
        label = f"{number} {title_text}" if (number and title_text) else title_text
        items.append(f'<a href="#sec-{i}" data-sec="{i}">{esc(short(label, 16))}</a>')
    if len(items) < 6 and not extra:
        return ""
    items.append(extra)
    return f'<nav class="toc" aria-label="章节目录">{"".join(items)}</nav>'


def render_print_appendix(sources: List[Dict[str, str]]) -> str:
    """打印归档附录：全部材料卡全展开（屏幕不显示，仅打印）。"""
    if not sources:
        return ""
    cards = "".join(render_source_card(s, for_print=True) for s in sources)
    return (f'<section class="print-appendix" aria-label="来源文章附录（打印归档）">'
            f'<h3>来源文章（全 {len(sources)} 篇）</h3>{cards}</section>')


def safe_output_filename(question: str, timestamp: datetime, fallback: str = "dknowc_search_trace", suffix_ext: str = ".html") -> str:
    raw = question.strip() or fallback
    # 清理对话指令性措辞（1.4.0）：文件名用主题本身，不保留"帮我梳理一下…做个系统"这类口吻
    # （实测：WB 交付物文件名直接带用户原话的"帮我梳理一下…做个系统"，冗长且不像正式交付名）
    for _ in range(3):  # 反复剥离直到无变化（如"请帮我…一下吧"）
        before = raw
        raw = re.sub(r"^(请|麻烦|帮我|帮忙|给我|我想|想问下|请问|你能|帮我看看|帮我看下)+", "", raw)
        # 只剥离明确不是主题词的整理类动词（"分析/对比"等可能是主题的一部分，如"分析化学"，不剥离）
        raw = re.sub(r"^(梳理|整理|汇总|总结|归纳|罗列)(一下)?", "", raw)
        raw = re.sub(r"(一下|吧|谢谢|多谢|可以吗|好吗|行吗|呢)+$", "", raw)
        raw = re.sub(r"(做个?系统(对比|比较|梳理)?|系统对比|系统梳理|对比一下|整理一下|汇总一下|总结一下)$", "", raw)
        raw = raw.strip(" ，,。.、！!？?~～")
        if raw == before:
            break
    raw = raw or question.strip() or fallback
    normalized = re.sub(r"\s+", "_", raw)
    normalized = re.sub(r"[\\/:*?\"<>|#%&{}$!@`+=;'，。、？！：；“”‘’（）()【】《》\[\]]+", "", normalized)
    normalized = normalized.strip("._-")
    if not normalized:
        normalized = fallback
    # 产物名优先由 Agent 通过 --output 指定（简短的标题式文件名）；
    # 本函数仅作未指定时的兜底：问题截断 32 字、空格转下划线。
    # 内部重跑覆盖同名文件，版本编号只在交付层产生（2026-11-23 起）
    stem = normalized[:32].strip("._-") or fallback
    return f"{stem}{suffix_ext}"


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

/* ===== 数据可视化（1.4.0 一体化：图表并入核验报告，不再另出独立报告） ===== */
/* 主形态：图表跟着它展示的数据所在章节走（.chart-inline 插在该章节正文之后） */
.chart-inline{margin:18px 0 4px;padding-top:14px;border-top:1px dashed var(--line)}
.chart-h3{margin:0 0 4px;font-size:14px;font-weight:600;color:var(--ink)}
/* 退化形态：锚点缺失/匹配不上时，作为独立章节排在核验报告单之后、正文之前 */
.chart-section{background:#fff;border-radius:14px;box-shadow:var(--shadow-1);padding:22px 26px 18px;margin:0 0 16px}
.chart-h2{margin:0 0 6px;font-size:16px;line-height:1.4}
.chart-note{margin:0 0 14px;color:var(--muted);font-size:12px}
.chart-section .card,.chart-inline .card{box-shadow:none;padding:0;border:0;background:transparent}
.chart-section .viz-panel h3,.chart-inline .viz-panel h3{margin:0 0 6px;font-size:13.5px;font-weight:600;color:var(--ink)}
.viz-duo{display:grid;grid-template-columns:1fr 1fr;gap:8px 18px;align-items:start}
@media(max-width:900px){.viz-duo{grid-template-columns:1fr}}

/* ===== 顶栏 ===== */
.banner{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.94);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);padding:8px 22px 9px}
.banner-bar{display:flex;align-items:center;gap:14px;max-width:1080px;margin:0 auto}
.banner-bar .tb-title{flex:0 1 auto;min-width:0;max-width:30%;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;color:var(--muted);font-size:12.5px}
.banner-bar .view-switch{margin:0 auto}
.banner-bar .tb-tools{flex:0 0 auto}
.banner-bar .view-switch{border-color:#d9c9f4;background:#fff;box-shadow:0 1px 3px rgba(24,20,40,.04)}
.banner-bar .view-switch button{color:#70678a;padding:6px 18px;font-size:13px}
.banner-bar .view-switch button.on{background:var(--grad);color:#fff}
.banner .orig-q{max-width:1080px;margin:7px auto 0;color:var(--ink);font-size:13.5px;line-height:1.6;text-align:center}
.banner .orig-q b{color:var(--brand);margin-right:2px}
.banner .meta{max-width:1080px;margin:3px auto 0;color:var(--muted);font-size:11.5px;letter-spacing:.3px;text-align:center}
  vertical-align:middle;margin:0 6px}
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


/* ===== 容器与视图 ===== */
.container{max-width:1080px;margin:0 auto;padding:0 18px}
#view-body,#view-report,#view-library{display:none}
.app[data-view="body"] #view-body{display:block}
.app[data-view="report"] #view-report{display:block}
.app[data-view="library"] #view-library{display:block}
#view-body{padding-bottom:26px}
/* 文头标题（正文页/报告页各自成档的居中标题） */
.paper-title{margin:14px 0 18px;font-size:20px;font-weight:800;color:var(--ink);text-align:center;line-height:1.55;letter-spacing:.3px}
@media (max-width:680px){.paper-title{font-size:17.5px;margin-bottom:16px}}

/* ===== 过程回顾条 ===== */
.process{background:#fff;border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow-1);
  padding:15px 20px 13px;margin:0 auto 16px;position:relative}
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
.v-checks{margin-top:9px}
.v-checks summary{cursor:pointer;color:var(--brand);font-weight:700;font-size:12.5px;list-style:none;display:inline-flex;align-items:center;gap:5px}
.v-checks summary::-webkit-details-marker{display:none}
.v-checks summary::before{content:"＋";font-weight:700;font-size:12px}
.v-checks[open] summary::before{content:"－"}
.v-checks ul{margin:7px 0 0 4px;padding-left:16px}
.v-checks li{font-size:12.5px;color:var(--sub);line-height:1.72;margin:5px 0}

/* 正文（原型复刻）：章节 / 段落 / 角标 / 句后溯源卡 */
.doc-paper{background:#fff;border-radius:14px;box-shadow:var(--shadow-1);padding:26px 34px 22px;margin:0 0 16px}
.body-external-note{font-size:12px;line-height:1.65;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 11px;margin:0 0 16px}
.chapter{margin:40px 0 0}
.chapter:first-child{margin-top:6px}
.ch-head{display:flex;align-items:center;gap:14px;margin-bottom:18px;scroll-margin-top:86px}
.ch-head h2{font-size:19.5px;font-weight:700;color:var(--ink);letter-spacing:.2px;line-height:1.4;flex:1;min-width:0}
.ch-head::after{content:"";flex-basis:110px;height:1px;background:linear-gradient(90deg,#e9dff9,transparent);order:3;flex-grow:0;flex-shrink:0}
.ch-head .sec-badge{order:4;flex:none;font-size:11.5px;color:var(--ok);background:var(--policy-soft);border-radius:6px;padding:2px 9px;font-weight:700}
.ch-head .sec-badge.bad{color:var(--danger);background:#fdecec}
.ch-head .sec-badge.warn{color:var(--warn);background:#fff6e5}
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
.cite a{color:inherit;text-decoration:none;border-bottom:0}
.cite.flash{background:var(--brand);color:#fff}
.cite.unresolved{color:var(--danger);background:#fdf7f7;border-color:#f6c9cb}

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
.jb-unofficial{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;color:#9a3412;background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:0 7px;margin-right:6px;white-space:nowrap}
.sc-unofficial{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;color:#9a3412;background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:0 7px;white-space:nowrap}
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

/* ===== 知识专库视图 ===== */
#view-library{padding:26px 0 30px}
.lib-head{max-width:860px;margin:0 auto 16px;text-align:center}
.lib-title{margin-bottom:14px}
.lib-title b{font-size:16px;color:var(--navy);letter-spacing:.5px;line-height:1.5}
.lib-searchWrap{position:relative;max-width:620px;margin:0 auto}
.lib-searchIcon{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#a6adbd;font-size:16px;font-weight:700}
.lib-search{width:100%;padding:11px 16px 11px 38px;border:1.5px solid var(--line-strong);border-radius:999px;
  font-size:14px;background:#fff;box-shadow:var(--shadow-1);outline:none}
.lib-search:focus{border-color:var(--brand-2);box-shadow:0 0 0 3px rgba(139,92,246,.18)}
.lib-tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:14px}
.lib-tabs button{border:1px solid var(--line);border-radius:999px;background:#fff;color:var(--muted);
  padding:4px 13px;font-size:12.3px;cursor:pointer}
.lib-tabs button.on{background:var(--grad);border-color:var(--brand);color:#fff;font-weight:700}
.lib-list{max-width:860px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
.lib-empty{max-width:860px;margin:30px auto;text-align:center;color:var(--muted);font-size:13.5px}
.lib-empty.hide{display:none}
.lib-unused.hide{display:none}
.lib-foot{text-align:center;color:var(--muted);font-size:11.5px;padding:18px 0 0;line-height:1.8}
.lib-unused{max-width:860px;margin:20px auto 0;border-top:1px dashed var(--line);padding-top:12px}
.lib-unused summary{cursor:pointer;color:var(--muted);font-size:12.5px;padding:6px 0;list-style:none}
.lib-unused summary::-webkit-details-marker{display:none}
.lib-unused summary::before{content:"▸";display:inline-block;margin-right:6px;transition:transform .15s}
.lib-unused[open] summary::before{transform:rotate(90deg)}
.lib-unused .lib-list{margin-top:10px}
.lib-unused .scard{opacity:.92}

/* ===== 材料卡 ===== */
.scard{min-width:0;border:1px solid #e5e9f0;border-left:3px solid #cbd5e1;border-radius:14px;padding:18px 20px;
  background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.04);transition:box-shadow .25s,border-color .25s}
.scard:hover{box-shadow:0 8px 24px rgba(15,23,42,.08);border-color:#d5dce6}
.scard.pol{border-left-color:var(--brand-2)}
.scard.dat{border-left-color:#0f766e}
.scard.cas{border-left-color:#d97706}
.scard.ref,.scard.mat{border-left-color:#94a3b8}
.scard.hl{box-shadow:0 0 0 3px rgba(59,130,246,.18),0 8px 24px rgba(15,23,42,.08)}
.scard.hide{display:none}
.sc-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.sc-id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700;font-size:11px;color:#fff;background:var(--grad);
  border-radius:6px;padding:2px 8px}
.sc-official{display:inline-flex;align-items:center;font-size:10.5px;font-weight:700;color:#0b4f6c;background:#e6f4fb;border:1px solid #a9d8ea;border-radius:6px;padding:0 7px;white-space:nowrap}
.sc-vk{margin-left:auto;font-size:11px;font-weight:700;color:#15803d}
.sc-vk.warn{color:#b45309}
.sc-unused{font-size:10.5px;font-weight:700;color:#64748b;background:#f1f5f9;border-radius:5px;
  padding:2px 7px;flex:none}
.sc-conf{font-size:10.5px;font-weight:600;color:#92400e;background:#fffbeb;border:1px solid #fde68a;
  border-radius:5px;padding:1px 7px;flex:none}
.scard h4{margin:0 0 6px;font-size:15px;font-weight:650;color:#0f172a;line-height:1.55}
.sc-meta{font-size:12px;color:#64748b;line-height:1.7}
/* 标题链面包屑（模型生成的结构化位置，核验核心抓手）与多段分块 */
.crumb{font-size:11.5px;color:#475569;margin:12px 0 4px;font-weight:500;line-height:1.6;
  padding:3px 9px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;display:inline-block;max-width:100%;
  overflow-wrap:break-word}
.crumb i{font-style:normal;color:#94a3b8;margin:0 2px;font-weight:400}
.seg-block{margin:0 0 10px;padding:12px 14px;background:#f8fafc;border-left:3px solid #dbe3ec;border-radius:0 9px 9px 0}
.seg-block:last-child{margin-bottom:0}
.seg-block .crumb{display:block;margin:0 0 8px;padding:0;background:none;border:0;border-radius:0;
  font-size:12px;font-weight:600;color:#475569;line-height:1.6}
.seg-block .sc-excerpt{margin:0;padding:0;border:0;border-radius:0;background:none;
  font-size:13px;line-height:1.9;color:#334155}
.seg-empty{margin-top:8px;padding:11px 13px;border:1px dashed #e2e8f0;border-radius:8px;
  color:#94a3b8;font-size:12px;background:#fcfcfd}
.sc-vnote{margin-top:5px;font-size:11.3px;color:var(--ok);line-height:1.6}
.sc-excerpt{margin:6px 0 0;padding:12px 14px;border:1px solid #e6eaf0;border-left:3px solid #cbd5e1;border-radius:8px;
  background:#fbfcfd;color:#334155;font-size:12.8px;line-height:1.9}
.sc-excerpt.rich{overflow-x:auto}
.sc-excerpt.rich table{width:max-content;min-width:100%;border-collapse:collapse;background:#fff;font-size:12px}
.sc-excerpt.rich td,.sc-excerpt.rich th{min-width:92px;max-width:220px;padding:7px 8px;border:1px solid var(--line);
  vertical-align:top;word-break:break-word}
.sc-excerpt.rich thead td,.sc-excerpt.rich th{background:#f3f4f6;color:#3f3d52;font-weight:700}
.scard .sc-links a{font-size:12px}
.scard .sc-links{margin-top:4px}
.no-link{font-size:11.5px;color:var(--muted)}
.sc-links a.snap{background:#faf5ff;border-color:#d9c9f4;color:#5b21b6}

/* ===== 章节目录（spy，长报告） ===== */
.toc{position:fixed;left:calc((100vw - 1080px)/2 - 168px);top:120px;width:140px;max-height:60vh;overflow:auto;
  display:flex;flex-direction:column;gap:2px;font-size:12px}
.toc a{color:var(--muted);text-decoration:none;padding:4px 10px;border-left:2px solid var(--line);
  line-height:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.toc a.on{color:var(--brand);border-left-color:var(--brand);font-weight:700}
/* 知识专库视图下隐藏章节目录（2026-09-29 起）：.toc 渲染在 .app 之外，
   视图切换只由 .app[data-view] 驱动，此前无任何规则处理 .toc，专库视图下目录仍挂在左侧 */
.app[data-view="library"] ~ .toc,.app[data-view="library"] .toc{display:none}
@media (max-width:1460px){.toc{display:none}}

.foot{text-align:center;color:var(--muted);font-size:11.5px;padding:16px 0 4px;line-height:1.8}


/* ===== 打印附录 ===== */
.print-appendix{display:none}

/* ===== 引用依据弹层 ===== */
.cite-mask{display:none;position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:120;opacity:0;pointer-events:none;transition:opacity .18s}
.cite-mask.show{display:block;opacity:1;pointer-events:auto}
.cite-modal{display:none;position:fixed;z-index:121;left:50%;top:50%;transform:translate(-50%,-48%);width:min(760px,calc(100vw - 32px));max-height:82vh;overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 80px rgba(15,23,42,.25)}
.cite-modal.show{display:block}
.cite-modal-head{position:sticky;top:0;z-index:1;display:flex;align-items:center;justify-content:space-between;padding:14px 18px;background:#fff;border-bottom:1px solid #e5e9f0}
.cite-modal-head b{font-size:14px;color:#0f172a}
.cite-modal-close{border:1px solid #e2e8f0;background:#f8fafc;border-radius:8px;padding:4px 10px;font-size:12px;color:#475569;cursor:pointer}
.cite-modal-body{padding:16px 18px 20px}
.cite-modal .scard{border:0;box-shadow:none;padding:0}
.cite-modal .scard:hover{box-shadow:none}
@media (max-width:680px){
  .cite-modal{top:auto;bottom:0;left:0;transform:none;width:100%;max-height:86vh;border-radius:16px 16px 0 0}
}

/* ===== 移动端 ===== */
.sheet-mask{display:none}
.sheet{display:none}
@media (max-width:680px){
  body{font-size:14px;line-height:1.8}
  .banner{padding:6px 10px 7px}
  .banner-bar{flex-wrap:wrap;justify-content:center;gap:7px}
  .banner-bar .tb-title{display:none}
  .banner-bar .view-switch{margin:0}
  .banner-bar .view-switch button{padding:5px 11px;font-size:12px}
  .tb-tools button{font-size:11.5px;padding:4px 8px}
  .ch-head{gap:8px;margin-bottom:14px;flex-wrap:nowrap}
  .ch-head h2{font-size:17px;line-height:1.45}
  .ch-head::after{display:none}
  .ch-head .sec-badge{font-size:10.5px;padding:2px 7px;white-space:nowrap}
  .jb-name{max-width:calc(100vw - 72px)}
  .banner .meta{font-size:11px;line-height:1.6}
  .banner .orig-q{font-size:12.5px}
  .process{padding:12px 12px 11px}
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
  .lib-list{grid-template-columns:minmax(0,1fr);gap:10px}
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
  .banner-bar,.process .p-detail,.lib-head,.toc,.sheet,.sheet-mask,
  .cite-mask,.cite-modal,.progress{display:none!important}
  .banner{position:static;background:none;border:0;padding:0 0 6px}
  .banner .orig-q{text-align:left;font-size:13px}
  .banner .meta{color:var(--muted);text-align:left}
  /* 完整归档：三页顺序打印（正文 → 溯源核验报告 → 知识专库）+ 来源附录；
     仅正文模式（body.print-body-only）只保留 #view-body */
  #view-body,#view-report,#view-library{display:block!important}
  .app[data-view] #view-body,.app[data-view] #view-report,.app[data-view] #view-library{display:block!important}
  body.print-body-only #view-report,body.print-body-only #view-library,body.print-body-only .print-appendix,
  body.print-body-only .jb,body.print-body-only .foot{display:none!important}
  #view-body .doc-paper,#view-report .doc-paper{break-after:page}

  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .process{box-shadow:none;margin:6px 0 12px}
  .verify{border-color:#bbb;box-shadow:none;break-inside:avoid}
  .doc-paper{box-shadow:none;border-radius:0;padding:0}
  body{background:#fff;font-size:12.5px}
  .sc-excerpt{display:block;-webkit-line-clamp:unset;cursor:auto}
  .sc-excerpt.rich table,.print-appendix .sc-excerpt.rich table{width:100%!important;min-width:0}
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

  /* ===== 1. 三页切换（正文 / 溯源核验报告 / 知识专库；保存/恢复各自滚动位置） ===== */
  var savedScroll = { body: 0, report: 0, library: 0 };
  var viewChangeHook = null; /* 切页后重算目录锚点等 */
  function setView(view) {
    if (!app || app.getAttribute("data-view") === view) return;
    savedScroll[app.getAttribute("data-view") || "report"] = window.scrollY;
    app.setAttribute("data-view", view);
    $$(".view-switch button").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-view") === view);
    });
    window.scrollTo(0, Math.max(0, savedScroll[view] || 0));
    if (viewChangeHook) viewChangeHook(view);
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

  /* ===== 3. 复制全文（从正文页取：章节标题 + 段落 + 表格，干净无角标） ===== */
  var copyBtn = $("#btn-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var parts = [];
      /* 按文档流顺序收集章节标题/段落/表格；克隆后剔除引文胶囊与角标，
         只复制正文本身（胶囊标题/展开摘录/编号数字均不带出） */
      var nodes = $$("#view-body .ch-head h2, #view-body .lead, #view-body .para, #view-body .tbl-wrap");
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

  /* ===== 5. 导出：正文 Markdown / PDF（浏览器打印另存为 PDF） ===== */
  var exportBtn = $("#btn-export");
  var exportDrop = $("#export-drop");
  function docTitleForFile() {
    var t = $(".tb-title");
    var name = (t ? t.textContent.trim() : "") || document.title || "文稿";
    return name.replace(/[\\/:*?"<>|]+/g, "_").trim() || "文稿";
  }
  function exportMarkdown() {
    var el = document.getElementById("doc-export");
    var data = { title: docTitleForFile(), markdown: "" };
    if (el) { try { data = JSON.parse(el.textContent) || data; } catch (err) {} }
    var blob = new Blob([data.markdown || ""], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = (data.title || docTitleForFile()) + ".md";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(url); if (a.parentNode) a.parentNode.removeChild(a); }, 800);
  }
  function printBy(mode) {
    if (mode === "body") document.body.classList.add("print-body-only");
    if (exportDrop) exportDrop.hidden = true;
    window.print();
  }
  if (exportBtn && exportDrop) {
    exportBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      exportDrop.hidden = !exportDrop.hidden;
    });
    exportDrop.addEventListener("click", function (e) {
      e.stopPropagation();
      var t = e.target.closest("button");
      if (!t) return;
      if (t.id === "export-md") { exportMarkdown(); exportDrop.hidden = true; return; }
      printBy(t.id === "export-pdf-body" ? "body" : "full");
    });
    document.addEventListener("click", function () { exportDrop.hidden = true; });
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

  /* 行内引用：弹出该来源的引用卡（只含被引用的原文段），不再跳专库。 */
  var citeModal = $(".cite-modal");
  var citeMask = $(".cite-mask");
  function openCite(id) {
    var card = byId[id];
    if (!citeModal || !card) {
      if (card) { setView("library"); card.scrollIntoView({behavior: "smooth", block: "center"}); }
      return;
    }
    var body = citeModal.querySelector(".cite-modal-body");
    body.innerHTML = "";
    var clone = card.cloneNode(true);
    clone.removeAttribute("id");
    clone.classList.remove("hide");
    body.appendChild(clone);
    citeModal.classList.add("show");
    citeMask.classList.add("show");
    document.body.style.overflow = "hidden";
    citeModal.scrollTop = 0;
  }
  function closeCite() {
    if (!citeModal) return;
    citeModal.classList.remove("show");
    citeMask.classList.remove("show");
    document.body.style.overflow = "";
  }
  if (citeMask) citeMask.addEventListener("click", closeCite);
  if (citeModal) {
    var citeClose = citeModal.querySelector(".cite-modal-close");
    if (citeClose) citeClose.addEventListener("click", closeCite);
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeCite();
  });

  /* 行内引文 jb（历史形态，保留兼容）：点小胶囊 toggle 展开卡；点角标展开对应 jb 并 flash。
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

  /* 引文条目点击 → 知识专库定位对应卡：库内导航看完整材料；
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
    /* 整个角标（含内边距）都可点；真正未绑定的角标才留痕。 */
    var link = btn.querySelector("a.cite-link");
    btn.addEventListener("click", function (e) {
      if (link) {
        e.preventDefault();
        openCite(link.getAttribute("data-cite"));
        return;
      }
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

  /* ===== 7. 知识专库：tabs + 搜索 + 热词 ===== */
  var cond = "";
  var kw = "";
  /* 筛选必须同时覆盖主列表与"未进入正文"折叠区（1.0.1 修复：此前只过滤主列表，
     选中分组后折叠区仍展示其他组的材料，标签数与可见结果对不上）。 */
  var filterCards = $$("#lib-list .scard, .lib-unused .scard");
  var unusedBox = $(".lib-unused");
  var luTitle = unusedBox ? unusedBox.querySelector(".lu-title") : null;
  function applyFilter() {
    var visible = 0;
    var unusedVisible = 0;
    filterCards.forEach(function (c) {
      var okCond = !cond;
      if (cond === "__unused__") okCond = c.getAttribute("data-unused") === "1";
      else if (cond) okCond = c.getAttribute("data-search") === cond;
      var okKw = !kw || (c.textContent || "").toLowerCase().indexOf(kw) !== -1;
      var show = okCond && okKw;
      c.classList.toggle("hide", !show);
      if (show) {
        visible++;
        if (c.getAttribute("data-unused") === "1") unusedVisible++;
      }
    });
    if (unusedBox && luTitle) {
      var total = unusedBox.getAttribute("data-total") || "0";
      if (cond) {
        luTitle.textContent = "本组未进入正文的参考材料（" + unusedVisible + "）";
      } else if (kw) {
        luTitle.textContent = "未进入正文的参考材料（" + unusedVisible + "）";
      } else {
        luTitle.textContent = "未进入正文的参考材料（" + total + "）";
      }
      unusedBox.classList.toggle("hide", unusedVisible === 0);
      if (cond && unusedVisible > 0) unusedBox.open = true;
    }
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
    /* 正文页锚 sec-N / 报告页锚 rsec-N：href 只是兜底，实际按当前视图前缀定位 */
    function tocPrefix() {
      var v = app ? app.getAttribute("data-view") : "";
      return v === "report" ? "rsec" : (v === "body" ? "sec" : "");
    }
    function tocSecs() {
      var pfx = tocPrefix();
      if (!pfx) return [];
      return links.map(function (a) { return document.getElementById(pfx + "-" + a.getAttribute("data-sec")); });
    }
    var secs = tocSecs();
    links.forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault();
        var pfx = tocPrefix();
        var target = pfx ? document.getElementById(pfx + "-" + a.getAttribute("data-sec")) : null;
        if (!target) return;
        /* 手动定位而非 scrollIntoView({block:"start"})：后者把标题顶到视口 y=0，
           会被 sticky 顶栏盖住。偏移量与目录吸顶位置同一基准（顶栏高 + 20px）。 */
        var bar = document.querySelector(".banner");
        var offset = (bar ? bar.offsetHeight : 0) + 20;
        var y = target.getBoundingClientRect().top + window.scrollY - offset;
        window.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
      });
    });
    function spy() {
      var pos = window.scrollY + 130;
      var current = -1;
      secs.forEach(function (s, i) { if (s && s.offsetTop <= pos) current = i; });
      links.forEach(function (a, i) { a.classList.toggle("on", i === current); });
    }
    window.addEventListener("scroll", spy, { passive: true });

    /* 目录纵向定位（2026-09-29 起）：此前 CSS 写死 top:120px，目录顶部与页头
       齐平、离正文很远。改为——直接跟随正文首节，只保留"不低于顶栏下方"的下限；首屏看不到
       目录属正常，向下滚动后自然吸附在顶栏下方。目录过长由 CSS max-height:60vh+overflow:auto
       内部滚动兜底。 */
    var bannerEl = document.querySelector(".banner");
    function placeToc() {
      var first = secs[0];
      if (!first) return;
      var stick = (bannerEl ? bannerEl.offsetHeight : 0) + 20;
      var want = Math.round(first.getBoundingClientRect().top);
      toc.style.top = Math.max(stick, want) + "px";
    }
    window.addEventListener("scroll", placeToc, { passive: true });
    window.addEventListener("resize", placeToc);
    /* 切页时重算锚点集合与高亮（正文页 sec-N / 报告页 rsec-N；专库页隐藏目录） */
    viewChangeHook = function () { secs = tocSecs(); spy(); placeToc(); };
    placeToc();
    spy();
  }
})();
"""


def render_html(payload: Dict[str, Any], title: str, answer_override: str = "", question_override: str = "",
                generated_at: Optional[datetime] = None,
                snapshot_enabled: bool = True,
                research_notes: Optional[Dict[str, int]] = None,
                charts_data: Optional[Dict[str, Any]] = None,
                stage_label: str = "") -> str:
    # search_meta.calls（每路调用增量）在 unwrap 前捕获——unwrap 会把 content 外层剥掉（1.6.0）
    _calls_meta = payload.get("search_meta") if isinstance(payload.get("search_meta"), dict) else {}
    payload = unwrap(payload)
    answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(payload)
    # 无 markdown 标题的答案：首个非空行若为短标题形态（≤60 字、非列表/表格/标题语法、
    # 不以句读结尾），升格为 `# 标题` 行——文头标题、章节卡、TOC、图表锚点全链路随 heading
    # 自然工作，标题行不再在正文重复渲染（2026-10-14 修复：实测纯文本首行答案的报告页
    # 文头显示"溯源核验报告：溯源核验报告"、图表锚点随之失配）
    if not re.search(r"(?m)^#{1,4}\s", answer):
        _first = next((ln.strip() for ln in answer.splitlines() if ln.strip()), "")
        if (_first and len(_first) <= 60 and not re.match(r"^[-*>|#\d|\|]", _first)
                and not _first.endswith(("。", "；", "！", "？", "!", "?", ".", ";"))):
            _rest = answer[answer.index(_first) + len(_first):].lstrip("\n")
            answer = f"# {_first}\n{_rest}"
    sources = align_sources_to_answer(answer, extract_sources(payload, snapshot_enabled=snapshot_enabled))
    # 角标按首次出现顺序重排为 1..N（含材料卡同步重编号与未引用分组），WorkBuddy 实测反馈要求
    answer, sources = renumber_citations(answer, sources)
    # 1.0.2：内容判断全部归 AI——渲染器不做任何"某句是否被原文支持"的判断，
    # 只保证结构（角标绑定、摘录可比对、不可引用材料不作依据、自检有据）。
    used = citation_ids(answer)
    generated_at = generated_at or datetime.now()
    generated = generated_at.strftime("%Y-%m-%d %H:%M")

    verification = compute_verification(answer, sources, payload, generated_at)
    # 1.0.2 两轨验收：不合格不进交付——结构不合格或 AI 验收未通过时直接退出，不生成 HTML。
    # 交付物只有"合格"这一种形态；发现问题就修复后重跑，而不是把问题交给用户。
    if not verification["overall"]["passed"]:
        _reasons = verification["overall"].get("reasons") or []
        print("错误：核验未通过，未生成报告。请先修正后重跑（不会产出不合格的 HTML）。",
              file=sys.stderr)
        for _r in _reasons:
            print(f"  - {_r}", file=sys.stderr)
        raise SystemExit(1)
    process_stats = compute_process_stats(sources, answer, calls=_calls_meta.get('calls'))
    if research_notes:
        process_stats["research_notes"] = research_notes
    citation_warning = ""
    if sources and not used:
        citation_warning = (
            '<div class="warn-box"><b>生成检查未通过：正文没有来源角标。</b>'
            '本报告无法建立"结论-素材"核验对应，仅作素材清单参考。'
            '请修正最终答案（--answer-file）：在关键结论后标注 [1]、[2] 等角标并逐条对应来源文章，'
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
    stage_suffix = f"（{stage_label}）" if stage_label else ""
    report_title = f"{brand_text('report_title_prefix')}：{display_title}{stage_suffix}"
    # 正文页：同一份正文去掉全部角标/引文胶囊，输出干净正式内容（核验内容归"溯源核验报告"页）
    clean_blocks, _ = parse_answer_blocks(answer, {s["id"] for s in sources}, chip_map, strip_cites=True)
    _, clean_sections = group_sections(clean_blocks)
    # 原问题行（2026-10-08 起）：只显示 --question 显式传入的原始问题，
    # 不用文档标题冒充（标题是答案的成稿名，不是用户原话）；为空或与标题相同时不显示
    question_text = (question_override or "").strip()
    hero_question = (
        f'<div class="orig-q" title="{esc(question_text)}"><b>原问题</b>：{esc(question_text)}</div>'
        if question_text and question_text != display_title else ""
    )

    # 注入 JSON 转义（1.6.0，对齐公文写作 3.9.0）：< > & 全量转 \uXXXX 转义——既防
    # </script> 提前闭合，也防 <!-- / <script 序列触发怪异解析；JSON.parse 原生可逆。
    def _json_for_html(obj: Any) -> str:
        return (json.dumps(obj, ensure_ascii=False)
                .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))

    jb_tables_json = _json_for_html(jb_tables)
    jb_tables_script = (f'<script type="application/json" id="jb-tables">{jb_tables_json}</script>\n'
                        if jb_tables else "")
    # 导出用正文 Markdown（去角标，干净正文），供顶部"导出 ▾ → 导出 Markdown（正文）"下载
    export_payload = {"title": display_title, "markdown": strip_citation_markers(answer)}
    export_json = _json_for_html(export_payload)
    export_script = f'<script type="application/json" id="doc-export">{export_json}</script>\n' 

    meta_bits = []
    if process_stats["n_searches"]:
        # 检索计数按通道拆分显示（检索来源/公开网络/宿主 WebSearch 是不同来源）
        _deep_n = process_stats.get("deep_routes", 0)
        _trusted_n = process_stats.get("trusted_routes", 0)
        meta_bits.append(route_summary(_deep_n, _trusted_n, process_stats["n_searches"]))
    if sources:
        meta_bits.append(f"知识专库文章 {len(sources)} 篇")
    if process_stats["n_cite_marks"]:
        meta_bits.append(f"正文实际引用 {process_stats['n_cite_marks']} 处")
    meta_bits.append(f"生成于 {generated}")
    meta_line = " · ".join(meta_bits)
    # 来源＝材料实际使用的检索通道（深度/可信/宿主 WebSearch，动态汇总）；
    # 历史产物无通道信息时保留旧文案；孤立「联网」并回「溯源核验报告生成器（联网）」
    _channels = channel_tokens([s.get("channel") or "" for s in sources])
    has_external_any = any(s.get("unofficial") or s.get("pending") for s in sources)
    source_line = (" · ".join(_channels) if _channels
                   else (brand_text("source_fallback_external") if has_external_any
                         else brand_text("source_fallback")))

    # 正文页的来源性质提示：引用了公开网络材料时，给用户一个可见、统一的标记，
    # 不暴露三阶段/检索通道；具体逐条标记仍在溯源核验报告的材料卡与引文胶囊上。
    # 1.0.2 来源等级：官方外部信源（政府/法定机构域名或机构名）单独提示，不与"非官方"混同。
    cited_third_party = any((s.get("unofficial") or s.get("pending")) and s.get("used", True)
                            for s in sources)
    cited_official_ext = any(s.get("official_external") and s.get("used", True) for s in sources)
    if cited_third_party:
        body_external_note = (
            '<div class="body-external-note">说明：本页部分材料来自公开网络第三方信源，'
            '已在溯源核验报告中标注「非官方来源」，请以官方口径复核。</div>')
    elif cited_official_ext:
        body_external_note = (
            '<div class="body-external-note">说明：本页部分材料来自公开网络的官方信源'
            '（政府机构/法定机构），已在溯源核验报告中标注，请以原文为准。</div>')
    else:
        body_external_note = ""

    # 图表并入核验报告（1.0.1 opt-in）：传 --charts-json 才画，交付物始终是**一个** HTML。
    # 位置按 metadata.section 锚点插进对应章节；锚点缺失或不匹配才退化为独立"数据可视化"章节。
    # 资源缺失或数据不可用则整块不渲染（不出现空白图，也不阻断报告生成）。
    charts_html = ""
    charts_script = ""
    chart_toc = ""
    charts_by_section: Dict[int, str] = {}
    if charts_data and (CONFIG.get("charts") or {}).get("enable", True):
        echarts_src = chart_embed.load_echarts_source()
        if not echarts_src:
            print(f"提示：未找到 {chart_embed.ECHARTS_RESOURCE}，本次不生成图表章节（报告其余部分不受影响）。",
                  file=sys.stderr)
        charts = chart_embed.build_charts(charts_data) if echarts_src else []
        if echarts_src and not charts:
            print("提示：图表数据不足以成图（需 ≥2 个数据点/系列），本次不生成图表章节。", file=sys.stderr)
        if charts:
            chart_meta = charts_data.get("metadata") or {}
            chart_title = str(chart_meta.get("title") or "").strip() or "数据可视化"
            note = '<p class="chart-note">图表由已核验材料数据生成，点击图例或数据项可跳转对应来源原文。</p>'
            blocks = chart_embed.render_blocks(charts)
            anchor_idx = resolve_chart_anchor(sections, chart_meta.get("section"))
            if anchor_idx:
                charts_by_section[anchor_idx] = (
                    f'<div class="chart-inline" aria-label="数据可视化">'
                    f'<h3 class="chart-h3">{esc(chart_title)}</h3>{note}{blocks}</div>'
                )
            else:
                charts_html = (
                    f'<section class="chart-section" id="chart-block" aria-label="数据可视化">'
                    f'<h2 class="chart-h2">{esc(chart_title)}</h2>{note}{blocks}</section>'
                )
                chart_toc = f'<a href="#chart-block">{esc(short(chart_title, 16))}</a>'
                if chart_meta.get("section"):
                    print(f"提示：图表锚点「{chart_meta.get('section')}」在正文里找不到对应章节，"
                          f"已改为独立章节呈现。", file=sys.stderr)
            charts_script = chart_embed.render_script(charts, echarts_src)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(display_title)}</title>
<style>{PAGE_CSS}</style>
</head>
<body>

<header class="banner">
  <div class="banner-bar">
    <span class="tb-title">{esc(display_title)}</span>
    <div class="view-switch" role="tablist" aria-label="页面切换">
      <button data-view="body" type="button">正文（去索引）</button>
      <button class="on" data-view="report" type="button">溯源核验报告</button>
      <button data-view="library" type="button">知识专库（{len(sources)}）</button>
    </div>
    <div class="tb-tools">
      <button id="btn-copy" type="button" title="复制正文纯文本">复制全文</button>
      <span class="print-menu">
        <button id="btn-export" type="button" aria-haspopup="true" title="导出正文 Markdown 或 PDF">导出 ▾</button>
        <span class="print-drop" id="export-drop" hidden>
          <button id="export-md" type="button">导出 Markdown（正文）</button>
          <button id="export-pdf-body" type="button">导出 PDF（正文）</button>
          <button id="export-pdf-full" type="button">导出 PDF（溯源核验报告）</button>
        </span>
      </span>
    </div>
  </div>
  {hero_question}
  <div class="meta">{esc(meta_line)} ｜ 来源：{esc(source_line)}</div>
  <div class="progress" aria-hidden="true"><i></i></div>
</header>

<div class="app container" data-view="report">

  <main class="view" id="view-body" aria-label="正文">
    <h2 class="paper-title">{esc(display_title)}</h2>
    <div class="doc-paper">
    {body_external_note}
    {render_section_cards(clean_sections, sources, id_prefix="sec")}
    </div>
    <div class="foot">{esc(brand_text("footer_body"))}</div>
  </main>

  <main class="view" id="view-report" aria-label="溯源核验报告">
    <h2 class="paper-title">{esc(report_title)}</h2>
    {citation_warning}
    {render_process_bar(process_stats, verification)}
    {render_verify_panel(verification)}
    {charts_html}
    <div class="doc-paper">
    {render_section_cards(sections, sources, charts_by_section, id_prefix="rsec")}
    </div>
    <div class="foot">{esc(brand_text("footer_report"))}</div>
  </main>

  {render_library_view(sources, display_title)}
  {render_print_appendix(sources)}
</div>

{render_toc(sections, chart_toc)}

<div class="ev-panel" id="ev-pop" hidden></div>
{export_script}{jb_tables_script}<div class="cite-mask" aria-hidden="true"></div>
<div class="cite-modal" role="dialog" aria-label="引用依据">
  <div class="cite-modal-head"><b>引用依据</b><button class="cite-modal-close" type="button">收起</button></div>
  <div class="cite-modal-body"></div>
</div>
<div class="sheet-mask" aria-hidden="true"></div>
<div class="sheet" role="dialog" aria-label="来源文章">
  <div class="sheet-grab"></div>
  <div class="sheet-head"><b>依据对照</b><button class="sheet-close" type="button">收起</button></div>
  <div class="sheet-body"></div>
</div>

<script>{PAGE_JS}</script>
{charts_script}
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
    """不再按位置给材料重编号。

    修复历史实现缺陷：原实现会在"正文角标与素材 id 完全不相交"时按顺序把素材改号
    迎合角标——正文写 [7] 而只有 1 篇来源文章时，会被洗成"✓ 引用对应 1/1"，与
    "未绑定角标绝不按位置猜测"的核验诚实性原则相反。现如实返回原素材，由核验单报未绑定。
    角标 1..N 的连续重排由 renumber_citations 独立完成（按首现顺序，1.1.5 用户要求）。
    """
    return sources


def parse_research_notes(text: str) -> Dict[str, int]:
    """统计研究资料 Markdown 的两张表行数：核心事实总表 / 数据口径表。
    按二级/三级标题分节识别，表格行以 | 开头（跳过表头与 --- 分隔行）；未识别到相应节时计 0。"""
    facts = 0
    calibers = 0
    current: Optional[str] = None
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            head = stripped.lstrip("#").strip()
            if "事实" in head:
                current = "facts"
            elif "口径" in head or "数据" in head:
                current = "calibers"
            else:
                current = None
            continue
        if not (current and stripped.startswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{2,}:?", c or "") for c in cells):
            continue  # 表头分隔行
        prev = lines[i - 1].strip() if i > 0 else ""
        if prev.startswith("|") and i >= 2 and all(
            re.fullmatch(r":?-{2,}:?", c or "") for c in [x.strip() for x in prev.strip("|").split("|")]
        ):
            continue  # 分隔行的前一行＝表头行，不计数据
        if any(cells):
            if current == "facts":
                facts += 1
            else:
                calibers += 1
    return {"facts": facts, "calibers": calibers}


def resolve_charts_data(value: Optional[str], run_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """解析 --charts-json：支持直接内联 JSON，也支持 run 目录内的文件名。

    非法/为空一律返回 None（图表章节不渲染），绝不因此阻断核验报告生成。
    """
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        if raw.startswith("{"):
            data = json.loads(raw)
        else:
            data = json.loads(_safe_input_path(raw, {".json"}, run_dir).read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"提示：图表数据无法读取（{exc}），本次不生成图表章节。", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def _prescan_config_option(argv: List[str]) -> Optional[str]:
    """在 argparse 前预读 --config，使 argparse 描述也能用上品牌配置。"""
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--config="):
            return arg.split("=", 1)[1]
    return None


def main() -> None:
    apply_config(load_config(_prescan_config_option(sys.argv[1:])))

    parser = argparse.ArgumentParser(description=brand_text("argparse_desc"))
    parser.add_argument("input_json", help="通用 JSON（materials 数组 + answer）。接口/merge 产物请先用 build_report_input.py 转换")
    parser.add_argument("--run", help="本次运行的独立目录（必须在 Skill 安装目录之外；相对产物落在该目录）")
    parser.add_argument("--output", help="输出 HTML 文件名；相对名落在 --run 目录，绝对路径也必须在 Skill 目录之外。内部重跑直接覆盖同名文件（交付版本编号由 deliver_outputs 在用户目录处理）")
    parser.add_argument("--config", help="业务 Skill 配置 JSON（品牌/通道/自检标签/双版/图表/域内核验）；不传用通用默认值")
    parser.add_argument("--title", default=None, help="页面标题；不传用配置的 default_page_title")
    parser.add_argument("--answer-file", help="最终答案文件（关键结论带 [1][2] 角标）。复杂任务综合后必须传入，确保 HTML 展示的答案与交付一致。")
    parser.add_argument("--question", default="", help="用户原始问题，用于自动生成文件名。")
    parser.add_argument("--question-file", help="用户原始问题全文文件（run 目录内文件名或绝对路径）；多行/长问题必须用本参数传全文，禁止只传首行（1.6.0）")
    parser.add_argument("--self-check-file", help="答案自检结果 JSON（五项：fact_basis/binding/consistency/freshness/no_gap，值写 通过/未通过：原因；标签集可由配置替换）；未传时核验单如实显示'未记录'。")
    parser.add_argument("--verify-file", help="业务 Skill 的域内核验记录 JSON（verdict/record/issues）；record 指纹与当前答案/证据不一致或 verdict=fail 时判核验未通过")
    parser.add_argument("--charts-json", help="图表数据 JSON（run 目录内文件名或内联 JSON）；传入后图表并入本报告（一体化，不另出独立 HTML）")
    parser.add_argument("--stage", help="双版报告阶段标识（如 outline/final），显示名由配置 stage.labels 提供；未配置则不出现后缀")
    parser.add_argument("--no-snapshot", action="store_true", help="关闭存档快照兜底展示（默认启用：原文失效时以 /A/ 修订后的存档快照回看）")
    parser.add_argument("--research-notes-file", help="研究资料 Markdown（核心事实总表 + 数据口径表）；传入后 AI 自验收过程条体现整理规模，未传不显示该统计。")
    args = parser.parse_args()
    if args.config:
        apply_config(load_config(args.config))

    try:
        run_dir = resolve_run_dir(args.run) if args.run else None
    except RunPathError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None

    input_path = _safe_input_path(args.input_json, {".json"}, run_dir)
    payload = load_json(input_path)
    answer_override = ""
    answer_path = None
    if args.answer_file:
        answer_path = _safe_input_path(args.answer_file, {".txt", ".md"}, run_dir)
        answer_override = answer_path.read_text(encoding="utf-8")

    # 答案自检结果注入（写入 unwrap 后的根级，供 compute_verification 读取）
    if args.self_check_file:
        check_path = _safe_input_path(args.self_check_file, {".json"}, run_dir)
        check_data = json.loads(check_path.read_text(encoding="utf-8"))
        if isinstance(check_data, dict):
            unwrap(payload)["selfCheck"] = check_data
        # 文件时间兜底：答案或依据在自检之后被改过，旧自检不得继续沿用。
        try:
            if answer_path is not None and answer_path.stat().st_mtime > check_path.stat().st_mtime + 1:
                unwrap(payload)["answer_stale"] = True
            if input_path.stat().st_mtime > check_path.stat().st_mtime + 1:
                unwrap(payload)["evidence_stale"] = True
        except OSError:
            pass

    # 域内核验记录注入（--verify-file）：由业务 Skill 的核验器产出，渲染时并入核验单
    if args.verify_file:
        verify_path = _safe_input_path(args.verify_file, {".json"}, run_dir)
        verify_data = json.loads(verify_path.read_text(encoding="utf-8"))
        if isinstance(verify_data, dict):
            unwrap(payload)["verifyRecord"] = verify_data

    snapshot_enabled = not args.no_snapshot
    unwrapped = unwrap(payload)
    # 严格单输入：找不到通用材料时直接拒绝，提示改用统一入口转换（不静默产出空报告）
    if not load_materials(unwrapped) and not load_materials(payload):
        print("错误：输入不是通用 JSON（未找到 materials / 材料 / sources 数组）。\n"
              "接口检索或 merge 产物请先用 build_report_input.py --adapter merged 转换为通用 JSON。",
              file=sys.stderr)
        raise SystemExit(2)
    final_answer = normalize_citations(answer_override) if answer_override.strip() else extract_answer(unwrapped)

    # 生成前硬校验：核验报告必须以可交付状态产出——无角标或角标未绑定材料均拒绝生成
    preview_sources = extract_sources(unwrapped, snapshot_enabled=snapshot_enabled)
    preview_cited = citation_ids(final_answer)
    if preview_sources and not preview_cited:
        print(
            "错误：生成检查未通过——已召回 "
            f"{len(preview_sources)} 篇来源文章，但答案中没有 [1]、[2] 等来源角标，无法建立\"结论-来源文章\"核验对应。\n"
            "请修正最终答案（--answer-file）：在关键结论后标注角标并逐条对应来源文章，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    preview_ids = {s["id"] for s in preview_sources}
    unbound_preview = [cid for cid in preview_cited if cid not in preview_ids]
    if unbound_preview:
        shown = "、".join(f"[{c}]" for c in unbound_preview[:8])
        print(
            f"错误：生成检查未通过——答案角标 {shown} 未绑定到任何来源文章"
            f"（共召回 {len(preview_sources)} 条，可绑定编号 {min(preview_ids) if preview_ids else '-'}~{max(preview_ids) if preview_ids else '-'}）。\n"
            "请修正最终答案：角标必须逐条对应实际引用的来源文章，然后重新运行本脚本。",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.question_file:
        _qf = _safe_input_path(args.question_file, {".txt", ".md"}, run_dir)
        args.question = _qf.read_text(encoding="utf-8").strip()
    question = args.question.strip() or extract_question(unwrapped)
    generated_at = datetime.now()
    try:
        if args.output:
            output = _safe_output_path(args.output, {".html", ".htm"}, ".html", run_dir)
        else:
            # 产物名应由 Agent 通过 --output 指定（简短、取自答案标题、无 _v2/时间戳）；
            # 未指定时才回退问题截断式自动命名（仅兜底，不推荐）。
            print("提示：未指定 --output，使用自动文件名。建议由 Agent 按答案标题命名"
                  "（如「成都重庆西安养老金对比.html」，重跑仍传同名以覆盖）。", file=sys.stderr)
            output = _safe_output_path(safe_output_filename(question, generated_at), {".html", ".htm"}, ".html", run_dir)
    except RunPathError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None

    # 内部重跑直接覆盖 $RUN 内同名报告（被否掉的草稿不占版本号）；
    # 版本编号只在**交付给用户**时由 deliver_outputs 按"目标目录已有同名且内容不同"决定。
    output.parent.mkdir(parents=True, exist_ok=True)
    research_notes = None
    if args.research_notes_file:
        _rn_path = _safe_input_path(args.research_notes_file, {".md", ".txt"}, run_dir)
        research_notes = parse_research_notes(_rn_path.read_text(encoding="utf-8"))
        print(f"研究资料统计：{research_notes['facts']} 项事实 · {research_notes['calibers']} 项口径")
    title_text = (args.title or brand_text("default_page_title")).strip() or "溯源核验报告"
    stage_label = ""
    stage_cfg = CONFIG.get("stage") or {}
    if args.stage and stage_cfg.get("enable"):
        stage_label = str((stage_cfg.get("labels") or {}).get(args.stage) or "")
    charts_data = resolve_charts_data(args.charts_json, run_dir) if args.charts_json else None
    output.write_text(
        render_html(payload, title_text, answer_override=answer_override, question_override=args.question,
                    generated_at=generated_at,
                    snapshot_enabled=snapshot_enabled,
                    research_notes=research_notes,
                    charts_data=charts_data,
                    stage_label=stage_label),
        encoding="utf-8")
    print(f"已生成：{output}")


if __name__ == "__main__":
    main()
