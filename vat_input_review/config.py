from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when PyYAML is absent.
    yaml = None


@dataclass(frozen=True)
class ReviewDateRange:
    date_from: date
    date_to: date


@dataclass(frozen=True)
class OrgReviewConfig:
    tenant_id: str
    organisation_name: str | None = None
    standard_rate: Decimal = Decimal("0.15")
    vat_period_basis: str = "bi-monthly"
    lookback_years: int = 5
    review_range: ReviewDateRange | None = None
    minimum_sample_size: int = 5
    min_confidence: Decimal = Decimal("0.65")
    modal_share_threshold: Decimal = Decimal("0.70")
    standard_rate_tolerance: Decimal = Decimal("0.01")
    low_rate_threshold: Decimal = Decimal("0.80")
    no_vat_tax_types: set[str] = field(
        default_factory=lambda: {"NONE", "EXEMPTINPUT", "ZERORATEDINPUT", "INPUTZERORATED", "NO VAT", "EXEMPT"}
    )
    standard_input_tax_types: set[str] = field(default_factory=lambda: {"INPUT", "INPUT2", "STANDARD INPUT VAT"})
    blocked_input_vat_accounts: set[str] = field(default_factory=set)
    exempt_or_zero_rated_accounts: set[str] = field(default_factory=set)
    apportionment_accounts: set[str] = field(default_factory=set)
    non_vat_supplier_ids: set[str] = field(default_factory=set)
    non_vat_supplier_names: set[str] = field(default_factory=set)
    tax_type_aliases: dict[str, str] = field(default_factory=dict)

    def canonical_tax_type(self, tax_type: str | None) -> str:
        if not tax_type:
            return ""
        normalized = tax_type.strip().upper()
        return self.tax_type_aliases.get(normalized, normalized)

    def is_no_vat_tax_type(self, tax_type: str | None) -> bool:
        return self.canonical_tax_type(tax_type) in {self.canonical_tax_type(t) for t in self.no_vat_tax_types}

    def is_standard_input_tax_type(self, tax_type: str | None) -> bool:
        return self.canonical_tax_type(tax_type) in {self.canonical_tax_type(t) for t in self.standard_input_tax_types}

    def is_account_suppressed(self, account_id: str | None, account_code: str | None, account_name: str | None) -> bool:
        account_tokens = {token.strip().upper() for token in (account_id, account_code, account_name) if token}
        suppressed = (
            self.blocked_input_vat_accounts
            | self.exempt_or_zero_rated_accounts
            | self.apportionment_accounts
        )
        return bool(account_tokens & {token.strip().upper() for token in suppressed})

    def is_supplier_suppressed(self, supplier_id: str | None, supplier_name: str | None) -> bool:
        if supplier_id and supplier_id.strip().upper() in {s.upper() for s in self.non_vat_supplier_ids}:
            return True
        if supplier_name and supplier_name.strip().upper() in {s.upper() for s in self.non_vat_supplier_names}:
            return True
        return False


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_upper_set(values: Any) -> set[str]:
    if not values:
        return set()
    return {str(value).strip().upper() for value in values if str(value).strip()}


def load_org_config(path: str | Path) -> OrgReviewConfig:
    config_path = Path(path)
    if config_path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required to read YAML config files. Use JSON or install PyYAML.")
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    else:
        payload = json.loads(config_path.read_text(encoding="utf-8"))

    review_range = None
    if payload.get("review_date_range"):
        review_range = ReviewDateRange(
            date_from=_parse_date(payload["review_date_range"]["date_from"]),
            date_to=_parse_date(payload["review_date_range"]["date_to"]),
        )

    aliases = {str(k).strip().upper(): str(v).strip().upper() for k, v in payload.get("tax_type_aliases", {}).items()}

    return OrgReviewConfig(
        tenant_id=str(payload["tenant_id"]),
        organisation_name=payload.get("organisation_name"),
        standard_rate=Decimal(str(payload.get("standard_rate", "0.15"))),
        vat_period_basis=str(payload.get("vat_period_basis", "bi-monthly")),
        lookback_years=int(payload.get("lookback_years", 5)),
        review_range=review_range,
        minimum_sample_size=int(payload.get("minimum_sample_size", 5)),
        min_confidence=Decimal(str(payload.get("min_confidence", "0.65"))),
        modal_share_threshold=Decimal(str(payload.get("modal_share_threshold", "0.70"))),
        standard_rate_tolerance=Decimal(str(payload.get("standard_rate_tolerance", "0.01"))),
        low_rate_threshold=Decimal(str(payload.get("low_rate_threshold", "0.80"))),
        no_vat_tax_types=_as_upper_set(payload.get("no_vat_tax_types"))
        or OrgReviewConfig(tenant_id=str(payload["tenant_id"])).no_vat_tax_types,
        standard_input_tax_types=_as_upper_set(payload.get("standard_input_tax_types"))
        or OrgReviewConfig(tenant_id=str(payload["tenant_id"])).standard_input_tax_types,
        blocked_input_vat_accounts=_as_upper_set(payload.get("blocked_input_vat_accounts")),
        exempt_or_zero_rated_accounts=_as_upper_set(payload.get("exempt_or_zero_rated_accounts")),
        apportionment_accounts=_as_upper_set(payload.get("apportionment_accounts")),
        non_vat_supplier_ids=_as_upper_set(payload.get("non_vat_supplier_ids")),
        non_vat_supplier_names=_as_upper_set(payload.get("non_vat_supplier_names")),
        tax_type_aliases=aliases,
    )
