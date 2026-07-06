#!/usr/bin/env python3
"""根据账簿 CSV 生成简易财务报表工作底稿。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


ZERO = Decimal("0.00")
FIELD_ALIASES = {
    "account_code": ["account_code", "科目编码", "会计科目编码"],
    "account_name": ["account_name", "科目名称", "会计科目"],
    "account_type": ["account_type", "科目类型", "报表分类"],
    "debit": ["debit", "借方", "借方金额"],
    "credit": ["credit", "贷方", "贷方金额"],
}
FIELD_DISPLAY = {
    "account_code": "科目编码",
    "account_name": "科目名称",
    "account_type": "科目类型",
    "debit": "借方",
    "credit": "贷方",
}
TYPE_ALIASES = {
    "资产": "asset",
    "负债": "liability",
    "所有者权益": "equity",
    "权益": "equity",
    "收入": "revenue",
    "成本": "expense",
    "费用": "expense",
    "成本费用": "expense",
}


@dataclass
class AccountTotal:
    code: str
    name: str
    account_type: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO

    @property
    def signed_balance(self) -> Decimal:
        if self.account_type in {"liability", "equity", "revenue"}:
            return self.credit - self.debit
        return self.debit - self.credit


def money(value: object) -> Decimal:
    if not value:
        return ZERO
    try:
        return Decimal(str(value).replace(",", "").strip() or "0").quantize(ZERO)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc


def field_value(row: dict[str, str], field: str) -> str:
    for name in FIELD_ALIASES[field]:
        if name in row:
            return row.get(name, "")
    return ""


def has_field(fieldnames: list[str], field: str) -> bool:
    return any(name in fieldnames for name in FIELD_ALIASES[field])


def infer_type(code: str, name: str, explicit: str) -> str:
    explicit = (explicit or "").strip().lower()
    if explicit:
        if explicit in TYPE_ALIASES:
            return TYPE_ALIASES[explicit]
        return explicit
    code = (code or "").strip()
    name = name or ""
    if code.startswith("1"):
        return "asset"
    if code.startswith("2"):
        return "liability"
    if code.startswith("4"):
        return "equity"
    if code.startswith("5"):
        return "expense"
    if code.startswith("6"):
        if "收入" in name or "收益" in name:
            return "revenue"
        return "expense"
    return "unknown"


def load_ledger(path: Path) -> tuple[dict[str, AccountTotal], list[str]]:
    totals: dict[str, AccountTotal] = {}
    warnings: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        required = ["account_code", "account_name", "debit", "credit"]
        missing = [field for field in required if not has_field(fieldnames, field)]
        if missing:
            names = "、".join(FIELD_DISPLAY[field] for field in missing)
            raise ValueError(f"账簿缺少必填列: {names}")
        for row_no, row in enumerate(reader, 2):
            code = field_value(row, "account_code").strip()
            name = field_value(row, "account_name").strip()
            if not code and not name:
                continue
            key = code or name
            account_type = infer_type(code, name, field_value(row, "account_type"))
            if account_type == "unknown":
                warnings.append(f"第 {row_no} 行：无法判断科目类型 {code} {name}")
            total = totals.setdefault(key, AccountTotal(code, name, account_type))
            total.debit += money(field_value(row, "debit"))
            total.credit += money(field_value(row, "credit"))
    return totals, warnings


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: Decimal) -> str:
    return str(value.quantize(ZERO))


def build_outputs(ledger: Path, out_dir: Path) -> dict[str, object]:
    totals, warnings = load_ledger(ledger)
    out_dir.mkdir(parents=True, exist_ok=True)

    trial_rows: list[dict[str, str]] = []
    buckets: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for total in sorted(totals.values(), key=lambda item: (item.code, item.name)):
        balance = total.signed_balance
        buckets[total.account_type] += balance
        trial_rows.append(
            {
                "account_code": total.code,
                "account_name": total.name,
                "account_type": total.account_type,
                "debit_total": fmt(total.debit),
                "credit_total": fmt(total.credit),
                "signed_balance": fmt(balance),
            }
        )

    write_csv(
        out_dir / "trial_balance.csv",
        ["account_code", "account_name", "account_type", "debit_total", "credit_total", "signed_balance"],
        trial_rows,
    )

    assets = buckets["asset"]
    liabilities = buckets["liability"]
    equity = buckets["equity"]
    revenue = buckets["revenue"]
    expense = buckets["expense"]
    profit = revenue - expense
    equation_difference = assets - liabilities - equity - profit

    write_csv(
        out_dir / "balance_sheet_workpaper.csv",
        ["line_item", "amount"],
        [
            {"line_item": "assets", "amount": fmt(assets)},
            {"line_item": "liabilities", "amount": fmt(liabilities)},
            {"line_item": "equity_before_profit", "amount": fmt(equity)},
            {"line_item": "current_period_profit", "amount": fmt(profit)},
            {"line_item": "equation_difference", "amount": fmt(equation_difference)},
        ],
    )
    write_csv(
        out_dir / "income_statement_workpaper.csv",
        ["line_item", "amount"],
        [
            {"line_item": "revenue", "amount": fmt(revenue)},
            {"line_item": "expenses", "amount": fmt(expense)},
            {"line_item": "profit", "amount": fmt(profit)},
        ],
    )

    summary: dict[str, object] = {
        "ledger": str(ledger),
        "outputs": [
            str(out_dir / "trial_balance.csv"),
            str(out_dir / "balance_sheet_workpaper.csv"),
            str(out_dir / "income_statement_workpaper.csv"),
        ],
        "assets": fmt(assets),
        "liabilities": fmt(liabilities),
        "equity_before_profit": fmt(equity),
        "current_period_profit": fmt(profit),
        "equation_difference": fmt(equation_difference),
        "balanced": equation_difference == ZERO,
        "warnings": warnings,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="根据账簿 CSV 生成试算平衡、资产负债表和利润表底稿。")
    parser.add_argument("--ledger", required=True, type=Path, help="账簿 CSV 文件，支持中文或英文表头。")
    parser.add_argument("--out", required=True, type=Path, help="输出目录。")
    args = parser.parse_args()
    summary = build_outputs(args.ledger, args.out)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["balanced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
