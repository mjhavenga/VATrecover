from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


Money = Decimal


def money(value: Any) -> Money:
    """Normalize API/fixture numeric values to two-decimal Decimal money."""
    if value is None:
        value = "0"
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rate(value: Any) -> Decimal:
    """Normalize rates as Decimal fractions, for example 0.15 for 15%."""
    if value is None:
        value = "0"
    return Decimal(str(value))


@dataclass(frozen=True)
class TransactionLine:
    """A single normalized purchase-side line from Xero.

    The rule engine only consumes this model, which keeps client data scoped to
    one Xero tenant and avoids coupling VAT review logic to raw Xero payloads.
    """

    tenant_id: str
    organisation_name: str | None
    transaction_type: str
    transaction_id: str
    line_id: str
    document_number: str | None
    transaction_date: date
    vat_period: str
    supplier_id: str | None
    supplier_name: str | None
    supplier_vat_number: str | None
    account_id: str | None
    account_code: str | None
    account_name: str | None
    tax_type: str | None
    description: str | None
    net_amount: Money
    vat_amount: Money
    gross_amount: Money
    currency_code: str = "ZAR"
    source_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def account_key(self) -> str:
        return self.account_id or self.account_code or self.account_name or "UNKNOWN_ACCOUNT"

    @property
    def supplier_key(self) -> str:
        return self.supplier_id or self.supplier_name or "UNKNOWN_SUPPLIER"

    @property
    def pair_key(self) -> tuple[str, str]:
        return self.account_key, self.supplier_key

    @property
    def has_supplier_vat_number(self) -> bool:
        return bool((self.supplier_vat_number or "").strip())

    @property
    def effective_rate(self) -> Decimal:
        base = abs(self.net_amount)
        if base == 0:
            return Decimal("0")
        return (abs(self.vat_amount) / base).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class ReviewFinding:
    reason_code: str
    reason: str
    confidence: Decimal
    expected_vat: Money
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewFlag:
    line: TransactionLine
    reason_code: str
    reason: str
    confidence: Decimal
    expected_vat: Money
    estimated_underclaim: Money
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantConnection:
    tenant_id: str
    tenant_name: str | None
    tenant_type: str | None = None
    auth_event_id: str | None = None
