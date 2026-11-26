#!/usr/bin/env python3
"""问题画像：把税务问题转成可校验的结构化字段。

不是"全自动理解税务问题"，而是给 Agent 一个固定落点：
- jurisdiction：地域（全国 / 省 / 省市县）
- as_of：截至日期
- domain：税务 / 社会保险
- tax_types：税种（增值税、企业所得税、个人所得税……）
- taxpayer_types：纳税人身份（小规模、一般纳税人、小型微利、个体工商户……）
- incentives：优惠事项（免征、减按、加计扣除、减半、留抵退税……）
- filing：申报/征期（按月、按季、年度汇算、预缴……）
- policy_years：问题里点名的年度
- entities：文件全名、引用短语、关键名词
- requested：用户要什么（税率/标准、适用条件、申报期限、计算、是否、最新……）

Agent 可以手写 profile 后用 --input 校验；也可以用 --question 做启发式初稿，
再人工/模型修正。source_cards.py / verify_claims.py 都读这个文件。

用法：
  python3 scripts/question_profile.py \
    --question "2026年北京市小规模纳税人月销售额10万元以下还免增值税吗？" \
    --as-of 2026-11-10 \
    --output tax_question_profile.json

  python3 scripts/question_profile.py --input profile.json --output normalized.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from typing import Any, Dict, List

import run_dir

PROVINCES = (
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省",
    "黑龙江省", "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省",
    "山东省", "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区",
    "海南省", "重庆市", "四川省", "贵州省", "云南省", "西藏自治区",
    "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    "香港特别行政区", "澳门特别行政区", "台湾省",
)

MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}

PROVINCE_SHORT = {
    p.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", ""): p
    for p in PROVINCES
}

# 税务/社保问题最常见的地市与直辖市辖区：只用于把"大兴区""深圳市"归到省份，
# 不做行政区划全集。命中即映射到省级，问题本身仍保留区县名。
CITY_PROVINCE = {
    # 直辖市辖区
    "东城": "北京市", "西城": "北京市", "朝阳": "北京市", "海淀": "北京市",
    "丰台": "北京市", "石景山": "北京市", "门头沟": "北京市", "房山": "北京市",
    "通州": "北京市", "顺义": "北京市", "昌平": "北京市", "大兴": "北京市",
    "怀柔": "北京市", "平谷": "北京市", "密云": "北京市", "延庆": "北京市",
    "黄浦": "上海市", "徐汇": "上海市", "长宁": "上海市", "静安": "上海市",
    "普陀": "上海市", "虹口": "上海市", "杨浦": "上海市", "闵行": "上海市",
    "宝山": "上海市", "嘉定": "上海市", "浦东": "上海市", "金山": "上海市",
    "松江": "上海市", "青浦": "上海市", "奉贤": "上海市", "崇明": "上海市",
    "和平": "天津市", "河东": "天津市", "河西": "天津市", "南开": "天津市",
    "红桥": "天津市", "东丽": "天津市", "西青": "天津市", "津南": "天津市",
    "北辰": "天津市", "武清": "天津市", "宝坻": "天津市", "滨海新区": "天津市",
    "宁河": "天津市", "静海": "天津市", "蓟州": "天津市",
    "渝中": "重庆市", "江北": "重庆市", "沙坪坝": "重庆市", "九龙坡": "重庆市",
    "南岸": "重庆市", "北碚": "重庆市", "渝北": "重庆市", "巴南": "重庆市",
    "两江新区": "重庆市",
    # 地市
    "石家庄": "河北省", "唐山": "河北省", "廊坊": "河北省", "保定": "河北省",
    "邯郸": "河北省", "秦皇岛": "河北省", "张家口": "河北省", "承德": "河北省",
    "沧州": "河北省", "邢台": "河北省", "衡水": "河北省",
    "太原": "山西省", "大同": "山西省", "运城": "山西省",
    "呼和浩特": "内蒙古自治区", "包头": "内蒙古自治区", "鄂尔多斯": "内蒙古自治区",
    "沈阳": "辽宁省", "大连": "辽宁省", "鞍山": "辽宁省",
    "长春": "吉林省", "吉林市": "吉林省", "延边": "吉林省",
    "哈尔滨": "黑龙江省", "大庆": "黑龙江省", "齐齐哈尔": "黑龙江省",
    "南京": "江苏省", "苏州": "江苏省", "无锡": "江苏省", "常州": "江苏省",
    "南通": "江苏省", "徐州": "江苏省", "扬州": "江苏省", "镇江": "江苏省",
    "泰州": "江苏省", "盐城": "江苏省", "淮安": "江苏省", "连云港": "江苏省",
    "宿迁": "江苏省",
    "杭州": "浙江省", "宁波": "浙江省", "温州": "浙江省", "嘉兴": "浙江省",
    "湖州": "浙江省", "绍兴": "浙江省", "金华": "浙江省", "衢州": "浙江省",
    "舟山": "浙江省", "台州": "浙江省", "丽水": "浙江省",
    "合肥": "安徽省", "芜湖": "安徽省", "蚌埠": "安徽省", "安庆": "安徽省",
    "福州": "福建省", "厦门": "福建省", "泉州": "福建省", "漳州": "福建省",
    "莆田": "福建省", "三明": "福建省", "南平": "福建省", "龙岩": "福建省",
    "宁德": "福建省", "晋江": "福建省", "安溪": "福建省", "石狮": "福建省",
    "南昌": "江西省", "赣州": "江西省", "九江": "江西省", "上饶": "江西省",
    "济南": "山东省", "青岛": "山东省", "烟台": "山东省", "潍坊": "山东省",
    "临沂": "山东省", "淄博": "山东省", "济宁": "山东省", "威海": "山东省",
    "郑州": "河南省", "洛阳": "河南省", "开封": "河南省", "新乡": "河南省",
    "武汉": "湖北省", "宜昌": "湖北省", "襄阳": "湖北省", "黄石": "湖北省",
    "长沙": "湖南省", "株洲": "湖南省", "湘潭": "湖南省", "岳阳": "湖南省",
    "广州": "广东省", "深圳": "广东省", "珠海": "广东省", "汕头": "广东省",
    "佛山": "广东省", "韶关": "广东省", "湛江": "广东省", "肇庆": "广东省",
    "江门": "广东省", "茂名": "广东省", "惠州": "广东省", "梅州": "广东省",
    "汕尾": "广东省", "河源": "广东省", "阳江": "广东省", "清远": "广东省",
    "东莞": "广东省", "中山": "广东省", "潮州": "广东省", "揭阳": "广东省",
    "云浮": "广东省", "鹤山": "广东省", "普宁": "广东省",
    "南宁": "广西壮族自治区", "柳州": "广西壮族自治区", "桂林": "广西壮族自治区",
    "海口": "海南省", "三亚": "海南省", "儋州": "海南省",
    "成都": "四川省", "绵阳": "四川省", "德阳": "四川省", "宜宾": "四川省",
    "贵阳": "贵州省", "遵义": "贵州省", "六盘水": "贵州省",
    "昆明": "云南省", "大理": "云南省", "曲靖": "云南省",
    "拉萨": "西藏自治区", "日喀则": "西藏自治区", "林芝": "西藏自治区",
    "西安": "陕西省", "咸阳": "陕西省", "宝鸡": "陕西省", "榆林": "陕西省",
    "兰州": "甘肃省", "天水": "甘肃省", "酒泉": "甘肃省",
    "西宁": "青海省", "海东": "青海省",
    "银川": "宁夏回族自治区", "石嘴山": "宁夏回族自治区",
    "乌鲁木齐": "新疆维吾尔自治区", "喀什": "新疆维吾尔自治区", "伊犁": "新疆维吾尔自治区",
}

TAX_TYPES = {
    "个人所得税": (
        "个人所得税", "个税", "工资薪金", "综合所得", "经营所得", "劳务报酬",
        "年终奖", "全年一次性奖金", "专项附加扣除", "累计预扣", "汇算清缴",
    ),
    "增值税": (
        "增值税", "小规模纳税人", "一般纳税人", "征收率", "进项税额", "销项税额",
        "留抵退税", "专用发票", "普通发票", "销售额",
    ),
    "企业所得税": (
        "企业所得税", "小型微利", "研发费用加计", "加计扣除", "税前扣除",
        "应纳税所得额", "弥补亏损", "预缴",
    ),
    "消费税": ("消费税",),
    "房产税": ("房产税",),
    "城镇土地使用税": ("城镇土地使用税", "土地使用税"),
    "车辆购置税": ("车辆购置税", "车购税", "购置税"),
    "车船税": ("车船税",),
    "印花税": ("印花税",),
    "契税": ("契税",),
    "资源税": ("资源税",),
    "城市维护建设税": ("城市维护建设税", "城建税"),
    "土地增值税": ("土地增值税",),
    "关税": ("关税", "进出口税"),
    "烟叶税": ("烟叶税",),
    "环境保护税": ("环境保护税", "环保税"),
    "耕地占用税": ("耕地占用税",),
    "船舶吨税": ("船舶吨税",),
    "社会保险费": (
        "社保", "社会保险", "养老保险", "医疗保险", "失业保险", "工伤保险",
        "生育保险", "缴费基数", "灵活就业",
    ),
}

TAXPAYER_TYPES = {
    "小规模纳税人": ("小规模纳税人", "小规模"),
    "一般纳税人": ("一般纳税人",),
    "小型微利企业": ("小型微利", "小微企业"),
    "个体工商户": ("个体工商户", "个体户"),
    "自然人": ("自然人", "个人"),
    "居民企业": ("居民企业",),
    "非居民企业": ("非居民企业", "非居民"),
    "灵活就业人员": ("灵活就业",),
    "高新技术企业": ("高新技术企业",),
    "境外单位或个人": ("境外单位", "境外个人", "外国企业"),
}

INCENTIVES = {
    "免征": ("免征", "免税", "不征"),
    "减征": ("减征", "减半", "减按"),
    "加计扣除": ("加计扣除", "加计抵减"),
    "留抵退税": ("留抵退税", "留抵"),
    "即征即退": ("即征即退",),
    "先征后返": ("先征后返", "先征后退"),
    "困难减免": ("困难减免", "减免税"),
    "税额抵免": ("税额抵免", "投资抵免"),
    "加速折旧": ("加速折旧", "一次性扣除"),
    "税收返还": ("税收返还", "财政返还"),
}

FILING_TERMS = {
    "按月申报": ("按月申报", "按月"),
    "按季申报": ("按季申报", "按季"),
    "年度汇算": ("年度汇算", "汇算清缴", "综合所得汇算"),
    "预缴": ("预缴", "预扣预缴"),
    "申报期限": ("申报期限", "申报期", "征期", "截止日期", "次月"),
    "纳税义务发生时间": ("纳税义务发生时间", "纳税义务时间"),
}

REQUESTED_TERMS = {
    "税率/标准": ("税率", "征收率", "标准", "多少", "比例", "扣除标准", "上限", "下限", "基数"),
    "适用条件": ("条件", "资格", "适用", "能不能", "可不可以", "是否", "有没有", "属不属于"),
    "申报期限": ("申报期限", "申报期", "征期", "截止", "什么时候申报", "按月", "按季"),
    "计算": ("怎么算", "计算", "算一下", "滞纳金", "税额", "应纳", "减免额", "算例"),
    "政策依据": ("依据", "哪个文件", "什么文件", "文号", "出处", "第几条"),
    "最新/现行": ("最新", "现行", "还有效", "延续", "到期", "2026", "2027"),
    "办理流程": ("怎么办理", "申请", "备案", "流程", "资料", "提交"),
    "优惠资格": ("优惠", "减免", "免征", "减半", "加计", "留抵"),
    "逐项": ("逐项", "分别", "列举", "几项", "各是多少"),
}

DOC_TYPE_TERMS = {
    "法律": ("法律", "税法"),
    "行政法规": ("条例", "暂行条例"),
    "部门规章": ("部门规章", "部令", "总局令", "令第"),
    "规范性文件": ("公告", "通知", "办法", "规定", "批复", "意见", "实施细则"),
    "政策解读": ("解读", "问答", "答记者问", "一图读懂"),
    "新闻报道": ("新闻", "报道"),
}

OUT_OF_SCOPE_TERMS = (
    "香港", "澳门", "台湾", "境外", "国外", "外国", "美国", "英国", "新加坡",
    "日本", "韩国", "德国", "法国", "欧盟", "跨境税收协定",
)

DATE_RE = re.compile(r"(20\d{2}[-年/]\d{1,2}[-月/]\d{1,2}日?)")
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
LOCALITY_RE = re.compile(r"([一-龥]{2,10}(?:县|区|市|旗|盟|州))")
DOC_RE = re.compile(r"《[^》]{2,80}》")
QUOTED_RE = re.compile(r"[“\"]([^”\"]{2,40})[”\"]")


def _uniq(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _norm_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return date.today().isoformat()
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-")
    parts = [p for p in text.split("-") if p]
    if len(parts) >= 3:
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
        except ValueError:
            pass
    if len(parts) == 1 and re.fullmatch(r"(?:19|20)\d{2}", parts[0]):
        return f"{parts[0]}-01-01"
    return text


def _find_province(text: str) -> str:
    province = next((p for p in PROVINCES if p in text), "")
    if province:
        return province
    # 短名按长度倒序，避免"吉林"先命中"吉林市"以外的无关词。
    for short in sorted(PROVINCE_SHORT, key=len, reverse=True):
        if short and short in text:
            return PROVINCE_SHORT[short]
    return ""


def _find_city_province(text: str) -> str:
    for city in sorted(CITY_PROVINCE, key=len, reverse=True):
        if city in text:
            return CITY_PROVINCE[city]
    return ""


def _extract_jurisdiction(question: str, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    province = _find_province(question)
    rest = question
    if province:
        idx = question.find(province)
        if idx >= 0:
            rest = question[idx + len(province):]
    match = LOCALITY_RE.search(rest)
    locality = match.group(1) if match else ""
    if locality in {"本市", "该市", "全市", "各县", "市区", "当地", "本省", "全省", "全国"}:
        locality = ""
    if province and locality:
        return province + locality
    if province:
        return province
    if locality:
        return _find_city_province(locality) or locality
    city_province = _find_city_province(question)
    if city_province:
        return city_province
    # 税务问题绝大多数默认全国口径；地方口径会在标题/机构里体现，由 source_cards 再核。
    return "全国"


def _match_terms(question: str, mapping: Dict[str, tuple]) -> List[str]:
    return [name for name, terms in mapping.items() if any(t in question for t in terms)]


def _extract_tax_types(question: str) -> List[str]:
    return _match_terms(question, TAX_TYPES)


def _extract_taxpayer_types(question: str) -> List[str]:
    found = _match_terms(question, TAXPAYER_TYPES)
    # "个人"是高频泛词；已经命中具体身份时不再单列"自然人"。
    if "自然人" in found and len(found) > 1 and "境外单位或个人" not in question:
        found = [x for x in found if x != "自然人"]
    return found


def _extract_incentives(question: str) -> List[str]:
    return _match_terms(question, INCENTIVES)


def _extract_filing(question: str) -> List[str]:
    return _match_terms(question, FILING_TERMS)


def _extract_domains(question: str, tax_types: List[str]) -> List[str]:
    domains: List[str] = []
    if any(t not in ("社会保险费",) for t in tax_types) or any(
        term in question for term in ("税", "纳税", "发票", "申报", "滞纳金", "税务")
    ):
        domains.append("税务")
    if "社会保险费" in tax_types:
        domains.append("社会保险")
    return domains or ["税务"]


def _extract_doc_types(question: str) -> List[str]:
    return _match_terms(question, DOC_TYPE_TERMS)


def _extract_requested(question: str) -> List[str]:
    return _match_terms(question, REQUESTED_TERMS)


def _extract_entities(question: str, tax_types: List[str], taxpayer_types: List[str],
                      incentives: List[str]) -> List[str]:
    entities: List[str] = []
    entities.extend(DOC_RE.findall(question))
    entities.extend(QUOTED_RE.findall(question))
    entities.extend(tax_types)
    entities.extend(taxpayer_types)
    entities.extend(incentives)
    for term in (
        "专项附加扣除", "全年一次性奖金", "月销售额10万元", "月销售额", "季度销售额",
        "起征点", "免征额", "税率表", "速算扣除数", "滞纳金", "纳税义务发生时间",
        "缴费基数", "上下限", "汇算清缴", "预扣预缴", "留抵退税", "加计扣除",
    ):
        if term in question:
            entities.append(term)
    if not entities and question:
        entities.append("税务")
    return _uniq(entities)


def build_profile(question: str, as_of: str = "", jurisdiction: str = "") -> Dict[str, Any]:
    question = (question or "").strip()
    date_match = DATE_RE.search(question)
    tax_types = _extract_tax_types(question)
    taxpayer_types = _extract_taxpayer_types(question)
    incentives = _extract_incentives(question)
    out_of_scope = [term for term in OUT_OF_SCOPE_TERMS if term in question]
    return {
        "question": question,
        "jurisdiction": _extract_jurisdiction(question, jurisdiction),
        "as_of": _norm_date(as_of or (date_match.group(1) if date_match else "")),
        "domain": _extract_domains(question, tax_types),
        "tax_types": tax_types,
        "taxpayer_types": taxpayer_types,
        "incentives": incentives,
        "filing": _extract_filing(question),
        "policy_years": _uniq(YEAR_RE.findall(question)),
        "doc_types": _extract_doc_types(question),
        "entities": _extract_entities(question, tax_types, taxpayer_types, incentives),
        "requested": _extract_requested(question),
        "scope_notice": (
            "本 Skill 只覆盖中国大陆税务；涉港澳台/外国税制只答内地一侧义务，域外规则不展开"
            if out_of_scope else ""
        ),
        "out_of_scope": bool(out_of_scope),
    }


def validate_profile(profile: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    if not isinstance(profile, dict):
        return ["profile 必须是 JSON 对象"]
    if not str(profile.get("question") or "").strip():
        issues.append("缺少 question（原始问题）")
    if not str(profile.get("jurisdiction") or "").strip():
        issues.append("缺少 jurisdiction（问题地域）；无法确定时必须写“全国”或具体省市县")
    if not str(profile.get("as_of") or "").strip():
        issues.append("缺少 as_of（截至日期）")
    if not isinstance(profile.get("entities"), list) or not profile.get("entities"):
        issues.append("entities 必须是非空数组")
    if not isinstance(profile.get("requested"), list) or not profile.get("requested"):
        issues.append("requested 必须是非空数组")
    if not isinstance(profile.get("tax_types"), list):
        issues.append("tax_types 必须是数组（可为空，但字段要在）")
    if not isinstance(profile.get("taxpayer_types"), list):
        issues.append("taxpayer_types 必须是数组（可为空，但字段要在）")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/校验税务问题画像")
    parser.add_argument("--question", help="用户原始问题")
    parser.add_argument("--as-of", default="", help="截至日期 YYYY-MM-DD")
    parser.add_argument("--jurisdiction", default="", help="问题地域，如“北京市大兴区”")
    parser.add_argument("--input", help="已有 profile JSON，校验并规范化")
    parser.add_argument("--out", help="运行目录（会话工作区）；与 --output 文件名一起用")
    parser.add_argument("--output", default="tax_question_profile.json",
                        help="输出文件名（配合 --out）或显式输出路径（不得指向 Skill 安装目录）")
    args = parser.parse_args()

    if args.input:
        try:
            profile = json.loads(
                run_dir.resolve_run_input(args.input, args.out).read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"profile 不可读：{exc}")
    else:
        if not args.question:
            parser.error("必须提供 --question 或 --input")
        profile = build_profile(args.question, args.as_of, args.jurisdiction)

    issues = validate_profile(profile)
    if issues:
        print("问题画像不完整：", file=sys.stderr)
        for issue in issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    try:
        out = run_dir.resolve_write_target(args.output, args.out)
    except ValueError as exc:
        parser.error(str(exc))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "profile": profile}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
