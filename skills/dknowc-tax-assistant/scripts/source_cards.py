#!/usr/bin/env python3
"""材料画像：把税务检索结果转成带地域、来源性质、文件类型、抓取状态的 source cards。

输入：tax_search.py / merge_search_results.py 的 JSON，或含"检索文章"数组的对象。
输出：tax_source_cards.json

设计目的：让"河北的口径被当成北京的口径""新闻报道被当成政策原文"这类问题
在材料层就暴露，而不是等模型写进答案后再靠人发现。

来源标签语义（2026-11-10 与深知系列产品口径对齐）：
- `source_grade`：官方库 / 政府网站 / 官方媒体 / 次级媒体 / 未知。
  "官方库"＝深知库内材料；外部材料按来源性质取值。
- `source_nature`：政府网站 / 官方媒体 / 次级媒体 / 未知。
  `非官方来源=True` 只表示"不是深知库内材料"，不等于网站本身不官方；
  政府网站、官方媒体要如实区分，无法判断写"未知"，不要合并成"次级媒体/未知"。
- `source_channel`：深知库内 / 外部联网。

用法：
  python3 scripts/source_cards.py \
    --input tax_<任务>_merged.json \
    --profile tax_question_profile.json \
    --output tax_source_cards.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List
from urllib.parse import urlparse

from question_profile import CITY_PROVINCE, PROVINCES, PROVINCE_SHORT
import run_dir

PROVINCE_DOMAIN_PREFIX = {
    "bj": "北京市", "tj": "天津市", "he": "河北省", "sx": "山西省",
    "nm": "内蒙古自治区", "ln": "辽宁省", "jl": "吉林省", "hl": "黑龙江省",
    "sh": "上海市", "js": "江苏省", "zj": "浙江省", "ah": "安徽省",
    "fj": "福建省", "jx": "江西省", "sd": "山东省", "ha": "河南省",
    "hb": "湖北省", "hn": "湖南省", "gd": "广东省", "gx": "广西壮族自治区",
    "hi": "海南省", "cq": "重庆市", "sc": "四川省", "gz": "贵州省",
    "yn": "云南省", "xz": "西藏自治区", "sn": "陕西省", "gs": "甘肃省",
    "qh": "青海省", "nx": "宁夏回族自治区", "xj": "新疆维吾尔自治区",
}

NATIONAL_TERMS = (
    "全国", "中华人民共和国", "国务院", "全国人民代表大会", "全国人大常委会",
    "国家税务总局", "财政部", "海关总署", "人力资源和社会保障部", "国家医保局",
    "国家发展改革委", "工业和信息化部", "住房和城乡建设部", "商务部",
    "国家市场监督管理总局", "中共中央", "最高人民法院", "最高人民检察院",
)

GOV_TERMS = (
    "国务院", "人民政府", "税务局", "税务分局", "财政厅", "财政局", "财政部",
    "人力资源和社会保障局", "人力资源和社会保障厅", "人社局", "医保局",
    "海关", "发展和改革委员会", "工信厅", "工业和信息化厅", "住房和城乡建设厅",
    "市场监督管理局", "国家税务总局",
)

OFFICIAL_MEDIA_TERMS = (
    "中国政府网", "新华社", "新华网", "人民日报", "人民网", "央视", "中央电视台",
    "中国税务报", "中国税务网", "经济日报", "光明日报", "央广网", "中国新闻网",
)

SECONDARY_TERMS = (
    "新闻", "日报", "晚报", "时报", "商报", "财经", "资讯", "网", "搜狐", "新浪",
    "网易", "腾讯", "百家号", "头条", "知乎", "微博", "公众号", "自媒体",
)


def _first(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _articles(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    data = content.get("data") if isinstance(content.get("data"), dict) else content
    if isinstance(data, dict):
        arts = data.get("检索文章")
        if isinstance(arts, list):
            return [x for x in arts if isinstance(x, dict)]
    arts = payload.get("检索文章")
    return [x for x in arts if isinstance(x, dict)] if isinstance(arts, list) else []


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower() if url else ""
    except Exception:  # noqa: BLE001
        return ""


def _has_local_marker(text: str) -> str:
    province = next((p for p in PROVINCES if p in text), "")
    if province:
        return province
    for short in sorted(PROVINCE_SHORT, key=len, reverse=True):
        if short and short in text:
            return PROVINCE_SHORT[short]
    return ""


def _infer_jurisdiction(item: Dict[str, Any]) -> str:
    area = _first(item, "办理地域", "地域", "area")
    # 合并产物常给每篇带一个泛化的"办理地域=中国"，不能据此把地方文件标成全国。
    if area in ("中国", "全国"):
        area = ""
    if area:
        return area

    # 只从标题/机构/数据源判断，不扫描全文：政策全文常提到多个省份，
    # 用全文匹配会把中央文件误标成它正文里提到的某个省。
    title = _first(item, "文章标题", "标题")
    issuer = _first(item, "发布或实施机构", "发布机关")
    source = _first(item, "数据源")
    url = _first(item, "源网址", "url", "原文链接")
    meta = " ".join([title, issuer, source])

    # 地方税务机关的机构名本身带省市（国家税务总局北京市税务局），先认地方。
    issuer_local = _has_local_marker(issuer)
    if issuer_local:
        return issuer_local
    # 发布机关是中央部委/总局（财政部、国家税务总局…）即全国口径：
    # 中央文件被地方门户/镜像站转载时，不能因为数据源在某省就判成地方文件。
    if any(term in issuer for term in NATIONAL_TERMS):
        return "全国"
    title_local = _has_local_marker(title)
    central_title = any(term in title for term in NATIONAL_TERMS)
    # 地方税务局/财政厅的标题带省名（即使含"国家税务总局"前缀）先认地方；
    # 中央机关文件标题提到某省（如"国务院关于河北省……"）仍归全国。
    local_bureau_title = re.search(
        r"(省|市|自治区|区|县)[^ ]{0,8}(税务局|财政厅|财政局|人民政府|人社局)", title
    )
    if title_local and (local_bureau_title or not central_title):
        return title_local
    if central_title:
        return "全国"

    # 数据源本身是地方税务机关/政府网站时补认地方；中央文件被地方门户转载不适用
    # （上面 central_title 已归全国）。
    source_local = _has_local_marker(source)
    if source_local and re.search(r"税务局|财政厅|财政局|人民政府|人社局", source):
        return source_local

    for city in sorted(CITY_PROVINCE, key=len, reverse=True):
        if city in meta or city in url:
            return CITY_PROVINCE[city]
    if any(term in meta for term in NATIONAL_TERMS):
        return "全国"

    host = _host(url)
    labels = host.split(".") if host else []
    label = labels[0] if labels else ""
    if label in ("www", "m") and len(labels) > 1:
        label = labels[1]
    for city in sorted(CITY_PROVINCE, key=len, reverse=True):
        if label and label.startswith(city.lower()):
            return CITY_PROVINCE[city]
    if len(label) >= 2 and label[:2] in PROVINCE_DOMAIN_PREFIX:
        return PROVINCE_DOMAIN_PREFIX[label[:2]]
    return ""


def _infer_nature(item: Dict[str, Any], unofficial: bool) -> str:
    explicit = _first(item, "来源性质", "source_nature")
    if explicit in ("政府网站", "官方媒体", "次级媒体", "未知"):
        return explicit
    if not unofficial:
        issuer = _first(item, "发布或实施机构", "发布机关")
        return "政府网站" if any(term in issuer for term in GOV_TERMS) else "未知"
    issuer = _first(item, "发布或实施机构", "发布机关", "数据源")
    url = _first(item, "源网址", "url", "原文链接")
    host = _host(url)
    if host.endswith(".gov.cn") or any(term in issuer for term in GOV_TERMS):
        return "政府网站"
    if any(term in issuer for term in OFFICIAL_MEDIA_TERMS) or host.endswith("gov.cn"):
        return "官方媒体"
    if any(term in issuer for term in SECONDARY_TERMS) or any(
        term in host for term in ("news", "sina", "sohu", "163.com", "qq.com", "baidu.com")
    ):
        return "次级媒体"
    return "未知"


def _source_grade(nature: str, unofficial: bool, explicit: bool) -> str:
    # 显式来源性质优先：上游已写“次级媒体/未知”时，即使漏标非官方来源，
    # 也不能洗成“官方库”。库内材料无显式性质时才记“官方库”。
    if explicit:
        return "官方库" if (not unofficial and nature in ("政府网站", "官方媒体")) else nature
    return "官方库" if not unofficial else (nature or "未知")


def _is_official(nature: str) -> bool:
    return nature in ("政府网站", "官方媒体")


def _doc_type(item: Dict[str, Any]) -> str:
    title = _first(item, "文章标题", "标题")
    doc_no = _first(item, "发文字号", "文号")
    issuer = _first(item, "发布或实施机构", "发布机关")
    issuer_full = _first(item, "发布或实施机构", "发布机关", "数据源")
    text = " ".join([title, doc_no, issuer_full])
    if re.search(r"GB(?:/T)?\s*\d", text):
        return "国家标准"
    # "问答/解读"看标题和发布机关，不看数据源：政策原文可能被门户的问答栏目转载。
    if re.search(r"解读|问答|答记者问|一图读懂|图解", " ".join([title, issuer])):
        return "政策解读"
    if re.search(r"新闻|报道|记者", title) or re.search(
        r"新华社|人民日报|央视|中国税务报|日报|晚报|新闻网", issuer
    ):
        return "新闻报道"
    if re.search(r"《[^》]*法》", title) or title.endswith("法"):
        return "法律"
    if "条例" in text:
        return "行政法规"
    if re.search(r"令第|部令|总局令|部门规章", text):
        return "部门规章"
    local_issuer = bool(_has_local_marker(issuer_full))
    if re.search(r"公告|通知|办法|规定|意见|批复|实施细则", title):
        return "地方政策" if local_issuer else "规范性文件"
    if "公告" in text or "通知" in text:
        return "地方政策" if local_issuer else "规范性文件"
    if local_issuer:
        return "地方政策"
    return "其他"


def _channel(item: Dict[str, Any], unofficial: bool) -> str:
    raw = _first(item, "检索通道", "channel")
    if unofficial or "联网" in raw or "WebSearch" in raw:
        return "外部联网"
    return "深知库内"


def _spans(item: Dict[str, Any]) -> List[str]:
    spans: List[str] = []
    for para in item.get("段落") or []:
        if isinstance(para, dict):
            text = str(para.get("内容") or para.get("text") or "").strip()
        else:
            text = str(para or "").strip()
        if text:
            spans.append(text)
    return spans


def _tax_types(item: Dict[str, Any], title: str) -> List[str]:
    tags = item.get("文件标签") or []
    if not isinstance(tags, list):
        tags = [tags]
    found = [str(x).split("/")[-1] for x in tags if str(x).strip()]
    probes = {
        "增值税": ("增值税",), "企业所得税": ("企业所得税",), "个人所得税": ("个人所得税", "个税"),
        "消费税": ("消费税",), "房产税": ("房产税",), "车辆购置税": ("车辆购置税", "车购税"),
        "印花税": ("印花税",), "契税": ("契税",), "资源税": ("资源税",),
        "土地增值税": ("土地增值税",), "关税": ("关税",), "烟叶税": ("烟叶税",),
        "环境保护税": ("环境保护税", "环保税"), "社会保险费": ("社会保险", "社保", "养老保险"),
    }
    for name, terms in probes.items():
        if any(term in title for term in terms) and name not in found:
            found.append(name)
    return [x for x in found if x]


def build_cards(payload: Any, question_jurisdiction: str = "") -> Dict[str, Any]:
    cards: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for idx, item in enumerate(_articles(payload), start=1):
        spans = _spans(item)
        unofficial = bool(item.get("非官方来源"))
        explicit_nature = _first(item, "来源性质", "source_nature")
        explicit = explicit_nature in ("政府网站", "官方媒体", "次级媒体", "未知")
        nature = _infer_nature(item, unofficial)
        if explicit:
            nature = explicit_nature
        jurisdiction = _infer_jurisdiction(item)
        title = _first(item, "文章标题", "标题")
        official = _is_official(nature) if (unofficial or explicit) else True
        api_authority = _first(item, "数据权威性", "authority")
        data_authority = "非权威" if unofficial else api_authority
        sid = str(item.get("文章Id") or f"s{idx}")
        if unofficial and api_authority == "权威":
            warnings.append(
                f"来源 {sid} 是非官方来源但接口标了数据权威性=权威，已按非权威处理"
            )
        if unofficial and not explicit and nature == "未知":
            warnings.append(f"来源 {sid} 无法判定来源性质，已标“未知”")
        cards.append({
            "id": str(item.get("文章Id") or f"s{idx}"),
            "article_no": item.get("编号"),
            "title": title,
            "issuer": _first(item, "发布或实施机构", "发布机关"),
            "jurisdiction": jurisdiction,
            "jurisdiction_status": "known" if jurisdiction else "unknown",
            "doc_type": _doc_type(item),
            "source_grade": _source_grade(nature, unofficial, explicit),
            "source_nature": nature,
            "source_nature_status": "explicit" if explicit else "inferred",
            "source_channel": _channel(item, unofficial),
            "official": official,
            "library_material": not unofficial,
            "data_authority": data_authority,
            "published_at": _first(item, "发布日期", "date"),
            "effective_at": _first(item, "生效日期", "effectiveDate"),
            "url": _first(item, "源网址", "url", "原文链接"),
            "doc_number": _first(item, "发文字号", "文号"),
            "tax_types": _tax_types(item, title),
            "channel": _channel(item, unofficial),
            "fetch_status": "ok" if spans else "failed",
            "spans": spans,
        })
    return {
        "question_jurisdiction": question_jurisdiction,
        "sources": cards,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成税务材料画像 source cards")
    parser.add_argument("--input", required=True, help="检索结果 JSON")
    parser.add_argument("--profile", help="问题画像 JSON（读取 jurisdiction / tax_types）")
    parser.add_argument("--out", help="运行目录（会话工作区）；与 --output 文件名一起用")
    parser.add_argument("--output", default="tax_source_cards.json",
                        help="输出文件名（配合 --out）或显式输出路径（不得指向 Skill 安装目录）")
    args = parser.parse_args()

    try:
        payload = json.loads(
            run_dir.resolve_run_input(args.input, args.out).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"输入不可读：{exc}")
    question_jurisdiction = ""
    if args.profile:
        try:
            profile = json.loads(
                run_dir.resolve_run_input(args.profile, args.out).read_text(encoding="utf-8")
            )
            question_jurisdiction = str(profile.get("jurisdiction") or "")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"profile 不可读：{exc}")

    try:
        out = run_dir.resolve_write_target(args.output, args.out)
    except ValueError as exc:
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    result = build_cards(payload, question_jurisdiction)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for warning in result.get("warnings") or []:
        print(f"材料画像告警：{warning}", file=sys.stderr)
    print(json.dumps({
        "output": str(out),
        "sources": len(result["sources"]),
        "warnings": len(result.get("warnings") or []),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
