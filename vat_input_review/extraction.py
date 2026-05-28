from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from .auth import CONNECTIONS_URL
from .config import OrgReviewConfig
from .models import TenantConnection, TransactionLine, money
from .tax_periods import vat_period_label


ACCOUNTING_API_BASE = "https://api.xero.com/api.xro/2.0"


class XeroRateLimiter:
    """Conservative limiter for Xero's minute/day read limits."""

    def __init__(self, per_minute: int = 60, per_day: int = 5000):
        self.min_interval_seconds = 60 / per_minute
        self.per_day = per_day
        self.calls_today = 0
        self.last_call_at = 0.0

    def wait(self) -> None:
        if self.calls_today >= self.per_day:
            raise RuntimeError("Xero daily API limit reached for this process.")
        elapsed = time.monotonic() - self.last_call_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        self.last_call_at = time.monotonic()
        self.calls_today += 1


@dataclass(frozen=True)
class XeroExtractionResult:
    tenant: TenantConnection
    accounts: list[dict[str, Any]]
    contacts: list[dict[str, Any]]
    tax_rates: list[dict[str, Any]]
    organisation: dict[str, Any] | None
    lines: list[TransactionLine]


class XeroAccountingClient:
    def __init__(self, access_token: str, rate_limiter: XeroRateLimiter | None = None):
        import requests

        self.access_token = access_token
        self.rate_limiter = rate_limiter or XeroRateLimiter()
        self.session = requests.Session()

    def list_connections(self) -> list[TenantConnection]:
        payload = self._raw_get(CONNECTIONS_URL, tenant_id=None)
        return [
            TenantConnection(
                tenant_id=item["tenantId"],
                tenant_name=item.get("tenantName"),
                tenant_type=item.get("tenantType"),
                auth_event_id=item.get("authEventId"),
            )
            for item in payload
        ]

    def extract_for_tenant(self, tenant_id: str, config: OrgReviewConfig, date_from: date, date_to: date) -> XeroExtractionResult:
        tenant = self._resolve_tenant(tenant_id)
        organisation = self.get_organisation(tenant_id)
        accounts = self.get_accounts(tenant_id)
        contacts = self.get_contacts(tenant_id)
        tax_rates = self.get_tax_rates(tenant_id)

        contact_by_id = {c.get("ContactID"): c for c in contacts if c.get("ContactID")}
        account_by_code = {a.get("Code"): a for a in accounts if a.get("Code")}

        documents: list[tuple[str, dict[str, Any]]] = []
        documents.extend(("INVOICE", item) for item in self.get_purchase_invoices(tenant_id, date_from, date_to))
        documents.extend(("BANK_TRANSACTION", item) for item in self.get_spend_bank_transactions(tenant_id, date_from, date_to))
        documents.extend(("CREDIT_NOTE", item) for item in self.get_purchase_credit_notes(tenant_id, date_from, date_to))

        lines: list[TransactionLine] = []
        for document_type, document in documents:
            lines.extend(
                normalize_xero_purchase_document(
                    tenant_id=tenant_id,
                    organisation_name=tenant.tenant_name or config.organisation_name,
                    document_type=document_type,
                    document=document,
                    contact_by_id=contact_by_id,
                    account_by_code=account_by_code,
                    config=config,
                )
            )

        return XeroExtractionResult(
            tenant=tenant,
            accounts=accounts,
            contacts=contacts,
            tax_rates=tax_rates,
            organisation=organisation,
            lines=lines,
        )

    def get_accounts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get_collection(tenant_id, "Accounts", "Accounts")

    def get_contacts(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get_collection(tenant_id, "Contacts", "Contacts")

    def get_tax_rates(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._get_collection(tenant_id, "TaxRates", "TaxRates")

    def get_organisation(self, tenant_id: str) -> dict[str, Any] | None:
        organisations = self._get_collection(tenant_id, "Organisation", "Organisations")
        return organisations[0] if organisations else None

    def get_purchase_invoices(self, tenant_id: str, date_from: date, date_to: date) -> list[dict[str, Any]]:
        where = f'Type=="ACCPAY"&&Date>=DateTime({date_from.year},{date_from.month},{date_from.day})&&Date<=DateTime({date_to.year},{date_to.month},{date_to.day})'
        return self._get_paginated(tenant_id, "Invoices", "Invoices", params={"where": where, "order": "Date ASC"})

    def get_spend_bank_transactions(self, tenant_id: str, date_from: date, date_to: date) -> list[dict[str, Any]]:
        where = f'Type=="SPEND"&&Date>=DateTime({date_from.year},{date_from.month},{date_from.day})&&Date<=DateTime({date_to.year},{date_to.month},{date_to.day})'
        return self._get_paginated(tenant_id, "BankTransactions", "BankTransactions", params={"where": where, "order": "Date ASC"})

    def get_purchase_credit_notes(self, tenant_id: str, date_from: date, date_to: date) -> list[dict[str, Any]]:
        where = f'Type=="ACCPAYCREDIT"&&Date>=DateTime({date_from.year},{date_from.month},{date_from.day})&&Date<=DateTime({date_to.year},{date_to.month},{date_to.day})'
        return self._get_paginated(tenant_id, "CreditNotes", "CreditNotes", params={"where": where, "order": "Date ASC"})

    def _resolve_tenant(self, tenant_id: str) -> TenantConnection:
        for connection in self.list_connections():
            if connection.tenant_id == tenant_id:
                return connection
        raise ValueError(f"Tenant {tenant_id} is not available on this Xero connection.")

    def _get_collection(self, tenant_id: str, endpoint: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = self._raw_get(f"{ACCOUNTING_API_BASE}/{endpoint}", tenant_id=tenant_id, params=params)
        return list(payload.get(key, []))

    def _get_paginated(self, tenant_id: str, endpoint: str, key: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            page_params = dict(params or {})
            page_params["page"] = page
            batch = self._get_collection(tenant_id, endpoint, key, params=page_params)
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    def _raw_get(self, url: str, tenant_id: str | None, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}
        if tenant_id:
            headers["Xero-tenant-id"] = tenant_id

        for attempt in range(4):
            self.rate_limiter.wait()
            response = self.session.get(url, headers=headers, params=params, timeout=45)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                time.sleep(retry_after)
                continue
            if response.status_code >= 500 and attempt < 3:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()
        return response.json()


def normalize_xero_purchase_document(
    tenant_id: str,
    organisation_name: str | None,
    document_type: str,
    document: dict[str, Any],
    contact_by_id: dict[str, dict[str, Any]],
    account_by_code: dict[str, dict[str, Any]],
    config: OrgReviewConfig,
) -> Iterable[TransactionLine]:
    contact = _resolve_contact(document, contact_by_id)
    document_date = _parse_xero_date(document.get("Date") or document.get("UpdatedDateUTC"))
    transaction_id = _document_id(document_type, document)
    document_number = document.get("InvoiceNumber") or document.get("BankTransactionID") or document.get("CreditNoteNumber")
    currency_code = document.get("CurrencyCode") or "ZAR"

    for index, line in enumerate(document.get("LineItems", []) or []):
        account_code = line.get("AccountCode")
        account = account_by_code.get(account_code, {})
        line_id = line.get("LineItemID") or f"{transaction_id}:{index}"
        net = money(line.get("LineAmount"))
        vat = money(line.get("TaxAmount"))
        gross = money(net + vat)
        if document_type == "CREDIT_NOTE":
            net = -abs(net)
            vat = -abs(vat)
            gross = -abs(gross)
        yield TransactionLine(
            tenant_id=tenant_id,
            organisation_name=organisation_name,
            transaction_type=document_type,
            transaction_id=transaction_id,
            line_id=line_id,
            document_number=document_number,
            transaction_date=document_date,
            vat_period=vat_period_label(document_date, config.vat_period_basis),
            supplier_id=contact.get("ContactID"),
            supplier_name=contact.get("Name"),
            supplier_vat_number=contact.get("TaxNumber") or contact.get("VATNumber"),
            account_id=account.get("AccountID"),
            account_code=account_code,
            account_name=account.get("Name"),
            tax_type=line.get("TaxType"),
            description=line.get("Description"),
            net_amount=net,
            vat_amount=vat,
            gross_amount=gross,
            currency_code=currency_code,
            source_url=None,
            raw={"document": document, "line": line},
        )


def _resolve_contact(document: dict[str, Any], contact_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contact = document.get("Contact") or {}
    contact_id = contact.get("ContactID")
    if contact_id and contact_id in contact_by_id:
        merged = dict(contact_by_id[contact_id])
        merged.update({k: v for k, v in contact.items() if v})
        return merged
    return contact


def _document_id(document_type: str, document: dict[str, Any]) -> str:
    if document_type == "INVOICE":
        return str(document.get("InvoiceID"))
    if document_type == "BANK_TRANSACTION":
        return str(document.get("BankTransactionID"))
    if document_type == "CREDIT_NOTE":
        return str(document.get("CreditNoteID"))
    return str(document.get("ID") or document.get("id"))


def _parse_xero_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.startswith("/Date("):
        millis = int(value.split("(")[1].split("+")[0].split("-")[0])
        return datetime.utcfromtimestamp(millis / 1000).date()
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Cannot parse Xero date value: {value!r}")
