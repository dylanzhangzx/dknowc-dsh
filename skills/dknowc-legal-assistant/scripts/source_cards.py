#!/usr/bin/env python3
"""材料画像：把检索结果转成带地域、来源等级、文件类型、抓取状态的 source cards。

输入：legal_search.py / merge_search_results.py 的 JSON，或含“检索文章”数组的对象。
输出：legal_source_cards.json

设计目的：让“河北的 208 元被当成福建的 208 元”这类问题在材料层就暴露，
而不是等模型写进答案后再靠人发现。

用法：
  python3 scripts/source_cards.py \
    --input legal_merged.json \
    --profile legal_question_profile.json \
    --output legal_source_cards.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from question_profile import PROVINCES
from path_guard import safe_read_path, safe_write_path

PROVINCE_SHORT = {
    p.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", ""): p
    for p in PROVINCES
}
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
CITY_PROVINCE = {
    "石家庄": "河北省", "福州": "福建省", "厦门": "福建省", "泉州": "福建省", "漳州": "福建省",
    "莆田": "福建省", "三明": "福建省", "南平": "福建省", "龙岩": "福建省",
    "宁德": "福建省", "晋江": "福建省", "永春": "福建省", "安溪": "福建省",
    "德化": "福建省", "安吉": "浙江省", "杭州": "浙江省", "宁波": "浙江省", "温州": "浙江省",
    "湖州": "浙江省", "嘉兴": "浙江省", "绍兴": "浙江省", "金华": "浙江省",
    "衢州": "浙江省", "舟山": "浙江省", "台州": "浙江省", "丽水": "浙江省",
    "广州": "广东省", "深圳": "广东省", "珠海": "广东省", "汕头": "广东省",
    "佛山": "广东省", "韶关": "广东省", "湛江": "广东省", "肇庆": "广东省",
    "江门": "广东省", "茂名": "广东省", "惠州": "广东省", "梅州": "广东省",
    "汕尾": "广东省", "河源": "广东省", "阳江": "广东省", "清远": "广东省",
    "东莞": "广东省", "中山": "广东省", "潮州": "广东省", "揭阳": "广东省",
    "云浮": "广东省", "鹤山": "广东省", "普宁": "广东省", "茂南": "广东省",
}
NATIONAL_TERMS = (
    "全国", "中华人民共和国", "国务院", "全国人民代表大会", "全国人大常委会",
    "最高人民法院", "最高人民检察院", "中共中央", "国家发展改革委",
    "人力资源和社会保障部", "财政部", "教育部", "公安部", "应急管理部",
    "国家市场监督管理总局", "国家卫生健康委员会",
)


def _first(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


_DATE_PATTERN = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?")
_COMPACT_DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _norm_date(value: Any) -> str:
    """把 2026年1月1日 / 2026.01.01 / 2026/01/01 / 20260101 统一成 ISO 日期。

    数据库里的失效日期不全是 ISO 格式；按字符串直接比较会把“2026年1月1日”判成
    未失效（2026-11-13 审核重要项）。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    match = _DATE_PATTERN.search(text)
    parts = match.groups() if match else None
    if not parts:
        compact = _COMPACT_DATE.match(text)
        parts = compact.groups() if compact else None
    if not parts:
        return ""
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError:
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


def _infer_jurisdiction(item: Dict[str, Any], text: str) -> str:
    area = _first(item, "办理地域", "地域", "area")
    if area in ("中国", "全国"):
        return "全国"
    if area:
        return area
    # 只从标题/机构/数据源判断，不扫描全文：政策全文常提到多个省份，
    # 用全文匹配会把“国务院文件”误标成它正文里提到的某个省。
    title = _first(item, "文章标题", "标题")
    issuer = _first(item, "发布或实施机构")
    source = _first(item, "数据源")
    meta = " ".join([title, issuer, source])
    issuer_text = " ".join([issuer, source])

    # 标题里的省名：地方实施办法优先；但“国务院关于河北省……”这类
    # 中央文件仍归全国，不能因为标题提到某省就当成地方文件。
    title_province = next((p for p in PROVINCES if p in title), "")
    if not title_province:
        title_province = next((p for short, p in PROVINCE_SHORT.items() if short and short in title), "")
    issuer_national = any(term in issuer_text for term in NATIONAL_TERMS)
    if title_province and (not issuer_national or "全国人民代表大会常务委员会" in issuer):
        return title_province

    # 国务院/部委文件归全国，不能因为正文提到某省就标成该省。
    if any(term in meta for term in NATIONAL_TERMS):
        return "全国"

    for province in PROVINCES:
        if province in meta:
            return province
    for short, province in PROVINCE_SHORT.items():
        if short and short in meta:
            return province

    # 城市名优先于 URL 前缀：heshan.gov.cn 是广东鹤山，不是河北（he）。
    url = _first(item, "源网址", "url", "原文链接")
    host = (urlparse(url).hostname or "").lower() if url else ""
    labels = host.split(".") if host else []
    label = labels[0] if labels else ""
    if label in ("www", "m") and len(labels) > 1:
        label = labels[1]
    for city, province in CITY_PROVINCE.items():
        if city in meta or (label and label.startswith(city.lower())):
            return province
    # 从 URL 的域名前缀补省份：fjyc.gov.cn -> 福建，zj.gov.cn -> 浙江。
    if len(label) >= 2 and label[:2] in PROVINCE_DOMAIN_PREFIX:
        return PROVINCE_DOMAIN_PREFIX[label[:2]]
    return "全国" if "中国" in meta or "全国" in meta else ""


