#!/usr/bin/env python3
"""结论图校验：用问题画像 + 材料画像 + claim 做通用对齐。

替代“针对某个错题写一条正则”的做法。核心检查维度：
- 地域：claim / 来源 / 问题是否一致（全国口径除外）
- 时点：claim 的 as_of 是否明确
- 来源等级：次级媒体不能直接当法律结论；媒体数值必须带官方口径或待核验
- 引文：direct 的 quote 是否在来源 span 里，数量是否等于枚举项数
- 计算：calculation 是否用 calc_period，天数口径是否写明
- 否定：negative 是否有 as_of/coverage，答案是否写成“未上调/未发生”
- 推断：inference 是否有“通常/以属地……认定为准”
- 解释争议：interpretation 是否同时给出 primary / alternative

用法：
  python3 scripts/verify_claims.py \
    --claims legal_claims.json \
    --sources legal_source_cards.json \
    --profile legal_question_profile.json \
    --answer legal_answer.txt \
    --output legal_verify.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

import calc_legal
# dsh：内核抽离到插件内兄弟 skill「溯源核验报告生成器」（dk-trace-report），
# 此处注入其 scripts 目录到 sys.path；母版同目录形态下目录不存在、行为不变。
import sys as _sys
from pathlib import Path as _Path
_KERNEL_DIR = _Path(__file__).resolve().parent.parent.parent / "dk-trace-report" / "scripts"
if _KERNEL_DIR.is_dir():
    _sys.path.insert(0, str(_KERNEL_DIR))

import trust_digest
from calc_period import build_result as calc_build_result
from calc_period import parse_date, parse_decimal, parse_rate
from check_answer import count_enumerations, quote_in_text
from source_cards import CITY_PROVINCE
from path_guard import safe_read_path, safe_write_path

TYPES = {"direct", "calculation", "negative", "inference", "external", "interpretation"}
NATIONAL = {"全国", "国家", "中国", ""}
SECONDARY = {"次级媒体", "次级媒体/未知", "未知"}
SOURCE_NATURES = {"政府网站", "官方媒体", "次级媒体", "未知", "次级媒体/未知"}
QUALIFIERS = ("通常", "一般", "原则上", "以属地", "以当地", "以主管", "以认定为准", "视", "可能")
STRONG_TERMS = ("确有", "已经", "属于", "不存在", "全部", "一律", "一定", "已上调", "已执行", "已补发")


def _load(path: str, run: str | None = None) -> Any:
    return json.loads(safe_read_path(path, run).read_text(encoding="utf-8"))


def _items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("claims") or data.get("sources") or []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _source_text(source: Dict[str, Any]) -> str:
    spans = source.get("spans") or []
    if isinstance(spans, list):
        return "\n".join(str(x) for x in spans if x)
    return str(spans or "")


def _city_province(name: str) -> str:
    name = (name or "").strip()
    return CITY_PROVINCE.get(name, CITY_PROVINCE.get(name.rstrip("市"), ""))


def _same_jurisdiction(left: str, right: str) -> bool:
    left = (left or "").strip()
    right = (right or "").strip()
    if left in NATIONAL or right in NATIONAL:
        return True
    if left == right or left in right or right in left:
        return True
    # 省级来源 vs 市级问题：河北省 vs 石家庄市 → 同一辖区。
    for a, b in ((left, right), (right, left)):
        if a.endswith("省") and b.endswith("市"):
            return _city_province(b) == a
        if a.endswith("自治区") and b.endswith("市"):
            return _city_province(b) == a
    return False


CALC_TOOLS = ("calc_period.py", "calc_legal.py")
CALC_LEGAL_OUTPUTS = (
    "amount", "total", "additional", "normal_wage", "months_factor", "value", "wage_used",
)


def _decimal_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:  # noqa: BLE001
        return False


def _calc_legal_inputs(claim: Dict[str, Any]) -> Dict[str, Any]:
    if str(claim.get("mode") or "") == "custom":
        return {
            "inputs": claim.get("inputs") if isinstance(claim.get("inputs"), dict) else {},
            "formula": claim.get("formula"),
        }
    if isinstance(claim.get("inputs"), dict):
        return dict(claim["inputs"])
    keys = (
        "monthly_wage", "years", "months", "capped_wage", "cap_years",
        "daily_wage", "days", "paid_ratio", "base", "ratio", "multiple",
    )
    return {key: claim[key] for key in keys if claim.get(key) is not None}


def calc_legal_matches(claim: Dict[str, Any]) -> Tuple[bool, str]:
    mode = str(claim.get("mode") or "").strip()
    if not mode:
        return False, "calculation(calc_legal.py) 缺少 mode"
    inputs = _calc_legal_inputs(claim)
    if not inputs:
        return False, "calculation(calc_legal.py) 缺少 inputs"
    try:
        result = calc_legal.calculate(mode, inputs)
    except Exception as exc:  # noqa: BLE001
        return False, f"calc_legal.py 无法重算：{exc}"
    present = [key for key in CALC_LEGAL_OUTPUTS if claim.get(key) is not None]
    if not present:
        return False, "calculation(calc_legal.py) 必须写回工具结果（如 amount/months_factor）"
    for key in present:
        if not _decimal_equal(claim.get(key), result.get(key)):
            return False, f"{key} 台账={claim.get(key)}，工具={result.get(key)}"
    return True, ""


def _calc_matches(claim: Dict[str, Any], claim_map: Dict[str, Dict[str, Any]]) -> Tuple[bool, str]:
    if str(claim.get("tool") or "") == "calc_legal.py":
        return calc_legal_matches(claim)
    required = ("start", "end", "principal", "annual_rate")
    if not all(claim.get(k) for k in required):
        aggregate = claim.get("aggregate_of")
        if isinstance(aggregate, list) and aggregate:
            total = Decimal("0")
            for ref in aggregate:
                other = claim_map.get(str(ref))
                if not other or other.get("type") != "calculation":
                    return False, f"aggregate_of 引用无效：{ref}"
                try:
                    total += Decimal(str(other.get("interest") or "0"))
                except Exception:  # noqa: BLE001
                    return False, f"aggregate_of 引用缺少 interest：{ref}"
            if claim.get("interest") is not None:
                try:
                    if Decimal(str(claim["interest"])) != total:
                        return False, f"aggregate_of 合计={total}，claim.interest={claim['interest']}"
                except Exception:  # noqa: BLE001
                    return False, "aggregate_of 的 interest 不是有效金额"
            return True, ""
        return False, "calculation 缺少 start/end/principal/annual_rate，或 aggregate_of"
    try:
        args = type("Args", (), {
            "start": parse_date(str(claim["start"])),
            "end": parse_date(str(claim["end"])),
            "day_count": str(claim.get("convention") or "include-end"),
            "principal": parse_decimal(str(claim["principal"])),
            "rate": parse_rate(str(claim["annual_rate"])),
            "basis_days": int(claim.get("basis_days") or 365),
        })()
        result = calc_build_result(args)
    except Exception as exc:  # noqa: BLE001
        return False, f"无法重算：{exc}"
    for key in ("days", "interest"):
        if claim.get(key) is not None and str(claim.get(key)) != str(result.get(key)):
            return False, f"{key} 台账={claim.get(key)}，工具={result.get(key)}"
    return True, ""


def _norm_text(value: str) -> str:
    return re.sub(r"[\s*_`#]+", "", value or "")


def _anchors(claim: Dict[str, Any]) -> List[str]:
    value = claim.get("answer_anchor") or claim.get("answer_anchors") or []
    if isinstance(value, str):
        value = [value]
    return [str(x) for x in value if str(x).strip()] if isinstance(value, list) else []


def _answer_sentences(answer: str) -> List[str]:
    out: List[str] = []
    for raw in answer.splitlines():
        line = raw.strip()
        if not line or line.startswith(">") or line.startswith("#") or line.startswith("```"):
            continue
        for sent in re.split(r"(?<=[。！？；!?;])", line):
            sent = sent.strip()
            if sent:
                out.append(sent)
    return out


def verify(claims: List[Dict[str, Any]], sources: List[Dict[str, Any]],
           profile: Dict[str, Any], answer: str = "") -> Dict[str, Any]:
    source_map = {str(s.get("id")): s for s in sources}
    claim_map = {str(c.get("id")): c for c in claims if c.get("id")}
    question_jurisdiction = str(profile.get("jurisdiction") or "").strip()
    issues: List[str] = []
    item_results: List[Dict[str, Any]] = []

    if not question_jurisdiction:
        issues.append("问题画像缺少 jurisdiction")
    if not claims:
        issues.append("没有结论台账（claims 为空）")

    for idx, claim in enumerate(claims, start=1):
        cid = str(claim.get("id") or f"c{idx}")
        ctype = str(claim.get("type") or "").strip()
        text = str(claim.get("text") or claim.get("claim") or "").strip()
        local: List[str] = []

        if ctype not in TYPES:
            local.append(f"type 非法：{ctype or '空'}")
        if not text:
            local.append("缺少 text/claim")
        anchors = _anchors(claim)
        if anchors and answer:
            if not any(_norm_text(a) in _norm_text(answer) for a in anchors):
                local.append("answer_anchor 未在答案中出现，答案没有落到这条 claim")

        source_ids = claim.get("source_ids") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        cited = [source_map[str(sid)] for sid in source_ids if str(sid) in source_map]
        if source_ids and not cited:
            local.append("source_ids 在材料画像中都不存在")
        for source in cited:
            if source.get("fetch_status") == "failed":
                local.append(f"来源 {source.get('id')} 抓取失败，不能作为依据")

        claim_jurisdiction = str(claim.get("jurisdiction") or "").strip()
        if not claim_jurisdiction and cited:
            claim_jurisdiction = str(cited[0].get("jurisdiction") or "")
        if ctype in ("direct", "external") and not claim_jurisdiction:
            local.append("缺少 jurisdiction，无法判断地域是否匹配")
        if claim_jurisdiction and not _same_jurisdiction(claim_jurisdiction, question_jurisdiction):
            local.append(f"claim 地域（{claim_jurisdiction}）与问题地域（{question_jurisdiction}）不一致")

        if ctype == "external":
            nature = str(claim.get("source_nature") or "").strip()
            source_jurisdiction = str(claim.get("jurisdiction") or (cited[0].get("jurisdiction") if cited else "")).strip()
            question_j = str(claim.get("question_jurisdiction") or question_jurisdiction).strip()
            if not nature:
                local.append("external 缺少 source_nature")
            elif nature not in SOURCE_NATURES:
                local.append(f"external source_nature 非法：{nature}")
            if not str(claim.get("as_of") or "").strip():
                local.append("external 缺少 as_of")
            if not source_ids and not claim.get("url") and not claim.get("source_ref") and not claim.get("official_value"):
                local.append("external 缺少来源引用（source_ids/url/source_ref）")
            if nature == "政府网站" and not source_ids and not claim.get("url"):
                local.append("政府网站来源缺少 source_ids/url，无法回查")
            if not source_jurisdiction or not question_j:
                local.append("external 缺少 jurisdiction / question_jurisdiction")
            elif not _same_jurisdiction(source_jurisdiction, question_j):
                local.append(f"来源地域（{source_jurisdiction}）与问题地域（{question_j}）不一致")
            if nature in SECONDARY and not (claim.get("official_value") or claim.get("wording")):
                local.append("次级媒体 external 缺少 official_value 或“待核验”措辞")
            value = str(claim.get("value") or "").strip()
            official_value = str(claim.get("official_value") or "").strip()
            wording = str(claim.get("wording") or "")
            if value and official_value and value not in official_value and official_value not in value:
                if not re.search(r"待核验|未见正式|以官方|官方口径", wording):
                    local.append("外部数值与官方口径不一致，但措辞未写“待核验/未见正式文件/官方口径”")
            mixed = claim.get("mixed_sources")
            if mixed:
                if isinstance(mixed, dict):
                    mixed_grades = set()
                    for sid, grade in mixed.items():
                        if str(sid) not in {str(x) for x in source_ids}:
                            local.append(f"mixed_sources 引用了未引用的来源：{sid}")
                        grade = str(grade or "")
                        if grade not in SOURCE_NATURES:
                            local.append(f"mixed_sources 的来源等级非法：{grade or '空'}")
                        mixed_grades.add(grade)
                    if nature not in SECONDARY and not any(g in SECONDARY for g in mixed_grades):
                        local.append("mixed_sources 没有任何次级媒体/未知来源，不能解释 claim 的来源等级")
                elif isinstance(mixed, str):
                    if not (re.search(r"次级媒体|未知|转引|转载", mixed) and re.search(r"政府网站|官方媒体", mixed)):
                        local.append("mixed_sources 必须同时说明政府网站/官方媒体与次级媒体/转引")
                else:
                    local.append("mixed_sources 必须是对象或说明字符串")

            for source in cited:
                if source.get("jurisdiction") and question_jurisdiction and not _same_jurisdiction(str(source["jurisdiction"]), question_jurisdiction):
                    local.append(f"来源 {source.get('id')} 地域（{source.get('jurisdiction')}）与问题不一致")
                if (
                    not source.get("jurisdiction")
                    and question_j not in NATIONAL
                    and claim_jurisdiction not in NATIONAL
                ):
                    local.append(f"来源 {source.get('id')} 地域未知，不能用于省级/地方问题")
                grade = str(source.get("source_grade") or "").strip()
                if grade in SECONDARY and nature not in SECONDARY and not claim.get("mixed_sources"):
                    local.append(
                        f"claim 标为“{nature}”，但来源 {source.get('id')} 是“{grade}”；请拆分或写 mixed_sources"
                    )

        if ctype == "direct":
            if not source_ids:
                local.append("direct 缺少 source_ids")
            quote = str(claim.get("quote") or "")
            if not quote:
                local.append("direct 缺少 quote")
            elif cited:
                if not any(quote_in_text(quote, _source_text(s)) for s in cited):
                    local.append("direct.quote 在来源 span 中找不到")
            count = claim.get("count")
            if count is not None:
                try:
                    expected = int(count)
                except (TypeError, ValueError):
                    local.append("count 不是整数")
                else:
                    actual = count_enumerations(quote)
                    if actual != expected:
                        local.append(f"count 声称 {expected} 项，引文数出 {actual} 项")
            if cited and not all(
                s.get("official") or s.get("source_grade") in ("官方库", "政府网站")
                for s in cited
            ):
                local.append("direct 依据含次级媒体/未知来源，不能作为法律条文结论")

        elif ctype == "calculation":
            tool = str(claim.get("tool") or "").strip()
            if tool not in CALC_TOOLS:
                local.append("calculation 必须写 tool=calc_period.py 或 calc_legal.py")
            if tool == "calc_period.py":
                convention = str(claim.get("convention") or "").strip()
                if convention not in ("include-end", "exclude-end"):
                    local.append("calculation 必须写 convention=include-end/exclude-end")
            ok, msg = _calc_matches(claim, claim_map)
            if not ok:
                local.append(msg)

        elif ctype == "negative":
            if not str(claim.get("as_of") or "").strip():
                local.append("negative 缺少 as_of")
            if not str(claim.get("coverage") or "").strip():
                local.append("negative 缺少 coverage")
            if not str(claim.get("wording") or "").strip():
                local.append("negative 缺少 wording")

        elif ctype == "inference":
            if not str(claim.get("wording") or "").strip():
                local.append("inference 缺少限定 wording")
            if answer and text in answer and not any(q in answer for q in QUALIFIERS):
                local.append("答案里的 inference 结论没有限定词")

        elif ctype == "interpretation":
            if not str(claim.get("primary") or "").strip() or not str(claim.get("alternative") or "").strip():
                local.append("interpretation 必须同时写 primary 和 alternative")
            if not str(claim.get("selected_reason") or "").strip():
                local.append("interpretation 缺少 selected_reason")

        item_results.append({"id": cid, "type": ctype, "verdict": "fail" if local else "pass", "issues": local})
        issues.extend(f"{cid}：{x}" for x in local)

    # 答案层通用措辞：否定结论必须有截止日期和检索覆盖。
    if answer:
        for lineno, line in enumerate(answer.splitlines(), 1):
            if line.strip().startswith(">") or not line.strip():
                continue
            if re.search(r"未上调|未再上调|未发生|不存在", line):
                if not (re.search(r"截至\s*\d{4}-\d{2}-\d{2}", line) and re.search(r"公开渠道未见|未检索到|未见", line)):
                    issues.append(f"答案第 {lineno} 行：否定结论缺少“截至YYYY-MM-DD，公开渠道未见”")

        # 句子 -> claim：强断言必须有 answer_anchor 或引用角标。
        anchors_all: List[str] = []
        claim_texts: List[str] = []
        for claim in claims:
            anchors_all.extend(_norm_text(a) for a in _anchors(claim))
            claim_texts.append(_norm_text(str(claim.get("text") or claim.get("claim") or "")))
        for sent in _answer_sentences(answer):
            if not any(term in sent for term in STRONG_TERMS):
                continue
            if re.search(r"\[\d+\]", sent):
                continue
            norm = _norm_text(sent)
            if any(a and a in norm for a in anchors_all):
                continue
            if any(t and t in norm for t in claim_texts if len(t) >= 8):
                continue
            issues.append(f"答案强断言没有 claim 锚点/引用：{sent[:80]}")

    return {"verdict": "pass" if not issues else "fail", "issues": issues, "items": item_results}


def main() -> int:
    parser = argparse.ArgumentParser(description="问题画像 + 材料画像 + claim 通用校验")
    parser.add_argument("--claims", required=True)
    parser.add_argument("--sources", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--answer", default="", help="最终答案文件（run 目录内）；渲染报告前必须传，用于写入核验记录指纹")
    parser.add_argument("--output", default="legal_verify.json", help="输出文件名（落到 --run 目录）")
    parser.add_argument("--run", help="会话 run 目录（也可用环境变量 DKNOWC_RUN_DIR）")
    args = parser.parse_args()

    try:
        claims = _items(_load(args.claims, args.run))
        sources = _items(_load(args.sources, args.run))
        profile = _load(args.profile, args.run)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"输入不可读：{exc}", file=sys.stderr)
        return 1
    try:
        answer = safe_read_path(args.answer, args.run).read_text(encoding="utf-8") if args.answer else ""
    except (OSError, ValueError) as exc:
        print(f"答案不可读：{exc}", file=sys.stderr)
        return 1
    result = verify(claims, sources, profile, answer)
    # 核验记录指纹：绑定核验当时的答案与证据；渲染侧据此检测“核验后改答案/补查后旧报告”。
    from datetime import datetime
    result["record"] = {
        # 与渲染侧对齐（上游内核 extract_answer 会 strip 首尾空白）：指纹一律按去首尾空白后的答案计算
        "answer_digest": trust_digest.answer_digest(answer.strip()) if answer else "",
        "evidence_digest": trust_digest.evidence_digest(sources),
        "verdict": result.get("verdict"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        out = safe_write_path(args.output, args.run)
    except ValueError as exc:
        parser.error(str(exc))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
