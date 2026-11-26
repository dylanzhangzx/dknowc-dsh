#!/usr/bin/env python3
"""法律场景纯算术计算器（交付前唯一算术入口）。

解决：经济补偿年限折算、年假 300%、比例/倍数、封顶等结论没有起止日期，
无法用 calc_period.py 登记的问题。所有结果可重算，不允许心算。

模式：
- severance    经济补偿/赔偿金：月工资 × 折算月数；可传三倍社平封顶
- annual-leave 未休年假：日工资 × 天数 × 300%（同时给出含正常工资部分）
- ratio        比例：基数 × 比例（如定金 20%）
- multiple     倍数：基数 × 倍数（如二倍工资）
- custom       兜底算式：只允许数字、括号和 + - * /，变量必须来自 inputs

用法：
  python3 scripts/calc_legal.py --mode severance --monthly-wage 18000 --years 7 --months 3
  python3 scripts/calc_legal.py --mode annual-leave --daily-wage 1379 --days 10
  python3 scripts/calc_legal.py --mode ratio --base 100000 --ratio 20%
  python3 scripts/calc_legal.py --mode multiple --base 5000 --multiple 2
  python3 scripts/calc_legal.py --mode custom --inputs '{"a":18000,"b":7.5}' --formula "a*b"
"""

from __future__ import annotations

import argparse
import ast
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, Mapping

MODES = ("severance", "annual-leave", "ratio", "multiple", "court-fee", "custom")


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{name} 必须是数字")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{name} 不是有效数字：{value}") from exc
    if not number.is_finite():
        raise ValueError(f"{name} 必须是有限数字")
    if number < 0:
        raise ValueError(f"{name} 不能为负数")
    return number


def _integer(value: Any, name: str) -> int:
    number = _decimal(value, name)
    if number != number.to_integral_value():
        raise ValueError(f"{name} 必须是整数")
    return int(number)


def _percent(value: Any, name: str) -> Decimal:
    text = str(value).strip()
    if text.endswith("%"):
        return _decimal(text[:-1], name) / Decimal("100")
    number = _decimal(text, name)
    if number > 1:
        raise ValueError(f"{name} 请写 20% 或 0.2，不要只写 20")
    return number


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _severance(values: Mapping[str, Any]) -> Dict[str, Any]:
    monthly_wage = _decimal(values.get("monthly_wage"), "monthly_wage")
    years = _integer(values.get("years", 0), "years")
    months = _integer(values.get("months", 0), "months")
    if months >= 12:
        raise ValueError("months 应为 0-11；满 12 个月请计入 years")
    if years == 0 and months == 0:
        raise ValueError("years 与 months 不能同时为 0")

    # 《劳动合同法》第四十七条：每满一年一个月；六个月以上不满一年按一年；
    # 不满六个月支付半个月。
    factor = Decimal(years) + (Decimal("1") if months >= 6 else Decimal("0.5") if months > 0 else Decimal("0"))
    wage_used = monthly_wage
    cap_years = _integer(values.get("cap_years", 12), "cap_years")
    cap_applied = False
    notes = []
    if values.get("capped_wage") not in (None, ""):
        capped_wage = _decimal(values.get("capped_wage"), "capped_wage")
        if monthly_wage > capped_wage:
            wage_used = capped_wage
            cap_applied = True
            if factor > cap_years:
                factor = Decimal(cap_years)
            notes.append(
                "月工资高于本地区上年度职工月平均工资三倍，按三倍数额支付，年限最高不超过"
                f"{cap_years}年（《劳动合同法》第四十七条第二款）"
            )
    if not cap_applied:
        notes.append("未传入 capped_wage，按未触发三倍社平封顶计算；若已触发需重算")

    amount = (wage_used * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "mode": "severance",
        "years": years,
        "months": months,
        "months_factor": _plain(factor),
        "monthly_wage": _plain(monthly_wage),
        "wage_used": _plain(wage_used),
        "cap_applied": cap_applied,
        "amount": _money(amount),
        "formula": f"{_plain(wage_used)} × {_plain(factor)}",
        "notes": notes,
    }


