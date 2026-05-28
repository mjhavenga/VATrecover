from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from vat_input_review.date_ranges import chunk_date_range
from vat_input_review.exports import export_transaction_pack
from vat_input_review.models import TransactionLine, money


def make_line(line_id: str = "line-1") -> TransactionLine:
    return TransactionLine(
        tenant_id="tenant-export",
        organisation_name="Export Client",
        transaction_type="INVOICE",
        transaction_id="tx-export",
        line_id=line_id,
        document_number="INV-001",
        transaction_date=date(2026, 1, 15),
        vat_period="2026-01_to_2026-02",
        supplier_id="supplier-1",
        supplier_name="VAT Vendor",
        supplier_vat_number="4123456789",
        account_id="acct-400",
        account_code="400",
        account_name="Materials",
        tax_type="INPUT",
        description="Purchase line",
        net_amount=money("1000.00"),
        vat_amount=money("150.00"),
        gross_amount=money("1150.00"),
        source_system="xero",
    )


class ExportTests(unittest.TestCase):
    def test_chunk_date_range_monthly(self):
        chunks = chunk_date_range(date(2026, 1, 15), date(2026, 3, 10), "monthly")

        self.assertEqual(
            chunks,
            [
                (date(2026, 1, 15), date(2026, 1, 31)),
                (date(2026, 2, 1), date(2026, 2, 28)),
                (date(2026, 3, 1), date(2026, 3, 10)),
            ],
        )

    def test_export_transaction_pack_writes_ai_ready_csv_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_transaction_pack(
                [make_line()],
                Path(tmp),
                "tenant-export",
                (date(2026, 1, 1), date(2026, 1, 31)),
                formats={"csv", "json"},
            )

            self.assertTrue(paths.csv_path and paths.csv_path.exists())
            self.assertTrue(paths.json_path and paths.json_path.exists())

            with paths.csv_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["source_system"], "xero")
            self.assertIn("input VAT", rows[0]["ai_review_prompt"])

            payload = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["tenant_id"], "tenant-export")
            self.assertIn("ai_review_instruction", payload[0])


if __name__ == "__main__":
    unittest.main()
