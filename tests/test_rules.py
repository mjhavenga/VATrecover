from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from vat_input_review.config import OrgReviewConfig
from vat_input_review.models import TransactionLine, money
from vat_input_review.profiling import build_profiles
from vat_input_review.rules import evaluate_line, evaluate_lines


TENANT_ID = "tenant-a"


def make_config(**overrides):
    values = {
        "tenant_id": TENANT_ID,
        "organisation_name": "Fixture Client",
        "minimum_sample_size": 3,
        "standard_rate": Decimal("0.15"),
        "blocked_input_vat_accounts": set(),
        "apportionment_accounts": set(),
        "exempt_or_zero_rated_accounts": set(),
        "non_vat_supplier_ids": set(),
        "non_vat_supplier_names": set(),
    }
    values.update(overrides)
    return OrgReviewConfig(**values)


def make_line(
    line_id: str,
    *,
    supplier_id: str = "supplier-1",
    supplier_name: str = "VAT Vendor",
    supplier_vat_number: str | None = "4123456789",
    account_code: str = "400",
    account_name: str = "Materials",
    tax_type: str = "INPUT",
    net: str = "1000.00",
    vat: str = "150.00",
    tx_date: date = date(2026, 1, 15),
) -> TransactionLine:
    net_amount = money(net)
    vat_amount = money(vat)
    return TransactionLine(
        source_system="xero",
        tenant_id=TENANT_ID,
        organisation_name="Fixture Client",
        transaction_type="INVOICE",
        transaction_id=f"tx-{line_id}",
        line_id=line_id,
        document_number=f"DOC-{line_id}",
        transaction_date=tx_date,
        vat_period="2026-01_to_2026-02",
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        supplier_vat_number=supplier_vat_number,
        account_id=f"acct-{account_code}",
        account_code=account_code,
        account_name=account_name,
        tax_type=tax_type,
        description="Fixture purchase",
        net_amount=net_amount,
        vat_amount=vat_amount,
        gross_amount=money(net_amount + vat_amount),
        currency_code="ZAR",
    )


class RuleEngineTests(unittest.TestCase):
    def test_flags_vat_registered_supplier_with_zero_input_vat(self):
        config = make_config()
        history = [make_line(f"hist-{idx}") for idx in range(3)]
        profiles = build_profiles(history, config)

        review_line = make_line("review-1", tax_type="NONE", vat="0.00")
        flag = evaluate_line(review_line, profiles, config)

        self.assertIsNotNone(flag)
        assert flag is not None
        self.assertIn("SUPPLIER_VAT_ZERO_CLAIM", flag.reason_code)
        self.assertEqual(flag.expected_vat, money("150.00"))
        self.assertEqual(flag.estimated_underclaim, money("150.00"))

    def test_flags_zero_tax_type_on_account_that_normally_claims_input(self):
        config = make_config()
        history = [make_line(f"hist-{idx}", supplier_id=f"supplier-{idx}") for idx in range(3)]
        profiles = build_profiles(history, config)

        review_line = make_line("review-2", supplier_id="new-supplier", tax_type="ZERORATEDINPUT", vat="0.00")
        flag = evaluate_line(review_line, profiles, config)

        self.assertIsNotNone(flag)
        assert flag is not None
        self.assertIn("ZERO_TAX_ON_STANDARD_ACCOUNT", flag.reason_code)

    def test_flags_low_effective_rate_when_pair_history_is_standard(self):
        config = make_config()
        history = [make_line(f"hist-{idx}") for idx in range(3)]
        profiles = build_profiles(history, config)

        review_line = make_line("review-3", tax_type="INPUT", vat="50.00")
        flag = evaluate_line(review_line, profiles, config)

        self.assertIsNotNone(flag)
        assert flag is not None
        self.assertIn("LOW_EFFECTIVE_RATE", flag.reason_code)
        self.assertEqual(flag.estimated_underclaim, money("100.00"))

    def test_suppresses_blocked_input_vat_accounts(self):
        config = make_config(blocked_input_vat_accounts={"ENTERTAINMENT"})
        history = [make_line(f"hist-{idx}", account_name="Entertainment") for idx in range(3)]
        profiles = build_profiles(history, config)

        review_line = make_line("review-4", account_name="Entertainment", tax_type="NONE", vat="0.00")
        flag = evaluate_line(review_line, profiles, config)

        self.assertIsNone(flag)

    def test_suppresses_configured_non_vat_supplier(self):
        config = make_config(non_vat_supplier_ids={"supplier-1"})
        history = [make_line(f"hist-{idx}", supplier_vat_number=None, tax_type="NONE", vat="0.00") for idx in range(3)]
        profiles = build_profiles(history, config)

        review_line = make_line("review-5", supplier_vat_number=None, tax_type="NONE", vat="0.00")
        flag = evaluate_line(review_line, profiles, config)

        self.assertIsNone(flag)

    def test_evaluate_lines_returns_flags_sorted_by_underclaim(self):
        config = make_config()
        history = [make_line(f"hist-{idx}") for idx in range(3)]
        profiles = build_profiles(history, config)
        flags = evaluate_lines(
            [
                make_line("small", net="100.00", vat="0.00", tax_type="NONE"),
                make_line("large", net="2000.00", vat="0.00", tax_type="NONE"),
            ],
            profiles,
            config,
        )

        self.assertEqual([flag.line.line_id for flag in flags], ["large", "small"])


if __name__ == "__main__":
    unittest.main()
