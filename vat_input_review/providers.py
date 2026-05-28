from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from .config import OrgReviewConfig
from .models import TransactionLine


@dataclass(frozen=True)
class AccountingOrganisation:
    source_system: str
    tenant_id: str
    name: str | None = None
    raw: dict | None = None


class AccountingProvider(Protocol):
    source_system: str

    def list_organisations(self) -> list[AccountingOrganisation]:
        """Return organisations/businesses available to the authenticated user."""

    def extract_lines(
        self,
        tenant_id: str,
        config: OrgReviewConfig,
        date_from: date,
        date_to: date,
    ) -> list[TransactionLine]:
        """Return normalized purchase-side transaction lines for one tenant only."""
