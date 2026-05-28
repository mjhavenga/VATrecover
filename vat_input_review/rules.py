from __future__ import annotations

from decimal import Decimal

from .config import OrgReviewConfig
from .models import ReviewFinding, ReviewFlag, TransactionLine, money
from .profiling import BehaviourProfile, ProfileSet


ZERO_TOLERANCE = Decimal("0.01")


def evaluate_lines(lines: list[TransactionLine], profiles: ProfileSet, config: OrgReviewConfig) -> list[ReviewFlag]:
    flags = []
    for line in lines:
        flag = evaluate_line(line, profiles, config)
        if flag:
            flags.append(flag)
    return sorted(flags, key=lambda flag: flag.estimated_underclaim, reverse=True)


def evaluate_line(line: TransactionLine, profiles: ProfileSet, config: OrgReviewConfig) -> ReviewFlag | None:
    if _is_suppressed(line, config):
        return None

    pair_profile = profiles.pair_for(line)
    account_profile = profiles.account_for(line)
    supplier_profile = profiles.supplier_for(line)
    findings: list[ReviewFinding] = []

    if line.has_supplier_vat_number and _has_zero_input_vat(line, config):
        confidence = Decimal("0.70")
        if _profile_implies_standard(pair_profile, config) or _profile_implies_standard(account_profile, config):
            confidence += Decimal("0.10")
        findings.append(
            ReviewFinding(
                reason_code="SUPPLIER_VAT_ZERO_CLAIM",
                reason="Supplier has a VAT number but the line carries no input VAT.",
                confidence=min(confidence, Decimal("0.95")),
                expected_vat=_expected_standard_vat(line, config),
                evidence={"supplier_vat_number": line.supplier_vat_number},
            )
        )

    if config.is_no_vat_tax_type(line.tax_type) and _profile_implies_standard(account_profile, config):
        findings.append(
            ReviewFinding(
                reason_code="ZERO_TAX_ON_STANDARD_ACCOUNT",
                reason="The tax type is no-VAT/zero/exempt but this account normally carries standard-rated input VAT.",
                confidence=Decimal("0.76"),
                expected_vat=_expected_standard_vat(line, config),
                evidence=_profile_evidence("account_profile", account_profile),
            )
        )

    if _effective_rate_below_standard(line, config) and (
        _profile_implies_standard(pair_profile, config)
        or _profile_implies_standard(account_profile, config)
        or _profile_implies_standard(supplier_profile, config)
    ):
        findings.append(
            ReviewFinding(
                reason_code="LOW_EFFECTIVE_RATE",
                reason="The effective VAT rate is below the standard rate where history implies standard rating.",
                confidence=Decimal("0.78"),
                expected_vat=_expected_standard_vat(line, config),
                evidence={
                    "effective_rate": str(line.effective_rate),
                    "standard_rate": str(config.standard_rate),
                },
            )
        )

    if _breaks_pair_pattern(line, pair_profile, config):
        findings.append(
            ReviewFinding(
                reason_code="PAIR_PATTERN_BREAK",
                reason="The line breaks the established tax pattern for this account/supplier pair.",
                confidence=Decimal("0.84"),
                expected_vat=_expected_standard_vat(line, config),
                evidence=_profile_evidence("pair_profile", pair_profile),
            )
        )

    if not findings:
        return None

    best_expected_vat = max((finding.expected_vat for finding in findings), default=money("0"))
    underclaim = money(max(Decimal("0"), abs(best_expected_vat) - abs(line.vat_amount)))
    if underclaim <= ZERO_TOLERANCE:
        return None

    confidence = min(sum((finding.confidence for finding in findings), Decimal("0")) / Decimal(len(findings)) + _confidence_boost(findings), Decimal("0.99"))
    if confidence < config.min_confidence:
        return None

    return ReviewFlag(
        line=line,
        reason_code=";".join(finding.reason_code for finding in findings),
        reason=" ".join(finding.reason for finding in findings),
        confidence=confidence.quantize(Decimal("0.01")),
        expected_vat=best_expected_vat,
        estimated_underclaim=underclaim,
        evidence={finding.reason_code: finding.evidence for finding in findings},
    )


def _is_suppressed(line: TransactionLine, config: OrgReviewConfig) -> bool:
    return config.is_account_suppressed(line.account_id, line.account_code, line.account_name) or config.is_supplier_suppressed(
        line.supplier_id, line.supplier_name
    )


def _has_zero_input_vat(line: TransactionLine, config: OrgReviewConfig) -> bool:
    return abs(line.vat_amount) <= ZERO_TOLERANCE or config.is_no_vat_tax_type(line.tax_type)


def _expected_standard_vat(line: TransactionLine, config: OrgReviewConfig):
    return money(abs(line.net_amount) * config.standard_rate)


def _effective_rate_below_standard(line: TransactionLine, config: OrgReviewConfig) -> bool:
    if abs(line.net_amount) <= ZERO_TOLERANCE:
        return False
    if line.effective_rate <= ZERO_TOLERANCE:
        return True
    threshold = config.standard_rate * config.low_rate_threshold
    return line.effective_rate < threshold


def _profile_implies_standard(profile: BehaviourProfile | None, config: OrgReviewConfig) -> bool:
    return bool(profile and profile.implies_standard_input(config))


def _breaks_pair_pattern(line: TransactionLine, profile: BehaviourProfile | None, config: OrgReviewConfig) -> bool:
    if not profile or not profile.is_trusted(config):
        return False
    if profile.modal_tax_type_share < config.modal_share_threshold:
        return False
    current_tax_type = config.canonical_tax_type(line.tax_type)
    tax_type_break = current_tax_type != profile.modal_tax_type and profile.implies_standard_input(config)
    rate_break = abs(line.effective_rate - profile.median_effective_rate) > config.standard_rate_tolerance
    return tax_type_break or (profile.implies_standard_input(config) and rate_break and _effective_rate_below_standard(line, config))


def _profile_evidence(label: str, profile: BehaviourProfile | None) -> dict:
    if profile is None:
        return {}
    return {
        label: {
            "sample_size": profile.sample_size,
            "modal_tax_type": profile.modal_tax_type,
            "modal_tax_type_share": str(profile.modal_tax_type_share.quantize(Decimal("0.01"))),
            "median_effective_rate": str(profile.median_effective_rate),
            "standard_rated_share": str(profile.standard_rated_share.quantize(Decimal("0.01"))),
            "example_line_ids": list(profile.example_line_ids),
        }
    }


def _confidence_boost(findings: list[ReviewFinding]) -> Decimal:
    if len(findings) >= 3:
        return Decimal("0.08")
    if len(findings) == 2:
        return Decimal("0.04")
    return Decimal("0")