def _annual_leave(values: Mapping[str, Any]) -> Dict[str, Any]:
    daily_wage = _decimal(values.get("daily_wage"), "daily_wage")
    days = _decimal(values.get("days"), "days")
    paid_text = str(values.get("paid_ratio", 3)).strip()
    paid = (
        _decimal(paid_text[:-1], "paid_ratio") / Decimal("100")
        if paid_text.endswith("%")
        else _decimal(paid_text, "paid_ratio")
    )
    total = (daily_wage * days * paid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    normal = (daily_wage * days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "mode": "annual-leave",
        "daily_wage": _plain(daily_wage),
        "days": _plain(days),
        "paid_ratio": _plain(paid),
        "normal_wage": _money(normal),
        "total": _money(total),
        "additional": _money(total - normal),
        "formula": f"{_plain(daily_wage)} × {_plain(days)} × {_plain(paid)}",
        "notes": [
            "300% 中含正常工作期间工资 100%，可另行主张的是额外 200%；"
            "以当年度未休天数为前提"
        ],
    }


def _ratio(values: Mapping[str, Any]) -> Dict[str, Any]:
    base = _decimal(values.get("base"), "base")
    ratio = _percent(values.get("ratio"), "ratio")
    amount = (base * ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "mode": "ratio",
        "base": _plain(base),
        "ratio": _plain(ratio),
        "amount": _money(amount),
        "formula": f"{_plain(base)} × {_plain(ratio)}",
    }


def _multiple(values: Mapping[str, Any]) -> Dict[str, Any]:
    base = _decimal(values.get("base"), "base")
    multiple = _decimal(values.get("multiple"), "multiple")
    amount = (base * multiple).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "mode": "multiple",
        "base": _plain(base),
        "multiple": _plain(multiple),
        "amount": _money(amount),
        "formula": f"{_plain(base)} × {_plain(multiple)}",
    }


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
)


