from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median

from .config import OrgReviewConfig
from .models import TransactionLine


@dataclass(frozen=True)
class BehaviourProfile:
    key: str | tuple[str, str]
    sample_size: int
    modal_tax_type: str
    modal_tax_type_share: Decimal
    median_effective_rate: Decimal
    standard_rated_share: Decimal
    supplier_vat_number_seen: bool = False
    example_line_ids: tuple[str, ...] = field(default_factory=tuple)

    def is_trusted(self, config: OrgReviewConfig) -> bool:
        return self.sample_size >= config.minimum_sample_size

    def implies_standard_input(self, config: OrgReviewConfig) -> bool:
        if not self.is_trusted(config):
            return False
        near_standard = abs(self.median_effective_rate - config.standard_rate) <= config.standard_rate_tolerance
        modal_standard = config.is_standard_input_tax_type(self.modal_tax_type)
        share_standard = self.standard_rated_share >= config.modal_share_threshold
        return near_standard or modal_standard or share_standard


@dataclass(frozen=True)
class ProfileSet:
    by_account_supplier: dict[tuple[str, str], BehaviourProfile]
    by_account: dict[str, BehaviourProfile]
    by_supplier: dict[str, BehaviourProfile]

    def pair_for(self, line: TransactionLine) -> BehaviourProfile | None:
        return self.by_account_supplier.get(line.pair_key)

    def account_for(self, line: TransactionLine) -> BehaviourProfile | None:
        return self.by_account.get(line.account_key)

    def supplier_for(self, line: TransactionLine) -> BehaviourProfile | None:
        return self.by_supplier.get(line.supplier_key)


def build_profiles(lines: list[TransactionLine], config: OrgReviewConfig) -> ProfileSet:
    """Build adaptive profiles from one organisation's own history."""
    return ProfileSet(
        by_account_supplier=_profile_group(lines, config, key_fn=lambda line: line.pair_key),
        by_account=_profile_group(lines, config, key_fn=lambda line: line.account_key),
        by_supplier=_profile_group(lines, config, key_fn=lambda line: line.supplier_key),
    )


def _profile_group(lines: list[TransactionLine], config: OrgReviewConfig, key_fn) -> dict:
    grouped: dict[object, list[TransactionLine]] = defaultdict(list)
    for line in lines:
        if line.net_amount == 0:
            continue
        if config.is_account_suppressed(line.account_id, line.account_code, line.account_name):
            continue
        if config.is_supplier_suppressed(line.supplier_id, line.supplier_name):
            continue
        grouped[key_fn(line)].append(line)

    return {key: _profile_lines(key, values, config) for key, values in grouped.items()}


def _profile_lines(key, lines: list[TransactionLine], config: OrgReviewConfig) -> BehaviourProfile:
    tax_types = [config.canonical_tax_type(line.tax_type) for line in lines if line.tax_type]
    tax_counter = Counter(tax_types)
    modal_tax_type, modal_count = tax_counter.most_common(1)[0] if tax_counter else ("", 0)
    effective_rates = [line.effective_rate for line in lines if line.net_amount != 0]
    standard_count = sum(
        1
        for line in lines
        if config.is_standard_input_tax_type(line.tax_type)
        or abs(line.effective_rate - config.standard_rate) <= config.standard_rate_tolerance
    )
    sample_size = len(lines)
    return BehaviourProfile(
        key=key,
        sample_size=sample_size,
        modal_tax_type=modal_tax_type,
        modal_tax_type_share=Decimal(modal_count) / Decimal(sample_size) if sample_size else Decimal("0"),
        median_effective_rate=Decimal(str(median(effective_rates))).quantize(Decimal("0.0001"))
        if effective_rates
        else Decimal("0"),
        standard_rated_share=Decimal(standard_count) / Decimal(sample_size) if sample_size else Decimal("0"),
        supplier_vat_number_seen=any(line.has_supplier_vat_number for line in lines),
        example_line_ids=tuple(line.line_id for line in lines[:5]),
    )
