#!/usr/bin/env python3
"""扫描账单/凭证目录，生成资料索引，并可选复制归档副本。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


DEFAULT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".csv",
    ".xls",
    ".xlsx",
    ".ofd",
    ".xml",
    ".txt",
    ".json",
    ".md",
    ".zip",
}

CATEGORY_RULES = [
    ("支付宝账单", ["支付宝", "alipay"]),
    ("微信账单", ["微信", "wechat", "weixin"]),
    ("银行流水", ["银行", "流水", "bank", "statement"]),
    ("发票", ["发票", "invoice", "数电票", "专票", "普票"]),
    ("申报表", ["申报", "申报表", "declaration", "return"]),
    ("完税缴款凭证", ["完税", "缴款", "扣款", "税收缴款", "tax_payment", "payment"]),
    ("合同订单", ["合同", "订单", "contract", "order"]),
    ("工资薪酬", ["工资", "薪酬", "payroll", "salary"]),
    ("社保公积金", ["社保", "公积金", "social", "housing"]),
    ("电子税务局回执", ["回执", "受理", "电子税务局", "receipt"]),
]

ARCHIVE_PREFIX = {
    "发票": "01_发票",
    "支付宝账单": "02_支付宝账单",
    "微信账单": "03_微信账单",
    "银行流水": "04_银行流水",
    "合同订单": "05_合同订单",
    "工资薪酬": "06_工资社保公积金",
    "社保公积金": "06_工资社保公积金",
    "申报表": "07_申报表和回执",
    "电子税务局回执": "07_申报表和回执",
    "完税缴款凭证": "08_完税缴款凭证",
    "待分类": "99_待分类",
}


@dataclass
class BillEntry:
    文件ID: str
    原始路径: str
    归档路径: str
    SHA256: str
    文件名: str
    扩展名: str
    大小字节: int
    修改时间: str
    推断日期: str
    资料类别: str
    来源平台: str
    所属期: str
    交易对方: str = ""
    金额: str = ""
    税额: str = ""
    发票号码: str = ""
    订单号: str = ""
    关联凭证号: str = ""
    是否已入账: str = "否"
    是否已勾稽: str = "否"
    待处理标签: str = ""
    备注: str = ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    value = re.sub(r"[\\\\/:*?\"<>|\\s]+", "_", value.strip())
    return value.strip("_") or "未命名"


def infer_date(text: str) -> str:
    patterns = [
        r"(20\\d{2})[-_.年](\\d{1,2})[-_.月](\\d{1,2})",
        r"(20\\d{2})(\\d{2})(\\d{2})",
        r"(20\\d{2})[-_.年](\\d{1,2})",
        r"(20\\d{2})(\\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = match.groups()
        if len(parts) == 3:
            year, month, day = parts
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        year, month = parts
        return f"{int(year):04d}-{int(month):02d}"
    return ""


def infer_category(path: Path) -> str:
    haystack = f"{path.name} {path.parent}".lower()
    for category, keywords in CATEGORY_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            return category
    return "待分类"


def infer_platform(category: str) -> str:
    if category == "支付宝账单":
        return "支付宝"
    if category == "微信账单":
        return "微信支付"
    if category == "银行流水":
        return "银行"
    if category in {"申报表", "电子税务局回执", "完税缴款凭证"}:
        return "电子税务局"
    return ""


def period_from_date(value: str) -> str:
    if re.match(r"^20\\d{2}-\\d{2}", value):
        return value[:7]
    return ""


def archive_target(root: Path, entry: BillEntry, original: Path) -> Path:
    period = entry.所属期 or "未知所属期"
    year = period[:4] if re.match(r"^20\\d{2}", period) else "未知年度"
    category_dir = ARCHIVE_PREFIX.get(entry.资料类别, "99_待分类")
    date_part = entry.推断日期 or "未知日期"
    filename = f"{date_part}_{entry.资料类别}_{entry.文件ID}_{safe_name(original.name)}"
    return root / year / period / category_dir / filename


def scan_files(source: Path, include_all: bool) -> list[Path]:
    paths: list[Path] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        if include_all or path.suffix.lower() in DEFAULT_EXTENSIONS:
            paths.append(path)
    return sorted(paths)


def build_entries(source: Path, copy_to: Optional[Path], include_all: bool) -> list[BillEntry]:
    entries: list[tuple[BillEntry, Path]] = []
    for path in scan_files(source, include_all):
        digest = sha256_file(path)
        stat = path.stat()
        inferred_date = infer_date(str(path))
        category = infer_category(path)
        entry = BillEntry(
            文件ID=digest[:12],
            原始路径=str(path),
            归档路径="",
            SHA256=digest,
            文件名=path.name,
            扩展名=path.suffix.lower(),
            大小字节=stat.st_size,
            修改时间=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            推断日期=inferred_date,
            资料类别=category,
            来源平台=infer_platform(category),
            所属期=period_from_date(inferred_date),
        )
        entries.append((entry, path))

    hash_counts = Counter(entry.SHA256 for entry, _ in entries)
    results: list[BillEntry] = []
    for entry, path in entries:
        labels: list[str] = []
        if not entry.推断日期:
            labels.append("缺日期")
        if entry.资料类别 == "待分类":
            labels.append("需分类")
        if hash_counts[entry.SHA256] > 1:
            labels.append("重复文件")
        entry.待处理标签 = "；".join(labels)
        if copy_to:
            target = archive_target(copy_to, entry, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
            entry.归档路径 = str(target)
        results.append(entry)
    return results


def write_index(entries: list[BillEntry], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(BillEntry.__dataclass_fields__.keys())
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.__dict__)


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描账单和凭证目录，生成中文资料索引，并可选复制归档副本。")
    parser.add_argument("--source", required=True, type=Path, help="原始资料目录。")
    parser.add_argument("--out", required=True, type=Path, help="输出的账单索引 CSV。")
    parser.add_argument("--copy-to", type=Path, help="可选：复制归档到指定目录，不删除原文件。")
    parser.add_argument("--include-all", action="store_true", help="包含所有扩展名；默认只扫描常见账单/凭证格式。")
    args = parser.parse_args()

    if not args.source.exists() or not args.source.is_dir():
        raise SystemExit(f"原始资料目录不存在或不是目录：{args.source}")

    entries = build_entries(args.source, args.copy_to, args.include_all)
    write_index(entries, args.out)
    duplicates = sum(1 for entry in entries if "重复文件" in entry.待处理标签)
    unresolved = sum(1 for entry in entries if entry.待处理标签)
    print(f"已扫描文件：{len(entries)}")
    print(f"索引文件：{args.out}")
    if args.copy_to:
        print(f"归档目录：{args.copy_to}")
    print(f"待处理文件：{unresolved}")
    print(f"重复文件标记：{duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