def _eval_formula(formula: str, inputs: Mapping[str, Any]) -> Decimal:
    try:
        tree = ast.parse((formula or "").strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"formula 语法错误：{exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"formula 含不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise ValueError("formula 只能包含数字")
        if isinstance(node, ast.Name) and node.id not in inputs:
            raise ValueError(f"formula 变量未在 inputs 中：{node.id}")

    def walk(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            return _decimal(inputs[node.id], node.id)
        if isinstance(node, ast.UnaryOp):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise ValueError("formula 除数为 0")
            return left / right
        raise ValueError("formula 无法求值")

    return walk(tree)


# 财产案件受理费分段表（《诉讼费用交纳办法》第十三条）：(上限, 超出部分费率)
# 上一档封顶时累计费用 = fee_at_cap；最后一档为(无穷, 0.6%)。
_COURT_FEE_TIERS = (
    (Decimal("10000"), Decimal("0")),
    (Decimal("100000"), Decimal("0.025")),
    (Decimal("200000"), Decimal("0.02")),
    (Decimal("500000"), Decimal("0.015")),
    (Decimal("1000000"), Decimal("0.01")),
    (Decimal("2000000"), Decimal("0.009")),
    (Decimal("5000000"), Decimal("0.008")),
    (Decimal("10000000"), Decimal("0.007")),
    (None, Decimal("0.006")),
)


def _court_fee(values: Mapping[str, Any]) -> Dict[str, Any]:
    """诉讼费速算（轻量）：财产案件受理费分段累计，可按简易程序/调解减半。

    inputs：claim_amount（诉讼请求金额）；halved=true 时按减半计。
    """
    claim = _decimal(values.get("claim_amount"), "claim_amount")
    if claim.is_nan() or not claim.is_finite() or claim < 0:
        raise ValueError("claim_amount 必须是非负金额")
    halved = values.get("halved")
    if isinstance(halved, str):
        halved = halved.strip().lower() in ("1", "true", "yes", "是")
    halved = bool(halved)

    fee = Decimal("0")
    lower = Decimal("0")
    base_fee = Decimal("50")  # ≤1 万基础件费
    for cap, rate in _COURT_FEE_TIERS:
        if claim <= lower:
            break
        upper = cap if cap is not None else claim
        taxable = min(claim, upper) - lower
        if taxable > 0:
            if lower == 0:
                fee = base_fee + taxable * rate
            else:
                fee += taxable * rate
        lower = upper
    fee = fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if halved:
        fee = (fee / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "mode": "court-fee",
        "inputs": {"claim_amount": _plain(claim), "halved": halved},
        "value": _money(fee),
        "note": "《诉讼费用交纳办法》第十三条分段累计" + ("；按简易程序/调解减半" if halved else ""),
    }


def _custom(values: Mapping[str, Any]):
    inputs = values.get("inputs")
    if not isinstance(inputs, Mapping) or not inputs:
        raise ValueError("custom 模式必须提供 inputs 对象")
    formula = str(values.get("formula") or "").strip()
    if not formula:
        raise ValueError("custom 模式必须提供 formula")
    try:
        raw = _eval_formula(formula, inputs)
        if not raw.is_finite():
            raise ValueError("formula 计算结果不是有限数")
        value = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ArithmeticError) as exc:
        raise ValueError("formula 计算结果超出可表示范围") from exc
    return {
        "mode": "custom",
        "inputs": {str(k): _plain(_decimal(v, str(k))) for k, v in inputs.items()},
        "formula": formula,
        "value": _money(value),
    }


_BUILDERS = {
    "severance": _severance,
    "annual-leave": _annual_leave,
    "ratio": _ratio,
    "multiple": _multiple,
    "court-fee": _court_fee,
    "custom": _custom,
}


def calculate(mode: str, values: Mapping[str, Any]) -> Dict[str, Any]:
    mode = (mode or "").strip()
    if mode not in _BUILDERS:
        raise ValueError(f"未知模式：{mode}；可选 {', '.join(MODES)}")
    if not isinstance(values, Mapping):
        raise ValueError("inputs 必须是对象")
    return _BUILDERS[mode](values)


def build_result(args: argparse.Namespace) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    if args.inputs:
        try:
            parsed = json.loads(args.inputs)
        except json.JSONDecodeError as exc:
            raise ValueError(f"--inputs 不是有效 JSON：{exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("--inputs 必须是 JSON 对象")
        if args.mode == "custom":
            values["inputs"] = parsed
        else:
            values.update(parsed)
    for key in (
        "monthly_wage", "years", "months", "capped_wage", "cap_years",
        "daily_wage", "days", "paid_ratio", "base", "ratio", "multiple", "formula",
        "claim_amount", "halved",
    ):
        value = getattr(args, key, None)
        if value is not None:
            values[key] = value
    return calculate(args.mode, values)


def main() -> int:
    parser = argparse.ArgumentParser(description="法律场景纯算术计算器")
    parser.add_argument("--mode", required=True, choices=MODES, help="计算模式")
    parser.add_argument("--inputs", help="JSON 对象；custom 模式必填")
    parser.add_argument("--monthly-wage", help="月工资")
    parser.add_argument("--years", help="完整工作年数")
    parser.add_argument("--months", help="完整年之外的月数（0-11）")
    parser.add_argument("--capped-wage", help="三倍社平封顶后的月工资；不传按未封顶")
    parser.add_argument("--cap-years", help="封顶年限，默认 12")
    parser.add_argument("--daily-wage", help="日工资")
    parser.add_argument("--days", help="天数")
    parser.add_argument("--paid-ratio", help="年假工资比例，默认 3（300%%）")
    parser.add_argument("--base", help="基数")
    parser.add_argument("--ratio", help="比例，如 20%% 或 0.2")
    parser.add_argument("--multiple", help="倍数")
    parser.add_argument("--formula", help="custom 模式算式，如 a*b")
    args = parser.parse_args()

    try:
        result = build_result(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
