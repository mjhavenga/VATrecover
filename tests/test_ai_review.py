from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from vat_input_review.ai_review import AIReview, enrich_flags_with_ai
from vat_input_review.models import ReviewFlag, TransactionLine, money


class FakeAIReviewClient:
    def review_flag(self, flag: ReviewFlag) -> AIReview:
        return AIReview(
            ai_risk="medium",
            recommended_action="verify_invoice",
            reviewer_note=f"Verify source invoice for {flag.line.document_number}.",
            evidence_checks=["Supplier VAT number is present", "Confirm invoice is a valid tax invoice"],
            missing_information=["Source invoice PDF"],
            claim_readiness=65,
            model="fake-model",
        )


def make_flag() -> ReviewFlag:
    line = TransactionLine(
        tenant_id="tenant-ai",
        organisation_name="AI Fixture Client",
        transaction_type="INVOICE",
        transaction_id="tx-ai",
        line_id="line-ai",
        document_number="INV-AI",
        transaction_date=date(2026, 1, 15),
        vat_period="2026-01_to_2026-02",
        supplier_id="supplier-ai",
        supplier_name="VAT Vendor",
        supplier_vat_number="4123456789",
        account_id="acct-400",
        account_code="400",
        account_name="Materials",
        tax_type="NONE",
        description="Potential missed VAT",
        net_amount=money("1000.00"),
        vat_amount=money("0.00"),
        gross_amount=money("1000.00"),
        source_system="xero",
    )
    return ReviewFlag(
        line=line,
        reason_code="SUPPLIER_VAT_ZERO_CLAIM",
        reason="Supplier has a VAT number but no input VAT was claimed.",
        confidence=Decimal("0.80"),
        expected_vat=money("150.00"),
        estimated_underclaim=money("150.00"),
        evidence={"supplier_vat_number": "4123456789"},
    )


class AIReviewTests(unittest.TestCase):
    def test_enrich_flags_with_ai_uses_structured_review_client(self):
        flag = make_flag()

        reviews = enrich_flags_with_ai([flag], FakeAIReviewClient())

        self.assertEqual(reviews["line-ai"].ai_risk, "medium")
        self.assertEqual(reviews["line-ai"].recommended_action, "verify_invoice")
        self.assertEqual(reviews["line-ai"].claim_readiness, 65)


if __name__ == "__main__":
    unittest.main()
