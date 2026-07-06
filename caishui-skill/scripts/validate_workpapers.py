#!/usr/bin/env python3
"""校验财税申报工作底稿是否具备申报准备条件。"""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0.00")
PROFILE_FIELD_ALIASES = {
    "entity_name": ["entity_name", "纳税人名称", "主体名称"],
    "legal_form": ["legal_form", "主体类型"],
    "province": ["province", "省份", "省/直辖市"],
    "city": ["city", "城市", "市"],
    "industry": ["industry", "行业"],
    "vat_taxpayer_status": ["vat_taxpayer_status", "增值税纳税人类型"],
    "collection_method": ["collection_method", "征收方式"],
    "filing_period_start": ["filing_period_start", "所属期起", "所属期开始"],
    "filing_period_end": ["filing_period_end", "所属期止", "所属期结束"],
    "official_policy_checked_at": ["official_policy_checked_at", "全国政策核验时间"],
    "local_policy_checked_at": ["local_policy_checked_at", "地方政策核验时间"],
}
PROFILE_DISPLAY = {
    "entity_name": "纳税人名称",
    "legal_form": "主体类型",
    "province": "省份",
    "city": "城市",
    "industry": "行业",
    "vat_taxpayer_status": "增值税纳税人类型",
    "collection_method": "征收方式",
    "filing_period_start": "所属期起",
    "filing_period_end": "所属期止",
    "official_policy_checked_at": "全国政策核验时间",
    "local_policy_checked_at": "地方政策核验时间",
}
PROFILE_REQUIRED = [
    "entity_name",
    "legal_form",
    "province",
    "city",
    "industry",
    "vat_taxpayer_status",
    "collection_method",
    "filing_period_start",
    "filing_period_end",
]
VAT_FIELD_ALIASES = {
    "period": ["period", "所属期"],
    "sales_ledger_ex_tax": ["sales_ledger_ex_tax", "账面不含税销售额"],
    "sales_invoice_ex_tax": ["sales_invoice_ex_tax", "发票不含税销售额"],
    "output_tax_ledger": ["output_tax_ledger", "账面销项税额"],
    "output_tax_invoice": ["output_tax_invoice", "发票销项税额"],
    "input_tax_ledger": ["input_tax_ledger", "账面进项税额"],
    "input_tax_certified": ["input_tax_certified", "已认证进项税额", "已勾选进项税额"],
}
VAT_FIELD_DISPLAY = {
    "period": "所属期",
    "sales_ledger_ex_tax": "账面不含税销售额",
    "sales_invoice_ex_tax": "发票不含税销售额",
    "output_tax_ledger": "账面销项税额",
    "output_tax_invoice": "发票销项税额",
    "input_tax_ledger": "账面进项税额",
    "input_tax_certified": "已认证/已勾选进项税额",
}


def money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0").replace(",", "").strip()).quantize(ZERO)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc


def finding(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def field_value(row: dict[str, str], field: str) -> str:
    for name in VAT_FIELD_ALIASES[field]:
        if name in row:
            return row.get(name, "")
    return ""


def has_field(fieldnames: list[str], field: str) -> bool:
    return any(name in fieldnames for name in VAT_FIELD_ALIASES[field])


def profile_value(data: dict[str, Any], field: str) -> Any:
    for name in PROFILE_FIELD_ALIASES[field]:
        if name in data:
            return data.get(name)
    return None


def validate_profile(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    findings: list[dict[str, str]] = []
    for key in PROFILE_REQUIRED:
        if not profile_value(data, key):
            findings.append(finding("blocker", f"profile.missing.{key}", f"纳税人画像缺少字段：{PROFILE_DISPLAY[key]}。"))
    if not profile_value(data, "official_policy_checked_at"):
        findings.append(
            finding("high", "policy.national.not_checked", "全国政策核验时间为空；请重新核验官方来源。")
        )
    if not profile_value(data, "local_policy_checked_at"):
        findings.append(
            finding("high", "policy.local.not_checked", "地方政策核验时间为空；请核验省市税务局口径。")
        )
    return findings


def validate_statement_summary(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    diff = money(data.get("equation_difference"))
    if diff != ZERO:
        return [
            finding(
                "blocker",
                "statements.not_balanced",
                f"资产负债表勾稽差额为 {diff}；财务报表申报前必须处理。",
            )
        ]
    return []


def validate_vat(path: Path, tolerance: Decimal) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        required = [
            "period",
            "sales_ledger_ex_tax",
            "sales_invoice_ex_tax",
            "output_tax_ledger",
            "output_tax_invoice",
            "input_tax_ledger",
            "input_tax_certified",
        ]
        fieldnames = reader.fieldnames or []
        missing = [field for field in required if not has_field(fieldnames, field)]
        if missing:
            names = "、".join(VAT_FIELD_DISPLAY[field] for field in missing)
            return [finding("blocker", "vat.columns_missing", f"增值税勾稽表缺少必填列: {names}")]
        for row_no, row in enumerate(reader, 2):
            period = field_value(row, "period") or f"第 {row_no} 行"
            sales_diff = money(field_value(row, "sales_ledger_ex_tax")) - money(field_value(row, "sales_invoice_ex_tax"))
            output_diff = money(field_value(row, "output_tax_ledger")) - money(field_value(row, "output_tax_invoice"))
            input_diff = money(field_value(row, "input_tax_ledger")) - money(field_value(row, "input_tax_certified"))
            if abs(sales_diff) > tolerance:
                findings.append(
                    finding("high", "vat.sales_mismatch", f"{period}：账面销售额与发票销售额差异 {sales_diff}。")
                )
            if abs(output_diff) > tolerance:
                findings.append(
                    finding("high", "vat.output_tax_mismatch", f"{period}：账面销项税额与发票销项税额差异 {output_diff}。")
                )
            if abs(input_diff) > tolerance:
                findings.append(
                    finding("medium", "vat.input_tax_mismatch", f"{period}：账面进项税额与已认证/已勾选进项税额差异 {input_diff}。")
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="校验财税申报工作底稿是否具备申报准备条件。")
    parser.add_argument("--profile", type=Path, help="纳税人画像 JSON。")
    parser.add_argument("--statement-summary", type=Path, help="报表生成脚本输出的 summary.json。")
    parser.add_argument("--vat-reconciliation", type=Path, help="增值税勾稽 CSV，支持中文或英文表头。")
    parser.add_argument("--tolerance", default="0.01", help="金额差异容忍度，默认 0.01。")
    parser.add_argument("--json", action="store_true", help="输出 JSON。")
    args = parser.parse_args()

    findings: list[dict[str, str]] = []
    if args.profile:
        findings.extend(validate_profile(args.profile))
    if args.statement_summary:
        findings.extend(validate_statement_summary(args.statement_summary))
    if args.vat_reconciliation:
        findings.extend(validate_vat(args.vat_reconciliation, money(args.tolerance)))

    payload = {"status": "pass" if not findings else "fail", "findings": findings}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("通过" if payload["status"] == "pass" else "未通过")
        for item in findings:
            print(f"- {item['severity']} {item['code']}: {item['message']}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
