#!/usr/bin/env python3
"""日期区间与利息计算器（税务计算的天数底层）。

用途：
- 日期区间天数：必须显式选择 include-end（含首尾）或 exclude-end（算头不算尾）。
- 单段利息：本金 × 年利率 × 天数 ÷ 计息基数，金额四舍五入到分。
- 税务滞纳金、税额、减免额走 calc_tax.py，天数口径与这里保持一致。

设计原则：
- 不让模型心算天数或金额；把口径写进输出，报告直接引用。
- 分段计息时每段单独跑一次，再把各段结果相加。

用法：
  python3 scripts/calc_period.py \
    --start 2020-08-20 --end 2026-11-10 \
    --day-count include-end \
    --principal 1000000 --rate 12%

  # 只要天数
  python3 scripts/calc_period.py --start 2020-01-01 --end 2020-08-19 --day-count include-end

输出 JSON：
{
  "start": "2020-08-20",
  "end": "2026-11-10",
  "day_count": "include-end",
  "days": 2274,
  "principal": "1000000",
  "annual_rate": "0.12",
  "basis_days": 365,
  "interest": "747616.44",
  "total": "1747616.44",
  "formula": "1000000 × 12% × 2274 ÷ 365"
}
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期格式应为 YYYY-MM-DD：{value}") from exc


def parse_rate(value: str) -> Decimal:
    text = (value or "").strip()
    if not text:
        raise argparse.ArgumentTypeError("--rate 不能为空")
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        rate = Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"--rate 不是有效数字：{value}") from exc
    if percent:
        rate = rate / Decimal("100")
    if rate < 0:
        raise argparse.ArgumentTypeError("--rate 不能为负数")
    if not percent and rate > 1:
        raise argparse.ArgumentTypeError("--rate 请写 12% 或 0.12，不要只写 12")
    return rate


def parse_decimal(value: str) -> Decimal:
    try:
        amount = Decimal((value or "").strip())
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"不是有效金额：{value}") from exc
    if amount < 0:
        raise argparse.ArgumentTypeError("金额不能为负数")
    return amount


def days_between(start: date, end: date, day_count: str) -> int:
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    delta = (end - start).days
    if day_count == "include-end":
        return delta + 1
    if day_count == "exclude-end":
        return delta
    raise ValueError(f"未知天数口径：{day_count}")


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_result(args: argparse.Namespace) -> dict:
    days = days_between(args.start, args.end, args.day_count)
    result = {
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "day_count": args.day_count,
        "days": days,
    }
    if args.principal is None and args.rate is None:
        return result
    if args.principal is None or args.rate is None:
        raise ValueError("计算利息时 --principal 与 --rate 必须同时提供")
    principal = args.principal
    rate = args.rate
    basis = Decimal(args.basis_days)
    interest = (principal * rate * Decimal(days) / basis).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    rate_text = f"{rate * 100:g}%"
    result.update(
        {
            "principal": str(principal),
            "annual_rate": str(rate),
            "basis_days": args.basis_days,
            "interest": money(interest),
            "total": money(principal + interest),
            "formula": f"{principal} × {rate_text} × {days} ÷ {args.basis_days}",
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="日期区间与利息计算器")
    parser.add_argument("--start", required=True, type=parse_date, help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=parse_date, help="截止日 YYYY-MM-DD")
    parser.add_argument(
        "--day-count",
        required=True,
        choices=("include-end", "exclude-end"),
        help="include-end=含首尾；exclude-end=算头不算尾",
    )
    parser.add_argument("--principal", type=parse_decimal, help="本金")
    parser.add_argument("--rate", type=parse_rate, help="年利率，如 12%% 或 0.12")
    parser.add_argument("--basis-days", type=int, default=365, help="计息基数，默认 365")
    args = parser.parse_args()

    if args.basis_days <= 0:
        parser.error("--basis-days 必须大于 0")
    try:
        result = build_result(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
