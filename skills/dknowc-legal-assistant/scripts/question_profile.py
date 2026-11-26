#!/usr/bin/env python3
"""问题画像：把用户问题转成可校验的结构化字段。

这不是“全自动理解法律问题”，而是给 Agent 一个固定落点：
- 地域（jurisdiction）
- 时点（as_of）
- 领域（domain）
- 文件类型（doc_types）
- 实体（entities）
- 用户要什么（requested）

Agent 可以手写 profile 后用 --input 校验；也可以用 --question 做启发式初稿，
再人工/模型修正。后续 source_cards.py / verify_claims.py 都读这个文件。

用法：
  python3 scripts/question_profile.py \
    --question "福建省泉州市安溪县2026年城乡居民基础养老金是多少？" \
    --output legal_question_profile.json

  python3 scripts/question_profile.py --input profile.json --output normalized.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from path_guard import safe_read_path, safe_write_path

PROVINCES = (
    "北京市", "天津市", "河北省", "山西省", "内蒙古自治区", "辽宁省", "吉林省",
    "黑龙江省", "上海市", "江苏省", "浙江省", "安徽省", "福建省", "江西省",
    "山东省", "河南省", "湖北省", "湖南省", "广东省", "广西壮族自治区",
    "海南省", "重庆市", "四川省", "贵州省", "云南省", "西藏自治区",
    "陕西省", "甘肃省", "青海省", "宁夏回族自治区", "新疆维吾尔自治区",
    "香港特别行政区", "澳门特别行政区", "台湾省",
)

MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}

DOMAIN_KEYWORDS = {
    "劳动": ("劳动", "工资", "加班", "年假", "解除", "裁员", "社保", "工伤", "竞业"),
    "借贷": ("借贷", "借款", "利息", "LPR", "民间借贷", "还款"),
    "消防": ("消防", "火灾", "疏散", "灭火", "民宿", "农家乐"),
    "社保": ("养老金", "养老保险", "城乡居民", "基础养老金", "退休"),
    "税务": ("税", "发票", "纳税人", "税率", "增值税", "个税"),
    "合同": ("合同", "违约", "定金", "押金", "解除合同"),
    "公司": ("公司", "股权", "股东", "出资", "清算"),
    "婚姻": ("婚姻", "离婚", "抚养", "彩礼", "继承"),
    "消费": ("消费", "退费", "充值", "预付", "消费者"),
    "行政": ("行政处罚", "行政许可", "行政复议", "政府信息公开"),
}

DOC_TYPE_KEYWORDS = {
    "法律": ("法", "法律"),
    "行政法规": ("条例", "行政法规"),
    "司法解释": ("司法解释", "解释", "批复"),
    "地方性法规": ("地方性法规", "省条例"),
    "政策文件": ("政策", "办法", "通知", "意见", "指导意见", "实施细则"),
    "国家标准": ("GB/T", "GB ", "国家标准", "标准"),
}

REQUEST_KEYWORDS = {
    "标准金额": ("多少", "标准", "金额", "每月", "每人"),
    "依据文件": ("依据", "哪个文件", "什么文件", "文号", "出处"),
    "是否": ("是否", "有没有", "属不属于", "算不算"),
    "计算": ("计算", "怎么算", "利息", "赔偿", "补偿"),
    "最新": ("最新", "现行", "2026", "2025"),
    "逐项": ("逐项", "分别", "列举", "几项"),
}

LOCALITY_RE = re.compile(r"([一-龥]{2,8}(?:县|区|市|旗))")
DATE_RE = re.compile(r"(20\d{2}[-年/]\d{1,2}[-月/]\d{1,2}日?)")
LAW_RE = re.compile(r"《[^》]{2,60}》")
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
    return text


def _extract_jurisdiction(question: str, explicit: str = "") -> str:
    if explicit.strip():
        return explicit.strip()
    province = next((p for p in PROVINCES if p in question), "")
    rest = question
    if province:
        idx = question.find(province)
        rest = question[idx + len(province):]
    match = LOCALITY_RE.search(rest)
    locality = match.group(1) if match else ""
    if locality in {"本市", "该市", "全市", "各县", "市区", "当地", "本省", "全省"}:
        locality = ""
    if province and locality:
        return province + locality
    return province or locality


def _extract_domains(question: str) -> List[str]:
    return [name for name, terms in DOMAIN_KEYWORDS.items() if any(t in question for t in terms)]


def _extract_doc_types(question: str) -> List[str]:
    return [name for name, terms in DOC_TYPE_KEYWORDS.items() if any(t in question for t in terms)]


def _extract_requested(question: str) -> List[str]:
    return [name for name, terms in REQUEST_KEYWORDS.items() if any(t in question for t in terms)]


def _extract_entities(question: str) -> List[str]:
    entities = LAW_RE.findall(question)
    entities.extend(QUOTED_RE.findall(question))
    # 常见实体短语：避免把整个问题当实体。
    for term in ("基础养老金", "城乡居民基本养老保险", "民间借贷", "民宿", "农家乐",
                 "公众聚集场所", "经济补偿", "赔偿金", "年休假", "LPR"):
        if term in question:
            entities.append(term)
    return _uniq(entities)


def build_profile(question: str, as_of: str = "", jurisdiction: str = "") -> Dict[str, Any]:
    question = (question or "").strip()
    date_match = DATE_RE.search(question)
    return {
        "question": question,
        "jurisdiction": _extract_jurisdiction(question, jurisdiction),
        "as_of": _norm_date(as_of or (date_match.group(1) if date_match else "")),
        "domain": _extract_domains(question),
        "doc_types": _extract_doc_types(question),
        "entities": _extract_entities(question),
        "requested": _extract_requested(question),
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
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/校验问题画像")
    parser.add_argument("--question", help="用户原始问题")
    parser.add_argument("--as-of", default="", help="截至日期 YYYY-MM-DD")
    parser.add_argument("--jurisdiction", default="", help="问题地域，如“福建省泉州市安溪县”")
    parser.add_argument("--input", help="已有 profile JSON（run 目录内），校验并规范化")
    parser.add_argument("--output", default="legal_question_profile.json", help="输出文件名（落到 --run 目录）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）")
    args = parser.parse_args()

    if args.input:
        try:
            profile = json.loads(safe_read_path(args.input, args.run).read_text(encoding="utf-8"))
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
        out = safe_write_path(args.output, args.run)
    except ValueError as exc:
        parser.error(str(exc))
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "profile": profile}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
