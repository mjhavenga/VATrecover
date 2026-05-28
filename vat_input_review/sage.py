from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from .auth import FileTokenStore
from .config import OrgReviewConfig
from .models import TransactionLine, money
from .providers import AccountingOrganisation
from .tax_periods import vat_period_label


SAGE_AUTH_URL = "https://www.sageone.com/oauth2/auth/central"
SAGE_TOKEN_URL = "https://oauth.accounting.sage.com/token"
SAGE_API_BASE = "https://api.accounting.sage.com/v3.1"


@dataclass(frozen=True)
class SageOAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ("full_access",)


class SageAuthClient:
    def __init__(self, config: SageOAuthConfig, token_store: FileTokenStore):
        self.config = config
        self.token_store = token_store

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "scope": " ".join(self.config.scopes),
                "state": state,
            }
        )
        return f"{SAGE_AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        import requests

        response = requests.post(
            SAGE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        self.token_store.save(token)
        return token

    def refresh(self) -> dict[str, Any]:
        import requests

        token = self.token_store.load()
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No Sage refresh_token found. Complete OAuth first.")
        response = requests.post(
            SAGE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
            timeout=30,
        )
        response.raise_for_status()
        refreshed = response.json()
        self.token_store.save(refreshed)
        return refreshed

    def access_token(self) -> str:
        token = self.token_store.load()
        if not token:
            raise RuntimeError("No Sage token found. Complete OAuth first.")
        if int(token.get("expires_at", 0)) <= int(time.time()):
            token = self.refresh()
        return str(token["access_token"])


class SageAccountingClient:
    """Read-only Sage Business Cloud Accounting extractor.

    Sage calls client organisations "businesses"; each API request is scoped by
    the X-Business header so data from different clients is never mixed.
    """

    source_system = "sage"

    def __init__(self, access_token: str):
        import requests

        self.access_token = access_token
        self.session = requests.Session()

    def list_organisations(self) -> list[AccountingOrganisation]:
        businesses = self._get_collection("businesses")
        return [
            AccountingOrganisation(
                source_system=self.source_system,
                tenant_id=str(item.get("id")),
                name=item.get("displayed_as") or item.get("name"),
                raw=item,
            )
            for item in businesses
            if item.get("id")
        ]

    def extract_lines(self, tenant_id: str, config: OrgReviewConfig, date_from: date, date_to: date) -> list[TransactionLine]:
        contacts = self._get_collection("contacts", business_id=tenant_id, params={"items_per_page": 200})
        ledger_accounts = self._get_collection("ledger_accounts", business_id=tenant_id, params={"items_per_page": 200})
        contacts_by_id = {str(item.get("id")): item for item in contacts if item.get("id")}
        accounts_by_id = {str(item.get("id")): item for item in ledger_accounts if item.get("id")}

        params = {
            "from_date": date_from.isoformat(),
            "to_date": date_to.isoformat(),
            "items_per_page": 200,
        }
        documents: list[tuple[str, dict[str, Any]]] = []
        documents.extend(("PURCHASE_INVOICE", item) for item in self._get_collection("purchase_invoices", business_id=tenant_id, params=params))
        documents.extend(("PURCHASE_CREDIT_NOTE", item) for item in self._get_collection("purchase_credit_notes", business_id=tenant_id, params=params))

        lines: list[TransactionLine] = []
        for document_type, document in documents:
            lines.extend(
                normalize_sage_purchase_document(
                    tenant_id=tenant_id,
                    organisation_name=config.organisation_name,
                    document_type=document_type,
                    document=document,
                    contacts_by_id=contacts_by_id,
                    accounts_by_id=accounts_by_id,
                    config=config,
                )
            )
        return lines

    def _get_collection(
        self,
        endpoint: str,
        business_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            request_params = dict(params or {})
            request_params.setdefault("page", page)
            payload = self._raw_get(endpoint, business_id=business_id, params=request_params)
            if isinstance(payload, list):
                batch = payload
            else:
                batch = payload.get("$items") or payload.get("items") or []
            items.extend(batch)
            if not isinstance(batch, list) or not batch:
                break
            page_info = payload.get("$total") if isinstance(payload, dict) else None
            if page_info is None and len(batch) < int(request_params.get("items_per_page", 200)):
                break
            if page_info is not None and len(items) >= int(page_info):
                break
            page += 1
        return items

    def _raw_get(self, endpoint: str, business_id: str | None, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}
        if business_id:
            headers["X-Business"] = business_id
        response = self.session.get(f"{SAGE_API_BASE}/{endpoint}", headers=headers, params=params, timeout=45)
        if response.status_code == 429:
            time.sleep(int(response.headers.get("Retry-After", "60")))
            response = self.session.get(f"{SAGE_API_BASE}/{endpoint}", headers=headers, params=params, timeout=45)
        response.raise_for_status()
        return response.json()


def normalize_sage_purchase_document(
    tenant_id: str,
    organisation_name: str | None,
    document_type: str,
    document: dict[str, Any],
    contacts_by_id: dict[str, dict[str, Any]],
    accounts_by_id: dict[str, dict[str, Any]],
    config: OrgReviewConfig,
) -> list[TransactionLine]:
    contact = _resolve_sage_ref(document.get("contact"), contacts_by_id)
    document_date = _parse_sage_date(document.get("date") or document.get("created_at"))
    transaction_id = str(document.get("id"))
    document_number = document.get("reference") or document.get("displayed_as")
    lines = []
    for index, line in enumerate(document.get("invoice_lines") or document.get("lines") or []):
        account = _resolve_sage_ref(line.get("ledger_account"), accounts_by_id)
        net = money(line.get("net_amount") or line.get("total_amount") or 0)
        vat = money(line.get("tax_amount") or line.get("total_tax_amount") or 0)
        if document_type == "PURCHASE_CREDIT_NOTE":
            net = -abs(net)
            vat = -abs(vat)
        tax_rate = line.get("tax_rate") or {}
        lines.append(
            TransactionLine(
                source_system="sage",
                tenant_id=tenant_id,
                organisation_name=organisation_name,
                transaction_type=document_type,
                transaction_id=transaction_id,
                line_id=str(line.get("id") or f"{transaction_id}:{index}"),
                document_number=document_number,
                transaction_date=document_date,
                vat_period=vat_period_label(document_date, config.vat_period_basis),
                supplier_id=str(contact.get("id")) if contact.get("id") else None,
                supplier_name=contact.get("displayed_as") or contact.get("name"),
                supplier_vat_number=contact.get("tax_number") or contact.get("vat_number"),
                account_id=str(account.get("id")) if account.get("id") else None,
                account_code=account.get("nominal_code") or account.get("ledger_account_number"),
                account_name=account.get("displayed_as") or account.get("name"),
                tax_type=tax_rate.get("id") or tax_rate.get("displayed_as") or tax_rate.get("name"),
                description=line.get("description"),
                net_amount=net,
                vat_amount=vat,
                gross_amount=money(net + vat),
                currency_code=(document.get("currency") or {}).get("id") or "ZAR",
                raw={"document": document, "line": line},
            )
        )
    return lines


def _resolve_sage_ref(value: Any, by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    ref_id = value.get("id")
    if ref_id and str(ref_id) in by_id:
        merged = dict(by_id[str(ref_id)])
        merged.update({k: v for k, v in value.items() if v})
        return merged
    return value


def _parse_sage_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    raise ValueError(f"Cannot parse Sage date value: {value!r}")
