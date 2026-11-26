#!/usr/bin/env python3
"""税务计算器（交付前唯一税额/滞纳金计算入口）。

不让模型心算金额；把口径写进输出，报告与 claim 台账直接引用。

支持四种模式：
1. late-fee（税款滞纳金）：本金 × 日万分之几 × 天数，必须显式选择
   include-end（含首尾）或 exclude-end（算头不算尾）。
2. tax-exclusive（不含税基数算税）：计税依据 × 税率。
3. tax-inclusive（含税金额价税分离）：含税金额 ÷ (1+税率) 得不含税销售额，
   税额 = 含税金额 − 不含税销售额。
4. reduction（减免额）：应纳税额 × 减免比例。

税率写法：`13%` 或 `0.13`；日滞纳金率默认 `0.05%`（万分之五）。
金额一律 Decimal 计算，四舍五入到分。

用法：
  python3 scripts/calc_tax.py --mode late-fee \
    --principal 200000 --daily-rate 0.05% \
    --start 2026-01-01 --end 2026-02-09 --day-count include-end

  python3 scripts/calc_tax.py --mode tax-exclusive --base 100000 --rate 1%
  python3 scripts/calc_tax.py --mode tax-inclusive --amount 103000 --rate 1%
  python3 scripts/calc_tax.py --mode reduction --tax 10000 --reduction 50%

输出 JSON（late-fee 示例）：
{
  "mode": "late-fee",
  "start": "2026-01-01", "end": "2026-02-09",
  "day_count": "include-end", "days": 40,
  "principal": "200000", "daily_rate": "0.0005",
  "amount": "4000.00",
  "formula": "200000 × 0.05% × 40"
}
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Optional

from calc_period import days_between, money, parse_date, parse_decimal, parse_rate

MODES = ("late-fee", "tax-exclusive", "tax-inclusive", "reduction")


def parse_ratio(value: str) -> Decimal:
    """比例解析：50% → 0.5；0.5 → 0.5；范围 0–1。"""
    text = (value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("比例不能为空")
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        ratio = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"不是有效比例：{value}") from exc
    if percent:
        ratio = ratio / Decimal("100")
    if ratio < 0 or ratio > 1:
        raise argparse.ArgumentTypeError("比例必须在 0 到 1 之间（或写 50%）")
    return ratio


def _round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(rate: Decimal) -> str:
    return f"{(rate * 100).normalize():f}%"


def _infer_mode(args: argparse.Namespace) -> str:
    if args.mode:
        return args.mode
    if args.principal is not None and args.start and args.end:
        return "late-fee"
    if args.amount is not None:
        return "tax-inclusive"
    if args.base is not None:
        return "tax-exclusive"
    if args.tax is not None and args.reduction is not None:
        return "reduction"
    return ""


def build_result(args: argparse.Namespace) -> Dict[str, Any]:
    mode = _infer_mode(args)
    if mode not in MODES:
        raise ValueError("无法判断计算模式：请显式传 --mode")
    if mode == "late-fee":
        if not (args.start and args.end and args.day_count):
            raise ValueError("late-fee 需要 --start/--end/--day-count")
        if args.principal is None:
            raise ValueError("late-fee 需要 --principal")
        daily_rate = args.daily_rate if args.daily_rate is not None else Decimal("0.0005")
        days = days_between(args.start, args.end, args.day_count)
        amount = _round(args.principal * daily_rate * Decimal(days))
        rate_text = _pct(daily_rate)
        return {
            "mode": "late-fee",
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "day_count": args.day_count,
            "days": days,
            "principal": str(args.principal),
            "daily_rate": str(daily_rate),
            "amount": money(amount),
            "formula": f"{args.principal} × {rate_text} × {days}",
        }
    if mode == "tax-exclusive":
        if args.base is None or args.rate is None:
            raise ValueError("tax-exclusive 需要 --base 与 --rate")
        tax = _round(args.base * args.rate)
        return {
            "mode": "tax-exclusive",
            "base": str(args.base),
            "rate": str(args.rate),
            "tax": money(tax),
            "total": money(args.base + tax),
            "formula": f"{args.base} × {_pct(args.rate)}",
        }
    if mode == "tax-inclusive":
        if args.amount is None or args.rate is None:
            raise ValueError("tax-inclusive 需要 --amount 与 --rate")
        base = _round(args.amount / (Decimal("1") + args.rate))
        tax = args.amount - base
        return {
            "mode": "tax-inclusive",
            "amount": str(args.amount),
            "rate": str(args.rate),
            "base": money(base),
            "tax": money(tax),
            "formula": f"{args.amount} ÷ (1+{_pct(args.rate)}) × {_pct(args.rate)}",
        }
    # reduction
    if args.tax is None or args.reduction is None:
        raise ValueError("reduction 需要 --tax 与 --reduction")
    relief = _round(args.tax * args.reduction)
    return {
        "mode": "reduction",
        "tax": str(args.tax),
        "reduction_rate": str(args.reduction),
        "relief": money(relief),
        "payable": money(args.tax - relief),
        "formula": f"{args.tax} × {_pct(args.reduction)}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="税务计算器（滞纳金/税额/价税分离/减免额）")
    parser.add_argument("--mode", choices=MODES, help="计算模式；不传则按参数推断")
    parser.add_argument("--start", type=parse_date, help="起始日 YYYY-MM-DD（滞纳金）")
    parser.add_argument("--end", type=parse_date, help="截止日 YYYY-MM-DD（滞纳金）")
    parser.add_argument("--day-count", choices=("include-end", "exclude-end"),
                        help="include-end=含首尾；exclude-end=算头不算尾")
    parser.add_argument("--principal", type=parse_decimal, help="欠缴税款本金")
    parser.add_argument("--daily-rate", type=parse_rate,
                        help="日滞纳金率，默认 0.05%%")
    parser.add_argument("--base", type=parse_decimal, help="不含税计税依据")
    parser.add_argument("--amount", type=parse_decimal, help="含税金额")
    parser.add_argument("--rate", type=parse_rate, help="税率/征收率，如 13%% 或 0.13")
    parser.add_argument("--tax", type=parse_decimal, help="应纳税额（减免额模式）")
    parser.add_argument("--reduction", type=parse_ratio, help="减免比例，如 50%% 或 0.5")
    args = parser.parse_args()

    try:
        result = build_result(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
