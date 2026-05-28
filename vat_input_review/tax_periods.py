from __future__ import annotations

from datetime import date


def vat_period_label(value: date, basis: str = "bi-monthly") -> str:
    basis_key = basis.strip().lower().replace("_", "-")
    if basis_key in {"monthly", "month"}:
        return f"{value.year}-{value.month:02d}"

    if basis_key in {"bi-monthly", "bimonthly", "two-monthly", "two-month"}:
        start_month = value.month if value.month % 2 == 1 else value.month - 1
        end_month = start_month + 1
        return f"{value.year}-{start_month:02d}_to_{value.year}-{end_month:02d}"

    if basis_key in {"bi-monthly-even", "bimonthly-even"}:
        if value.month % 2 == 0:
            start_month = value.month - 1
            end_month = value.month
            year = value.year
        else:
            start_month = value.month
            end_month = value.month + 1
            year = value.year
        return f"{year}-{start_month:02d}_to_{year}-{end_month:02d}"

    if basis_key in {"quarterly", "quarter"}:
        quarter = ((value.month - 1) // 3) + 1
        return f"{value.year}-Q{quarter}"

    if basis_key in {"annual", "yearly"}:
        return str(value.year)

    return f"{value.year}-{value.month:02d}"
