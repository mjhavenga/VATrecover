from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from vat_input_review.config import OrgReviewConfig
from vat_input_review.pastel import load_pastel_export


class PastelImportTests(unittest.TestCase):
    def test_loads_pastel_csv_export_into_normalized_lines(self):
        config = OrgReviewConfig(
            tenant_id="pastel-client",
            organisation_name="Pastel Fixture Client",
            minimum_sample_size=1,
            standard_rate=Decimal("0.15"),
        )
        fixture = Path(__file__).resolve().parents[1] / "examples" / "pastel_purchase_export.csv"

        result = load_pastel_export(fixture, config)

        self.assertEqual(len(result.lines), 2)
        first = result.lines[0]
        self.assertEqual(first.source_system, "pastel")
        self.assertEqual(first.tenant_id, "pastel-client")
        self.assertEqual(first.supplier_name, "VAT Vendor")
        self.assertEqual(first.account_code, "400")
        self.assertEqual(first.tax_type, "NONE")
        self.assertEqual(str(first.net_amount), "2000.00")


if __name__ == "__main__":
    unittest.main()
