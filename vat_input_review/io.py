from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .models import TransactionLine, money


def load_transaction_lines(path: str | Path) -> list[TransactionLine]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [transaction_line_from_dict(item) for item in payload]


def write_transaction_lines(path: str | Path, lines: list[TransactionLine]) -> None:
    Path(path).write_text(json.dumps([transaction_line_to_dict(line) for line in lines], indent=2), encoding="utf-8")


def transaction_line_from_dict(item: dict[str, Any]) -> TransactionLine:
    return TransactionLine(
        tenant_id=str(item["tenant_id"]),
        organisation_name=item.get("organisation_name"),
        transaction_type=str(item["transaction_type"]),
        transaction_id=str(item["transaction_id"]),
        line_id=str(item["line_id"]),
        document_number=item.get("document_number"),
        transaction_date=date.fromisoformat(str(item["transaction_date"])),
        vat_period=str(item["vat_period"]),
        supplier_id=item.get("supplier_id"),
        supplier_name=item.get("supplier_name"),
        supplier_vat_number=item.get("supplier_vat_number"),
        account_id=item.get("account_id"),
        account_code=item.get("account_code"),
        account_name=item.get("account_name"),
        tax_type=item.get("tax_type"),
        description=item.get("description"),
        net_amount=money(item.get("net_amount")),
        vat_amount=money(item.get("vat_amount")),
        gross_amount=money(item.get("gross_amount")),
        currency_code=item.get("currency_code", "ZAR"),
        source_url=item.get("source_url"),
        raw=item.get("raw", {}),
    )


def transaction_line_to_dict(line: TransactionLine) -> dict[str, Any]:
    return {
        "tenant_id": line.tenant_id,
        "organisation_name": line.organisation_name,
        "transaction_type": line.transaction_type,
        "transaction_id": line.transaction_id,
        "line_id": line.line_id,
        "document_number": line.document_number,
        "transaction_date": line.transaction_date.isoformat(),
        "vat_period": line.vat_period,
        "supplier_id": line.supplier_id,
        "supplier_name": line.supplier_name,
        "supplier_vat_number": line.supplier_vat_number,
        "account_id": line.account_id,
        "account_code": line.account_code,
        "account_name": line.account_name,
        "tax_type": line.tax_type,
        "description": line.description,
        "net_amount": str(Decimal(line.net_amount)),
        "vat_amount": str(Decimal(line.vat_amount)),
        "gross_amount": str(Decimal(line.gross_amount)),
        "currency_code": line.currency_code,
        "source_url": line.source_url,
    }
