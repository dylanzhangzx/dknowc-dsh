#!/usr/bin/env python3
"""交付前措辞检查：抓"无条件结论"和未注明的事实假设（税务版）。

不是词表检查——同义改写也要抓。引用块（Markdown `>` 行）和代码块不扫描，
政策原文里的"全部/一律"不算。命中项须改写，或在 tax_selfcheck.json 的
absolute_review 中按行号逐条说明理由。

税务版在法律版基础上增加：
- 税率/征收率/扣除标准必须带适用年度或政策依据；
- 滞纳金计算要写清情形（未按期缴纳 vs 偷税抗税）与口径；
- 社保缴费基数上下限、地方口径检查；
- 纳税人身份（小规模/一般纳税人/居民/non-resident）未确认不得当已确认。

用法：
  python3 scripts/check_answer.py \
    --answer ./runs/<任务>-<时间>/tax_answer.txt \
    --selfcheck ./runs/<任务>-<时间>/tax_selfcheck.json

不要写成 `... | tail -30; echo $?`——那样拿到的是 tail 的退出码，不是本脚本的。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# (词, 反问, 同一行出现这些词时视为已限定)
# 税率/扣除标准的"已限定"词：适用年度（任意 20xx 年）或年度/依据字样
YEAR_WORDS = tuple(str(y) for y in range(2018, 2028))

RULES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("只能", "政策是否真的只允许这一种处理？是否有其他申报/减免路径？", ()),
    ("唯一", "是否穷尽了所有情形？能否给出反例？", ()),
    ("一定", "是否存在例外？政策文件有没有限定条件？", ()),
    ("必然", "是否只是通常结果？有没有缓缴、补正、备案的空间？", ()),
    ("全部", "是否封闭列举？会不会漏掉未列举税目/情形？", ()),
    ("一律", "是否所有纳税人/情形都适用？有没有例外规定？", ()),
    ("均可", "主体/情形是否穷尽？小规模与一般纳税人口径一致吗？", ()),
    ("都能", "主体/情形是否穷尽？有没有被排除的对象？", ()),
    ("一旦", "条件句是否把可能后果写成了必然结果？", ()),
    ("就构成", "是否当然构成偷税/抗税？能否陈述申辩、补正？", ()),
    ("税率", "税率/征收率是否注明适用年度与政策依据（公告文号）？", ("年度",) + YEAR_WORDS),
    ("征收率", "征收率是否注明适用年度与政策依据？小规模与一般纳税人口径不同。", ("年度",) + YEAR_WORDS),
    ("速算扣除", "速算扣除数是否标明年度税率表？不同年度数值不同。", ("年度",) + YEAR_WORDS),
    ("扣除标准", "专项附加扣除标准按年度调整（2023 年起子女教育每月 2000 元）；是否标明年度与依据？", ("年度",) + YEAR_WORDS),
    ("起征点", "起征点与免税标准是两个口径；是否写明适用主体（小规模/个人）与年度？", ("年度",) + YEAR_WORDS),
    ("滞纳金", "滞纳金按日加收万分之五；是否写清起算日、截止日、情形（未按期缴纳 vs 偷税抗税）？",
     ("万分之五", "0.05%", "按日", "起算", "一日", "加收")),
    ("免征", "免征是否有销售额/身份/行业限定？小规模免征有月销售额标准线。",
     ("标准", "以下", "未超", "不超过", "限额", "内", "其中")),
    ("缴费基数", "社保/公积金缴费基数受当地上下限约束（常见 60%–300%），不是简单按实际工资；有当地依据吗？",
     ("当地", "上下限", "60%", "300%", "以当地", "通常口径", "社保经办", "口径")),
    ("小型微利", "小型微利要同时满足资产/人数/应纳税所得额三项条件；是否三项都写了？",
     ("同时", "三项", "资产", "人数", "所得额")),
)

# 数值型规则：关键词本身不是问题，"给出具体数字但没出处"才是问题。
# 只对命中具体税率/金额的句子触发，避免"取决于税率档"这类假设句误报。
RATE_NUMBER_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*[%％]|百分之[一二三四五六七八九十百零〇\d]+|\d+\s*个点)"
)
NUMBER_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*[%％]|百分之[一二三四五六七八九十百零〇\d]+|\d+\s*个点|"
    r"\d[\d,，]*(?:\.\d+)?\s*(?:万)?元)"
)
NUMERIC_RULES = {
    "税率": RATE_NUMBER_RE,
    "征收率": RATE_NUMBER_RE,
    "速算扣除": NUMBER_RE,
    "扣除标准": NUMBER_RE,
    "起征点": NUMBER_RE,
}
# 已限定：文号、公告编号、文件全称。仅写年份不算出处（年份只证明时间）。
DOC_CONTEXT_RE = re.compile(
    r"(?:〔\d{4}〕|第\d+号|公告\s*\d{4}\s*年第\s*\d+\s*号|财税\s*〔|《[^》]{2,80}》)"
)
# 假设/试算语境：句中出现具体数字也不当作“在断言适用税率”。
HYPOTHETICAL_RE = re.compile(
    r"(?:假设|假定|假如|如果|若(?!干)|试算|举例|例如|比如|情景|按.{0,8}(?:测算|试算))"
)

# 句式级检查：条件 + 后果，防止把词换成同义词绕过。
CONSEQUENCE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"(一旦|只要).{0,50}(就|便|会).{0,30}(违法|无效|免税|征税|处罚|加收|滞纳金|不能|不予|没了|补税)",
     "条件句是否把可能后果写成必然？"),
    (r"(就|便|即).{0,8}(构成|属于|变成).{0,12}(偷税|漏税|违法|违规)",
     "是否把可争议的定性写成必然？"),
    (r"(会|将).{0,12}(一并|全部|自动|当然).{0,12}(免征|覆盖|加收|补缴|处罚)",
     "后果是否当然发生？"),
)


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
            if term in NUMERIC_RULES:
                # 数值型规则只在给出具体数字时触发；"税率档/税率表"等假设句不拦。
                # 年度用“2026年”这类上下文判断，避免把“2000元”里的 2000 当年份。
                triggered = (
                    term in line
                    and bool(NUMERIC_RULES[term].search(line))
                    and not DOC_CONTEXT_RE.search(line)
                    and not HYPOTHETICAL_RE.search(line)
                )
            else:
                triggered = term in line and not any(u in line for u in unless)
            if triggered:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="检查答案中的无条件结论与未注明的事实假设（税务版）")
    parser.add_argument("--answer", required=True, help="答案 Markdown/TXT 文件")
    parser.add_argument("--selfcheck", help="tax_selfcheck.json（含 absolute_review）")
    args = parser.parse_args()

    answer_path = Path(args.answer)
    if not answer_path.is_file():
        print(f"答案文件不存在：{answer_path}", file=sys.stderr)
        return 2

    findings = scan(answer_path.read_text(encoding="utf-8"))
    if not findings:
        print("措辞检查通过：未发现无条件结论或未注明的事实假设")
        return 0

    review, review_loaded = (None, False)
    if args.selfcheck:
        review, review_loaded = load_review(Path(args.selfcheck))

    uncovered: List[Dict[str, str]] = []
    print(f"发现 {len(findings)} 处需要复核的表述：", flush=True)
    for item in findings:
        print(f"  第 {item['line']} 行「{item['term']}」：{item['question']}", flush=True)
        print(f"    {item['text'][:180]}", flush=True)
        if not covered(item, review):
            uncovered.append(item)

    if uncovered:
        if not review_loaded and args.selfcheck:
            hint = "自检文件不可读，未做复核匹配。"
        elif isinstance(review, dict):
            hint = "absolute_review 是对象时，每个命中行号都要有键。"
        else:
            hint = "absolute_review 建议改为按行号的对象，逐条说明；字符串只做词面匹配。"
        print(
            f"\n未在 absolute_review 中说明的有 {len(uncovered)} 处。{hint}\n"
            "优先改写为带条件/例外/年度的表述；确属事实描述或政策封闭列举的，再逐条说明理由。",
            file=sys.stderr,
        )
        return 1

    print("\n以上表述已在 absolute_review 中逐条说明，可继续生成报告")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
