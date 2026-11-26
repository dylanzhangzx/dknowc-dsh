#!/usr/bin/env python3
"""交付前检查：措辞 + 结论台账。

措辞：抓“无条件法律后果”和未注明的事实假设；不是词表检查，同义改写也要抓。
结论台账：`--claims` 传入 legal_claims.json，检查
- direct 的 count 与 quote 枚举数是否一致、quote 是否在材料里；
- negative 是否有 as_of/coverage/wording，答案是否写成“未上调/未发生”；
- inference 是否带“通常/以属地……认定为准”；
- calculation 是否带 tool/convention，答案是否写明天数口径。
引用块（Markdown `>` 行）和代码块不扫描；命中项须改写，或在
legal_selfcheck.json 的 absolute_review 中按行号逐条说明理由。台账问题不能靠
absolute_review 放行。

用法：
  python3 scripts/check_answer.py \
    --answer official-docs/search-results/legal_answer.txt \
    --selfcheck official-docs/search-results/legal_selfcheck.json \
    --claims official-docs/search-results/legal_claims.json \
    --materials official-docs/search-results/legal_search.json

不要写成 `... | tail -30; echo $?`——那样拿到的是 tail 的退出码，不是本脚本的。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# (词, 反问, 同一行出现这些词时视为已限定)
RULES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("只能", "法条是否真的只允许这一种路径？是否有其他解除/救济方式？", ()),
    ("唯一", "是否穷尽了所有情形？能否给出反例？", ()),
    ("一定", "是否存在例外？条文有没有限定条件？", ()),
    ("必然", "是否只是通常结果？有没有可补正、可抗辩的空间？", ()),
    ("全部", "是否封闭列举？会不会漏掉未列举项？", ()),
    ("一律", "是否所有情形都适用？有没有例外规定？", ()),
    ("立刻", "法律后果是否即时发生？是否需经认定/裁决？", ()),
    ("马上", "法律后果是否即时发生？是否需经认定/裁决？", ()),
    ("就构成", "程序瑕疵是否当然构成违法？能否补正？", ()),
    ("均可", "主体/情形是否穷尽？有没有被排除的对象？", ()),
    ("都能", "主体/情形是否穷尽？有没有被排除的对象？", ()),
    ("归零", "协议措辞是否当然导致权利消灭？举证责任如何分配？", ()),
    ("清零", "放弃条款是否当然有效？是否存在显失公平/无效情形？", ()),
    ("一旦", "条件句是否把可能后果写成了必然结果？", ()),
    ("就没了", "法律后果是否当然发生？有没有补正或救济空间？", ()),
    ("一并被覆盖", "放弃条款是否当然覆盖法定权利？", ()),
    ("性质变成违法解除", "程序/实体瑕疵是否当然构成违法解除？", ()),
    ("非因本人意愿", "协商解除是否由用人单位提出？员工提出的不属此列", ()),
    ("累计工作", "年休假按累计工作年限、不是本单位工龄；是否写明了假设？",
     ("假设", "估算", "若", "此前", "如无", "据你所述", "未提供", "以你",
      "自述", "年限档", "分档", "概念", "定义", "证明材料", "表头")),
    ("缴至", "社保缴至离职当月属实务口径；是否标注“按通常口径/以当地为准”？",
     ("通常口径", "实务", "按当地", "以当地", "一般")),
)

# 句式级检查：条件 + 后果，防止把词换成同义词绕过。
CONSEQUENCE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(一旦|只要).{0,50}(就|便|会).{0,30}(违法|无效|解除|赔偿|覆盖|丧失|消灭|不能|不予|没了)",
     "条件句是否把可能后果写成必然？"),
    (r"(就|便|即).{0,8}(构成|属于|变成).{0,12}(违法|无效)",
     "是否把可争议的定性写成必然？"),
    (r"(会|将).{0,12}(一并|全部|自动|当然).{0,12}(覆盖|消灭|丧失|清零|归零|解除)",
     "后果是否当然发生？"),
    (r"缴费基数.{0,10}(按|按照|以).{0,8}实际工资",
     "社保/公积金缴费基数受当地上下限约束（常见 60%–300%），不是简单按实际工资；有当地依据吗？"),
)


# ---------- 结论台账（claim ledger）检查 ----------

CLAIM_TYPES = {"direct", "calculation", "negative", "inference", "external"}
SOURCE_NATURES = {"政府网站", "官方媒体", "次级媒体", "未知", "次级媒体/未知"}

# 只抓“把检索结论写成事实”的高风险否定词；不抓“没有约定”这类合同事实。
NEGATIVE_TERMS = ("未上调", "未再上调", "未发生", "不存在", "未发布", "未出台", "没有上调", "没有调整")

# 推断结论必须带的限定语。
INFERENCE_QUALIFIERS = (
    "通常", "一般", "原则上", "以属地", "以当地", "以主管", "以……认定为准",
    "以认定为准", "视", "可能", "倾向于",
)

DAY_COUNT_QUALIFIERS = ("含首尾", "算头不算尾", "include-end", "exclude-end")

_ENUM_CN = re.compile(r"[（(]\s*([一二三四五六七八九十]+)\s*[）)]")
_ENUM_NUM = re.compile(r"(?m)^\s*(\d{1,2})[.、]\s*")
_ARTICLE_COUNT = re.compile(
    r"第(?P<article>[一二三四五六七八九十百零〇0-9]+)条"
    r"(?P<middle>[^。；\n]{0,40}?)"
    r"(?P<number>[一二三四五六七八九十]+)项"
    r"(?P<tail>[^，。；\n]{0,6})"
)
# 数量断言线索：只有这些语境才把“N项”当作总数，避免把“哪一项/第一项”误判。
_COUNT_CUES = ("共", "共计", "总计", "合计", "有", "为", "分为", "包括", "包含",
               "列举", "列明", "载明", "明确", "规定", "计", "履行", "承担",
               "享有", "负有", "设置", "设定", "配备", "罗列", "载有", "列有",
               "要求", "需要")
_COUNT_TAIL = ("职责", "义务", "情形", "条件", "事实", "规定", "要求", "内容",
               "权利", "措施", "行为", "事项", "标准", "步骤", "材料", "要件",
               "要素", "方式", "途径", "类型", "种类", "项目", "程序", "期限", "责任")
_SKIP_SUFFIX = tuple("第哪前后任某每逐同这那下上本该")
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_to_int(value: str) -> int:
    """把“六/七/十二/二十”这类中文数字转成整数；无法解析返回 0。"""
    text = (value or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(text, 0)


def _norm_ws(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def count_enumerations(quote: str) -> int:
    """数引文里的“（一）（二）……”或行首“1. 2.”枚举项。"""
    text = quote or ""
    cn = len({m.group(1) for m in _ENUM_CN.finditer(text)})
    nums = [int(m.group(1)) for m in _ENUM_NUM.finditer(text)]
    num = max(nums, default=0)
    return max(cn, num)


def quote_in_text(quote: str, text: str) -> bool:
    """引文比对：允许省略号，但省略号分隔的每一段都要能在材料里找到。"""
    q = _norm_ws(quote)
    t = _norm_ws(text)
    if not q:
        return True
    if not t:
        return False
    parts = [p for p in re.split(r"(?:……|\.{3,}|…+)", q) if len(p) >= 4]
    if len(parts) > 1:
        return all(p in t for p in parts)
    return q in t


def _collect_text(value: Any, out: List[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            # 只收正文类字段，避免把标题/元数据当原文。
            if key in ("内容", "正文", "text", "content", "摘录", "原文"):
                _collect_text(item, out)
            elif isinstance(item, (dict, list)):
                _collect_text(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_text(item, out)


def load_material_text(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    chunks: List[str] = []
    _collect_text(data, chunks)
    return "\n".join(chunks)


def load_claims(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("claims") or []
    if not isinstance(data, list):
        raise ValueError("claims 文件应为数组，或含 claims 数组的对象")
    return [item for item in data if isinstance(item, dict)]


def validate_claims(claims: List[Dict[str, Any]], material_text: str = "") -> List[str]:
    """检查台账本身：类型、枚举数量、引文是否存在、必填口径。"""
    import verify_claims  # 延迟导入：verify_claims 反向复用本模块的引文/计数函数

    issues: List[str] = []
    for idx, claim in enumerate(claims, start=1):
        cid = str(claim.get("id") or f"claims[{idx}]")
        ctype = str(claim.get("type") or "").strip()
        if ctype not in CLAIM_TYPES:
            issues.append(f"{cid}：type 必须是 {'/'.join(sorted(CLAIM_TYPES))}，当前为 {ctype or '空'}")
            continue
        quote = str(claim.get("quote") or "")
        if ctype == "direct":
            if not claim.get("source_ids"):
                issues.append(f"{cid}：direct 必须写 source_ids")
            count = claim.get("count")
            if count is not None:
                try:
                    expected = int(count)
                except (TypeError, ValueError):
                    issues.append(f"{cid}：count 必须是整数")
                else:
                    actual = count_enumerations(quote)
                    if actual != expected:
                        issues.append(
                            f"{cid}：声称 {expected} 项，引文实际数出 {actual} 项；先数原文再写数量"
                        )
            if quote and material_text and not quote_in_text(quote, material_text):
                issues.append(f"{cid}：quote 在材料原文中找不到；不得把概括句当原文")
        elif ctype == "negative":
            if not str(claim.get("as_of") or "").strip():
                issues.append(f"{cid}：negative 结论必须写 as_of（截至日期）")
            if not str(claim.get("coverage") or "").strip():
                issues.append(f"{cid}：negative 结论必须写 coverage（检索覆盖）")
            if not str(claim.get("wording") or "").strip():
                issues.append(f"{cid}：negative 结论必须写限定措辞 wording")
        elif ctype == "inference":
            if not str(claim.get("wording") or "").strip():
                issues.append(f"{cid}：inference 结论必须写限定措辞 wording")
        elif ctype == "external":
            nature = str(claim.get("source_nature") or "").strip()
            jurisdiction = str(claim.get("jurisdiction") or "").strip()
            question_jurisdiction = str(claim.get("question_jurisdiction") or "").strip()
            if not nature:
                issues.append(f"{cid}：external 结论必须写 source_nature（政府网站/官方媒体/次级媒体/未知）")
            elif nature not in SOURCE_NATURES:
                issues.append(f"{cid}：external source_nature 非法：{nature}")
            if not str(claim.get("as_of") or "").strip():
                issues.append(f"{cid}：external 结论必须写 as_of（截至日期）")
            if not jurisdiction or not question_jurisdiction:
                issues.append(f"{cid}：external 结论必须写 jurisdiction（来源地域）和 question_jurisdiction（问题地域）")
            elif jurisdiction != question_jurisdiction and jurisdiction not in ("全国", "国家") and question_jurisdiction not in ("全国", "国家"):
                issues.append(f"{cid}：来源地域（{jurisdiction}）与问题地域（{question_jurisdiction}）不一致；不得用外省材料回答本省问题")
            if nature in ("次级媒体", "次级媒体/未知", "未知"):
                if not str(claim.get("official_value") or "").strip() and not str(claim.get("wording") or "").strip():
                    issues.append(f"{cid}：只有次级媒体来源时，必须写 official_value 或“待核验”措辞")
        elif ctype == "calculation":
            tool = str(claim.get("tool") or "").strip()
            if tool not in verify_claims.CALC_TOOLS:
                issues.append(f"{cid}：calculation 必须写 tool（calc_period.py 或 calc_legal.py）")
            elif tool == "calc_legal.py":
                ok, msg = verify_claims.calc_legal_matches(claim)
                if not ok:
                    issues.append(f"{cid}：{msg}")
            else:
                if not str(claim.get("convention") or "").strip():
                    issues.append(f"{cid}：calculation 必须写 convention（include-end/exclude-end）")
                required = ("start", "end", "principal", "annual_rate")
                if not all(claim.get(k) for k in required) and not claim.get("aggregate_of"):
                    issues.append(f"{cid}：calculation 必须写 start/end/principal/annual_rate，或 aggregate_of")
    return issues


def _is_count_assertion(middle: str, tail: str) -> bool:
    """判断“第X条……N项”是在说总数，还是在说“第N项/哪一项”。

    计数断言：共三项、规定三项、有三项、三项职责、三项。
    非计数：第一项、哪一项、前一项、任一项、某一项、每一项、该项、其中一项。
    """
    middle = middle or ""
    tail = tail or ""
    stripped = middle.strip()
    if stripped.endswith(_SKIP_SUFFIX):
        return False
    if "其中" in stripped or "任何" in stripped:
        return False
    if not stripped:
        return True
    # “第四十条的三项”“第一款的三项”：结构助词“的”后接数量，是总数。
    if stripped.endswith("的"):
        return True
    if any(cue in stripped for cue in _COUNT_CUES):
        return True
    return any(noun in tail for noun in _COUNT_TAIL)


def scan_article_counts(answer: str, claims: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """答案里的“第X条共N项/规定N项”必须与台账中的 direct.count 对得上。

    只校验总数断言；“第一项/哪一项/前一项”等指代或疑问不算数量结论。
    """
    findings: List[Dict[str, str]] = []
    for lineno, raw in enumerate(answer.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(">") or line.startswith("```"):
            continue
        for match in _ARTICLE_COUNT.finditer(line):
            article = match.group("article")
            number_text = match.group("number")
            if not _is_count_assertion(match.group("middle"), match.group("tail")):
                continue
            stated = cn_to_int(number_text)
            if stated <= 0:
                continue
            related = [
                c for c in claims
                if str(c.get("type") or "") == "direct"
                and c.get("count") is not None
                and f"第{article}条" in str(c.get("text") or c.get("claim") or "")
            ]
            if not related:
                findings.append(
                    {
                        "line": str(lineno),
                        "term": f"第{article}条{number_text}项",
                        "question": "这条数量结论没有进 claim 台账；先登记 direct.count 和引文，再写数量",
                        "text": line,
                    }
                )
                continue
            expected = int(related[0].get("count"))
            if stated != expected:
                findings.append(
                    {
                        "line": str(lineno),
                        "term": f"第{article}条{number_text}项",
                        "question": f"答案写 {stated} 项，台账写 {expected} 项；按原文逐项数",
                        "text": line,
                    }
                )
    return findings


def scan_claim_phrases(answer: str, claims: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """检查答案措辞是否越过 claim 类型允许的边界。"""
    findings: List[Dict[str, str]] = []
    lines = answer.splitlines()
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith(">") or line.startswith("```"):
            continue
        if any(term in line for term in NEGATIVE_TERMS):
            # 条件句/合同条款里的“未发生”不是检索结论，跳过。
            if re.match(r"^(如果|若|假如|倘若|是否|约定|合同|条款|条件)", line):
                continue
            if re.search(r"(如果|若|是否|约定).{0,20}未发生", line):
                continue
            window = line + " " + (lines[lineno - 2].strip() if lineno >= 2 else "")
            if not (
                re.search(r"截至\s*\d{4}-\d{2}-\d{2}", window)
                and re.search(r"(公开渠道未见|未检索到|未见)", window)
            ):
                findings.append(
                    {
                        "line": str(lineno),
                        "term": next(t for t in NEGATIVE_TERMS if t in line),
                        "question": "“没检索到”只能写成“截至YYYY-MM-DD，公开渠道未见……”；不能写成“未上调/未发生/不存在”",
                        "text": line,
                    }
                )
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith(">") or line.startswith("```"):
            continue
        # 民间借贷跨期高频陷阱：第三十一条第二款是特别条款，2020-08-20
        # 之后那一段按“起诉时”LPR；不得用第二十五条“合同成立时”改写。
        if "第二段" in line and "合同成立时" in line and "LPR" in line:
            findings.append(
                {
                    "line": str(lineno),
                    "term": "第二段按合同成立时LPR",
                    "question": "本 skill 采用第三十一条第二款“起诉时”LPR 口径；如采用合同成立时口径，必须标明是另一种裁判观点并并列 12%，不能作为唯一结论",
                    "text": line,
                }
            )
    for claim in claims:
        if str(claim.get("type") or "") != "inference":
            continue
        text = str(claim.get("text") or claim.get("claim") or "").strip()
        if text and text in answer and not any(q in answer for q in INFERENCE_QUALIFIERS):
            findings.append(
                {
                    "line": "",
                    "term": text[:20],
                    "question": "推断结论必须带“通常/一般/以属地……认定为准”，不能写成“属于/就是”",
                    "text": text,
                }
            )
    if re.search(r"\d{4}-\d{2}-\d{2}", answer) and "天" in answer and ("利息" in answer or "期间" in answer):
        if not any(q in answer for q in DAY_COUNT_QUALIFIERS):
            findings.append(
                {
                    "line": "",
                    "term": "天数口径",
                    "question": "答案含日期区间/天数，但未写明“含首尾”或“算头不算尾”",
                    "text": "请在算例表头或首句写明天数口径",
                }
            )
    return findings


def scan(answer: str) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    seen: set = set()
    in_fence = False
    for lineno, raw in enumerate(answer.splitlines(), 1):
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or line.startswith(">"):
            continue
        for term, question, unless in RULES:
            if term in line and not any(u in line for u in unless):
                key = (lineno, term)
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "line": str(lineno),
                        "term": term,
                        "question": question,
                        "text": line,
                    })
        for pattern, question in CONSEQUENCE_PATTERNS:
            match = re.search(pattern, line)
            if match:
                term = match.group(0)[:12]
                key = (lineno, term)
                if key not in seen:
                    seen.add(key)
                    findings.append({
                        "line": str(lineno),
                        "term": term,
                        "question": question,
                        "text": line,
                    })
    return findings


def load_review(path: Path) -> Tuple[object, bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"无法读取自检文件：{exc}", file=sys.stderr)
        return None, False
    return data.get("absolute_review"), True


def covered(item: Dict[str, str], review: object) -> bool:
    if isinstance(review, dict):
        return str(item["line"]) in review
    if isinstance(review, str):
        return item["term"] in review
    return False


# 可回查要素（1.0.4 两轨自验收，与 render_trace_html 共用）：
# 材料编号、条款号、文号、日期、标准号——任一项即可回查。
CHECKABLE_PATTERNS = (
    re.compile(r"\[\d+\]"),
    re.compile(r"第[一二三四五六七八九十百零〇\d]+条"),
    re.compile(r"§\s*\d+"),
    re.compile(r"〔\s*20\d{2}\s*〕"),
    re.compile(r"（\s*20\d{2}\s*）"),
    re.compile(r"20\d{2}\s*[-/.年]\s*\d{1,2}"),
    re.compile(r"20\d{2}\s*年"),
    re.compile(r"[A-Za-z0-9_./-]+\.(?:json|txt|md|html|csv)", re.I),
    re.compile(r"GB(?:/T)?\s*\d+", re.I),
    re.compile(r"法释〔\s*20\d{2}\s*〕\s*\d+号"),
)


def has_checkable_element(text: Any) -> bool:
    """证据里是否至少有一处可回查的要素（编号/条款/文号/日期/标准号）。"""
    value = str(text or "")
    return any(pattern.search(value) for pattern in CHECKABLE_PATTERNS)


SELF_CHECK_KEYS = (
    ("fact_basis", "事实有据"),
    ("binding", "角标绑定"),
    ("consistency", "答案一致"),
    ("freshness", "时效确认"),
    ("no_gap", "无未核验断言"),
)
SELF_CHECK_PASS_PREFIXES = ("通过", "已通过", "合格", "pass", "true", "ok")
SELF_CHECK_FAIL_PREFIXES = ("未通过", "不通过", "不合格", "fail", "false")


def validate_selfcheck(path: Path) -> List[str]:
    """五项自检校验（1.0.4 两轨自验收契约）。

    结构化写法：{"verdict": "pass|fail|pending", "basis", "evidence":[…]}；
    旧字符串写法（“通过/未通过：原因”）兼容。声明"通过"必须带可回查证据，
    否则渲染器按 evidence_missing 拦截、不出报告。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"自检文件不可读：{exc}"]
    if not isinstance(data, dict):
        return ["自检文件不是 JSON 对象"]
    issues: List[str] = []
    for key, label in SELF_CHECK_KEYS:
        if key not in data:
            issues.append(f"缺少 {key}（{label}）")
            continue
        value = data.get(key)
        if isinstance(value, dict):
            verdict = str(value.get("verdict") or "").strip().lower()
            if verdict not in ("pass", "fail", "pending"):
                issues.append(f"{key}（{label}）verdict 必须是 pass/fail/pending")
                continue
            if verdict != "pass":
                continue
            evidence = value.get("evidence")
            if isinstance(evidence, (list, tuple)):
                ev_bits = [str(x) for x in evidence if str(x).strip()]
            elif str(evidence or "").strip():
                ev_bits = [str(evidence).strip()]
            else:
                ev_bits = []
            basis = str(value.get("basis") or "").strip()
            if not ev_bits and basis:
                ev_bits = [basis]
            joined = "；".join(ev_bits)
            if not joined.strip() or not has_checkable_element(joined):
                issues.append(f"{key}（{label}）声明通过但证据无可回查要素"
                              "（材料编号/条款号/文号/日期/标准号任一），渲染器会拦截")
            continue
        text = str(value or "").strip()
        if not text.startswith(SELF_CHECK_PASS_PREFIXES + SELF_CHECK_FAIL_PREFIXES):
            issues.append(f"{key}（{label}）没有以“通过/未通过”开头，报告会显示“未记录”")
    return issues