def _source_grade(item: Dict[str, Any]) -> str:
    nature = _first(item, "来源性质", "source_nature")
    if nature:
        return nature
    if item.get("非官方来源"):
        return "未知"
    return "官方库"


def _is_official(item: Dict[str, Any]) -> bool:
    nature = _first(item, "来源性质", "source_nature")
    if nature in ("次级媒体", "次级媒体/未知", "未知"):
        return False
    # “非官方来源=True”只表示不是深知库内材料，不否定政府网站本身的官方属性。
    if nature in ("政府网站", "官方媒体"):
        return True
    if item.get("非官方来源"):
        return False
    return _first(item, "数据权威性", "authority") in ("权威", "authoritative", "")


def _doc_type(item: Dict[str, Any]) -> str:
    title = _first(item, "文章标题", "标题")
    doc_no = _first(item, "发文字号", "文号")
    issuer = _first(item, "发布或实施机构", "发布机关")
    text = title + " " + doc_no + " " + issuer
    if re.search(r"GB(?:/T)?\s*\d", text):
        return "国家标准"
    if re.search(r"日报|晚报|新闻|财经|记者", text):
        return "新闻报道"
    if "司法解释" in text or "批复" in text or "解释" in title:
        return "司法解释"
    if "条例" in text:
        return "行政法规"
    if re.search(r"人民政府|办公厅|人社局|财政厅|教育局|消防救援", text):
        return "地方政策"
    if re.search(r"通知|办法|意见|指导意见|实施细则|规定", text):
        return "政策文件"
    if title.endswith("法") or "中华人民共和国" in title:
        return "法律"
    return "其他"


def _channel(item: Dict[str, Any]) -> str:
    raw = _first(item, "检索通道", "channel")
    raw = re.sub(
        r"宿主网页抓取[^、·]*|阶段[一二三]|库内政策[^、·]*|政策档案全文|条款级召回|^00[1-5]$|[（(]00[1-5][）)]",
        "", raw,
    )
    tokens = []
    for token in re.split(r"[、·]", raw):
        token = token.strip()
        if not token or token in ("联网", "可信联网", "宿主 WebSearch"):
            continue
        if "条款级召回" in token:
            token = re.split(r"[（(]", token, maxsplit=1)[0].strip()
        if not token or re.fullmatch(r"00[1-5]", token) or "条款级召回" in token:
            continue
        if token.startswith("深知可信搜索"):
            token = "深知可信搜索"
        elif token.startswith("深知深度搜索"):
            token = "深知深度搜索"
        elif token.startswith("法律"):
            token = "法律"
        if token not in tokens:
            tokens.append(token)
    return " · ".join(tokens)


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


def build_cards(payload: Any, question_jurisdiction: str = "", as_of: str = "") -> Dict[str, Any]:
    cards: List[Dict[str, Any]] = []
    for idx, item in enumerate(_articles(payload), start=1):
        spans = _spans(item)
        text = "\n".join(spans)
        jurisdiction = _infer_jurisdiction(item, text)
        expired_at = _first(item, "失效日期", "expired_at")
        expired_iso = _norm_date(expired_at)
        as_of_iso = _norm_date(as_of)
        is_expired = bool(expired_iso and as_of_iso and expired_iso < as_of_iso)
        cards.append({
            "id": str(item.get("编号") or item.get("文章Id") or f"s{idx}"),
            "title": _first(item, "文章标题", "标题"),
            "issuer": _first(item, "发布或实施机构", "发布机关"),
            "jurisdiction": jurisdiction,
            "jurisdiction_status": "known" if jurisdiction else "unknown",
            "doc_type": _doc_type(item),
            "source_grade": _source_grade(item),
            "source_channel": _first(item, "来源通道", "source_channel") or (
                "外部联网" if item.get("非官方来源") else "深知库内"
            ),
            "official": _is_official(item),
            "published_at": _first(item, "发布日期", "date"),
            "effective_at": _first(item, "生效日期", "effectiveDate"),
            "expired_at": expired_at,
            "is_expired": is_expired,
            "version_note": (
                f"材料标注失效日期 {expired_at}，为旧版本；现行版本请走法条模式"
                if is_expired else ""
            ),
            "url": _first(item, "源网址", "url", "原文链接"),
            "doc_number": _first(item, "发文字号", "文号"),
            "channel": _channel(item),
            "fetch_status": "ok" if spans else "failed",
            "spans": spans,
        })
    return {
        "question_jurisdiction": question_jurisdiction,
        "sources": cards,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成材料画像 source cards")
    parser.add_argument("--input", required=True, help="检索结果 JSON（run 目录内）")
    parser.add_argument("--profile", help="问题画像 JSON（run 目录内，读取 jurisdiction/as_of）")
    parser.add_argument("--output", default="legal_source_cards.json", help="输出文件名（落到 --run 目录）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）")
    args = parser.parse_args()

    try:
        payload = json.loads(safe_read_path(args.input, args.run).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"输入不可读：{exc}")
    question_jurisdiction = ""
    as_of = ""
    if args.profile:
        try:
            profile = json.loads(safe_read_path(args.profile, args.run).read_text(encoding="utf-8"))
            question_jurisdiction = str(profile.get("jurisdiction") or "")
            as_of = str(profile.get("as_of") or "")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"profile 不可读：{exc}")

    try:
        out = safe_write_path(args.output, args.run)
    except ValueError as exc:
        parser.error(str(exc))
    result = build_cards(payload, question_jurisdiction, as_of)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "sources": len(result["sources"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