# 隐私红线（律所客户反馈 2026-11-25）：交付答案里不得出现未脱敏的身份证号/手机号。
# 案号（(2025)京01民终123号）、金额、日期不在此列；脱敏格式（手机号前3位+星号+后4位、身份证前6位+星号）放行。
_ID_RE = re.compile(r"(?<![0-9Xx])\d{17}[0-9Xx](?![0-9Xx])")
_MOBILE_RE = re.compile(r"(?<![0-9])1[3-9]\d{9}(?![0-9])")
_MASKED_OK_RE = re.compile(r"[0-9*]{3}\*{3,}[0-9*]{0,4}")


def scan_privacy(answer: str) -> List[Dict[str, str]]:
    """扫描未脱敏的身份证号与手机号；属隐私硬错误，不能用 absolute_review 放行。"""
    findings: List[Dict[str, str]] = []
    lines = answer.split("\n")
    for idx, line in enumerate(lines, 1):
        for m in _ID_RE.finditer(line):
            findings.append({
                "line": str(idx),
                "term": m.group(0)[:6] + "********",
                "text": line,
                "question": "疑似未脱敏的 18 位身份证号：答案与产物必须脱敏（如 前6位+****），请删改",
            })
        for m in _MOBILE_RE.finditer(line):
            span = line[max(0, m.start() - 2):m.end() + 2]
            if _MASKED_OK_RE.search(span):
                continue
            # 金额/编号常被连续数字误中：排除紧跟"元/号/年度"等上下文
            if re.search(r"[0-9][万亿]|[万亿]\s*$|编号|案号|第\s*\d+", line[max(0, m.start() - 12):m.end() + 4]):
                continue
            findings.append({
                "line": str(idx),
                "term": m.group(0)[:3] + "****" + m.group(0)[-2:],
                "text": line,
                "question": "疑似未脱敏的 11 位手机号：请改为「前3位+星号+后4位」的脱敏形式或删除",
            })
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="检查答案中的无条件法律后果与事实假设")
    parser.add_argument("--answer", required=True, help="答案 Markdown/TXT 文件")
    parser.add_argument("--selfcheck", help="legal_selfcheck.json（含 absolute_review）")
    parser.add_argument("--claims", help="legal_claims.json（结论台账，含 type/quote/count/as_of）")
    parser.add_argument("--materials", help="检索结果 JSON，用于校验 claim quote 是否在原文中")
    args = parser.parse_args()

    if args.selfcheck:
        issues = validate_selfcheck(Path(args.selfcheck))
        if issues:
            print("自检五项格式不合格：", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            print("请把五项值写成“通过：原因”或“未通过：原因”后再生成报告。", file=sys.stderr)
            return 1

    answer_path = Path(args.answer)
    if not answer_path.is_file():
        print(f"答案文件不存在：{answer_path}", file=sys.stderr)
        return 2
    answer = answer_path.read_text(encoding="utf-8")

    claims: List[Dict[str, Any]] = []
    claim_issues: List[str] = []
    claim_findings: List[Dict[str, str]] = []
    if args.claims:
        try:
            claims = load_claims(Path(args.claims))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"结论台账不可读：{exc}", file=sys.stderr)
            return 1
        material_text = ""
        if args.materials:
            try:
                material_text = load_material_text(Path(args.materials))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"材料文件不可读：{exc}", file=sys.stderr)
                return 1
        claim_issues = validate_claims(claims, material_text)
        claim_findings = scan_article_counts(answer, claims) + scan_claim_phrases(answer, claims)

    if claim_issues:
        print("结论台账不合格：", file=sys.stderr)
        for issue in claim_issues:
            print(f"  - {issue}", file=sys.stderr)

    wording_findings = scan(answer)
    privacy_findings = scan_privacy(answer)
    findings = wording_findings + claim_findings + privacy_findings
    # 隐私发现与台账发现同级：硬错误，不能用 absolute_review 放行
    privacy_keys = {id(item) for item in privacy_findings}
    if not findings and not claim_issues:
        print("措辞检查通过：未发现无条件法律后果、未注明的事实假设或越界的结论措辞")
        return 0

    review, review_loaded = (None, False)
    if args.selfcheck:
        review, review_loaded = load_review(Path(args.selfcheck))

    # claim_findings 是台账级硬错误，不允许用 absolute_review 放行；
    # 只有措辞类 findings 可以按行号解释。
    claim_keys = {id(item) for item in claim_findings}
    uncovered: List[Dict[str, str]] = []
    if findings:
        print(f"发现 {len(findings)} 处需要复核的表述：", flush=True)
        for item in findings:
            print(f"  第 {item['line']} 行「{item['term']}」：{item['question']}", flush=True)
            print(f"    {item['text'][:180]}", flush=True)
            if id(item) in claim_keys or id(item) in privacy_keys or not covered(item, review):
                uncovered.append(item)

    if claim_issues or uncovered:
        if uncovered:
            hard_claim = any(id(item) in claim_keys or id(item) in privacy_keys
                             for item in uncovered)
            if hard_claim:
                hint = "其中包含结论台账/数量类硬错误，不能用 absolute_review 放行。"
            elif not review_loaded and args.selfcheck:
                hint = "自检文件不可读，未做复核匹配。"
            elif isinstance(review, dict):
                hint = "absolute_review 是对象时，每个命中行号都要有键。"
            else:
                hint = "absolute_review 建议改为按行号的对象，逐条说明；字符串只做词面匹配。"
            print(
                f"\n未通过的有 {len(uncovered)} 处。{hint}\n"
                "优先改写为带条件/例外的表述；确属事实描述或条文封闭列举的，再逐条说明理由。",
                file=sys.stderr,
            )
        if claim_issues:
            print("\n结论台账问题必须先修：数量按原文数、否定结论带截止日期、推断结论带限定语、计算写口径。",
                  file=sys.stderr)
        return 1

    print("\n以上表述已在 absolute_review 中逐条说明，可继续生成报告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
